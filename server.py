"""MCP server for Outlook email and calendar via Microsoft Graph.

Starts a FastMCP server with Streamable HTTP transport and OAuth 2.1 + DCR.
The MCP server acts as an OAuth proxy — users authenticate directly with Entra
ID and the server uses their delegated token to call Graph API as /me.

Environment variables
---------------------
ENTRA_TENANT_ID    : Entra tenant ID; use "common" for personal + work accounts
ENTRA_CLIENT_ID    : Entra app client ID (delegated Mail.Read, Calendars.Read)
ENTRA_CLIENT_SECRET: Entra app client secret
SERVER_URL         : Public URL of this server (default: http://localhost:8000)
HOST               : Bind host (default: 0.0.0.0)
PORT               : Bind port (default: 8000)
"""

import logging
import os
import secrets
import time
import urllib.parse
from collections.abc import Callable
from contextvars import ContextVar

import httpx
import uvicorn
from azure.core.credentials import AccessToken as AzureAccessToken
from dotenv import load_dotenv
from msgraph_beta import GraphServiceClient
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from outlook.calendar import register_calendar_tools
from outlook.mail import register_mail_tools

load_dotenv()

logger = logging.getLogger(__name__)

_MCP_SCOPES = ["mail.read", "calendar.read"]
_ENTRA_SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Calendars.Read",
    "offline_access",
]

_entra_tenant = os.environ.get("ENTRA_TENANT_ID", "common")
_entra_client_id = os.environ.get("ENTRA_CLIENT_ID", "")
_entra_client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "")
_server_url = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
_host = os.environ.get("HOST", "0.0.0.0")
_port = int(os.environ.get("PORT", "8000"))

if not _entra_client_id or not _entra_client_secret:
    raise RuntimeError("ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET must be set.")

_ENTRA_AUTH_URL = (
    f"https://login.microsoftonline.com/{_entra_tenant}/oauth2/v2.0/authorize"
)
_ENTRA_TOKEN_URL = (
    f"https://login.microsoftonline.com/{_entra_tenant}/oauth2/v2.0/token"
)

_current_entra_token: ContextVar[str] = ContextVar("entra_token", default="")


class _BearerTokenCredential:
    """Async Azure credential backed by a static bearer token."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self, *scopes: str, **kwargs) -> AzureAccessToken:
        return AzureAccessToken(self._token, int(time.time()) + 3600)

    async def close(self) -> None:
        pass


class _OAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """OAuth AS with DCR that proxies authentication to Entra ID.

    Claude registers via POST /register, then initiates the authorization code
    flow. The /authorize handler redirects to Entra; the /auth/callback handler
    exchanges the Entra code for tokens and issues an MCP auth code to Claude.
    """

    def __init__(self) -> None:
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._pending: dict[str, tuple[OAuthClientInformationFull, AuthorizationParams, float]] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._token_to_entra: dict[str, str] = {}
        self._refresh_to_entra: dict[str, str] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        entra_state = secrets.token_urlsafe(16)
        self._pending[entra_state] = (client, params, time.time() + 600)
        self._purge_expired_pending()
        qs = urllib.parse.urlencode({
            "client_id": _entra_client_id,
            "response_type": "code",
            "redirect_uri": f"{_server_url}/auth/callback",
            "scope": " ".join(_ENTRA_SCOPES),
            "state": entra_state,
            "response_mode": "query",
        })
        return f"{_ENTRA_AUTH_URL}?{qs}"

    def _purge_expired_pending(self) -> None:
        now = time.time()
        expired = [s for s, (_, _, exp) in self._pending.items() if exp < now]
        for s in expired:
            del self._pending[s]

    async def handle_entra_callback(self, entra_code: str, entra_state: str) -> str:
        """Exchange an Entra auth code for tokens; issue an MCP auth code.

        Returns the redirect URL to send the user back to Claude with the MCP
        auth code.
        """
        pending = self._pending.pop(entra_state, None)
        if pending is None:
            raise ValueError(f"Unknown Entra state: {entra_state!r}")

        client, params, expires_at = pending
        if expires_at < time.time():
            raise ValueError("Entra OAuth state has expired")

        async with httpx.AsyncClient() as http:
            try:
                resp = await http.post(
                    _ENTRA_TOKEN_URL,
                    data={
                        "client_id": _entra_client_id,
                        "client_secret": _entra_client_secret,
                        "code": entra_code,
                        "redirect_uri": f"{_server_url}/auth/callback",
                        "grant_type": "authorization_code",
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Entra token exchange failed: {exc}") from exc
            token_data = resp.json()

        entra_access_token = token_data.get("access_token")
        if not entra_access_token:
            raise RuntimeError("Entra token response missing access_token")
        entra_refresh_token: str = token_data.get("refresh_token", "")

        mcp_code = secrets.token_urlsafe(32)
        self._auth_codes[mcp_code] = AuthorizationCode(
            code=mcp_code,
            scopes=params.scopes or _MCP_SCOPES,
            expires_at=time.time() + 600,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        self._token_to_entra[mcp_code] = entra_access_token
        if entra_refresh_token:
            self._refresh_to_entra[mcp_code] = entra_refresh_token

        return construct_redirect_uri(
            str(params.redirect_uri), code=mcp_code, state=params.state
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        if code.expires_at < time.time():
            del self._auth_codes[authorization_code]
            self._token_to_entra.pop(authorization_code, None)
            self._refresh_to_entra.pop(authorization_code, None)
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        entra_token = self._token_to_entra.pop(authorization_code.code, "")
        entra_refresh = self._refresh_to_entra.pop(authorization_code.code, "")
        self._auth_codes.pop(authorization_code.code, None)

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        expires_in = 3600
        self._access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + expires_in,
        )
        self._refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
        )
        if entra_token:
            self._token_to_entra[access_token] = entra_token
        if entra_refresh:
            self._refresh_to_entra[refresh_token] = entra_refresh

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        at = self._access_tokens.get(token)
        if at is None:
            return None
        if at.expires_at is not None and at.expires_at < time.time():
            del self._access_tokens[token]
            self._token_to_entra.pop(token, None)
            self._refresh_to_entra.pop(token, None)
            return None
        _current_entra_token.set(self._token_to_entra.get(token, ""))
        return at

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        rt = self._refresh_tokens.get(refresh_token)
        if rt is None or rt.client_id != client.client_id:
            return None
        return rt

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        entra_refresh = self._refresh_to_entra.pop(refresh_token.token, "")
        self._refresh_tokens.pop(refresh_token.token, None)

        entra_token = ""
        new_entra_refresh = ""
        if entra_refresh:
            async with httpx.AsyncClient() as http:
                resp = await http.post(
                    _ENTRA_TOKEN_URL,
                    data={
                        "client_id": _entra_client_id,
                        "client_secret": _entra_client_secret,
                        "refresh_token": entra_refresh,
                        "grant_type": "refresh_token",
                        "scope": " ".join(_ENTRA_SCOPES),
                    },
                )
                if resp.is_success:
                    token_data = resp.json()
                    entra_token = token_data.get("access_token", "")
                    new_entra_refresh = token_data.get("refresh_token", entra_refresh)
                else:
                    logger.warning(
                        "Entra refresh token exchange failed: %s %s",
                        resp.status_code,
                        resp.text,
                    )

        access_token = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        expires_in = 3600
        effective_scopes = scopes or refresh_token.scopes
        self._access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=int(time.time()) + expires_in,
        )
        self._refresh_tokens[new_refresh] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=effective_scopes,
        )
        if entra_token:
            self._token_to_entra[access_token] = entra_token
        if new_entra_refresh:
            self._refresh_to_entra[new_refresh] = new_entra_refresh

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
            refresh_token=new_refresh,
            scope=" ".join(effective_scopes),
        )


provider = _OAuthProvider()

mcp = FastMCP(
    name="Outlook MCP",
    instructions=(
        "Tools for searching and reading Outlook emails and calendar events "
        "via the Microsoft Graph API."
    ),
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(_server_url),
        resource_server_url=None,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=_MCP_SCOPES,
            default_scopes=_MCP_SCOPES,
        ),
        required_scopes=_MCP_SCOPES,
    ),
    host=_host,
    port=_port,
)


def _get_graph_client() -> GraphServiceClient:
    """Build a per-request GraphServiceClient using the authenticated user's Entra token."""
    token = _current_entra_token.get()
    if not token:
        raise RuntimeError("No Entra token available for this request")
    return GraphServiceClient(credentials=_BearerTokenCredential(token))


register_mail_tools(mcp, _get_graph_client)
register_calendar_tools(mcp, _get_graph_client)


async def _auth_callback(request: Request) -> Response:
    error = request.query_params.get("error")
    if error:
        desc = request.query_params.get("error_description", error)
        return Response(f"Authentication error: {desc}", status_code=400)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return Response("Missing code or state parameters", status_code=400)

    try:
        redirect_url = await provider.handle_entra_callback(code, state)
    except Exception as exc:
        logger.error("Entra callback error: %s", exc)
        return Response("Authentication failed", status_code=500)

    return RedirectResponse(redirect_url, status_code=302)


def main() -> None:
    """Run the MCP server with Streamable HTTP transport."""
    mcp_app = mcp.streamable_http_app()
    app = Starlette(routes=[
        Route("/auth/callback", endpoint=_auth_callback),
        Mount("/", app=mcp_app),
    ])
    uvicorn.run(app, host=_host, port=_port)


if __name__ == "__main__":
    main()
