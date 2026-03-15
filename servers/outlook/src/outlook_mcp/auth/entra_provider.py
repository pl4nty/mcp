"""Microsoft Entra ID OAuth provider for the MCP authorization server.

The MCP server acts as an OAuth 2.1 Authorization Server (AS) that proxies
user authentication to Microsoft Entra ID. This allows Claude's custom
connector OAuth flow to work with any Microsoft account, including outlook.com.

Flow:
  1. Claude's client discovers the MCP server's AS metadata.
  2. Claude registers itself via Dynamic Client Registration (DCR).
  3. Claude sends the user to the MCP server's /authorize endpoint.
  4. The MCP server redirects the user to Microsoft Entra ID for login.
  5. After login, Entra ID redirects back to /oauth/callback on this server.
  6. This server exchanges the Entra code for an Entra token, then generates
     its own MCP authorization code and redirects the user to Claude's
     callback URI (https://claude.ai/api/mcp/auth_callback).
  7. Claude exchanges the MCP auth code for an MCP access token.
  8. On each MCP request, this server validates the MCP token and uses the
     stored Entra access token to call the Microsoft Graph API.
"""

import secrets
import time
from urllib.parse import urlencode

import httpx
from pydantic import AnyUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

# Microsoft Graph scopes required by this server's tools
_GRAPH_SCOPES = "offline_access Mail.Read Calendars.Read User.Read"

# MCP-level scopes exposed to clients (Claude)
MCP_SCOPES = ["mail.read", "calendar.read"]


class EntraAuthorizationCode(AuthorizationCode):
    """Authorization code that carries the Entra tokens obtained during the proxy flow."""

    entra_access_token: str
    entra_refresh_token: str
    entra_expires_at: int


class EntraRefreshToken(RefreshToken):
    """Refresh token that wraps an Entra ID refresh token."""

    entra_refresh_token: str


class EntraAccessToken(AccessToken):
    """Access token that embeds the Entra ID access token for Graph API calls."""

    entra_access_token: str


class EntraOAuthProvider(
    OAuthAuthorizationServerProvider[
        EntraAuthorizationCode,
        EntraRefreshToken,
        EntraAccessToken,
    ]
):
    """OAuth Authorization Server provider that proxies auth to Microsoft Entra ID.

    Stores all state in memory. This is appropriate for a single-instance
    deployment. For multi-instance deployments, replace the dicts with a
    shared store (e.g. Redis).
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        server_url: str,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        # Public URL of this MCP server, used to build the Entra redirect URI.
        self._server_url = server_url.rstrip("/")

        # In-memory stores (replace with a persistent store for production).
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, EntraAuthorizationCode] = {}
        self._access_tokens: dict[str, EntraAccessToken] = {}
        self._refresh_tokens: dict[str, EntraRefreshToken] = {}

        # Maps Entra ID state → MCP authorization request context, so that the
        # callback can complete the MCP authorization code issuance.
        self._pending: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Dynamic Client Registration (RFC 7591)
    # ------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    # ------------------------------------------------------------------
    # Authorization endpoint
    # ------------------------------------------------------------------

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Redirect the MCP client to Entra ID for user authentication.

        Stores the MCP request context keyed by a random Entra state value so
        that handle_entra_callback() can finish the MCP authorization code
        issuance after Entra ID redirects back.
        """
        entra_state = secrets.token_urlsafe(32)

        self._pending[entra_state] = {
            "client_id": client.client_id,
            "mcp_redirect_uri": str(params.redirect_uri),
            "scopes": params.scopes or MCP_SCOPES,
            "code_challenge": params.code_challenge,
            "mcp_state": params.state,
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
        }

        entra_redirect = f"{self._server_url}/oauth/callback"
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": entra_redirect,
                "response_mode": "query",
                "scope": _GRAPH_SCOPES,
                "state": entra_state,
            }
        )
        return (
            f"https://login.microsoftonline.com/{self._tenant_id}"
            f"/oauth2/v2.0/authorize?{query}"
        )

    # ------------------------------------------------------------------
    # Entra ID callback (not part of OAuthAuthorizationServerProvider —
    # called from the /oauth/callback custom route in server.py)
    # ------------------------------------------------------------------

    async def handle_entra_callback(self, code: str, state: str) -> str:
        """Handle the Entra ID authorization callback.

        Exchanges the Entra code for tokens, creates an MCP authorization code,
        and returns the URL that the server should redirect the browser to
        (Claude's callback URI with the MCP auth code).

        Raises:
            ValueError: if the state is unknown or the token exchange fails.
        """
        context = self._pending.pop(state, None)
        if context is None:
            raise ValueError(f"Unknown or expired state: {state!r}")

        entra_redirect = f"{self._server_url}/oauth/callback"

        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": entra_redirect,
                    "scope": _GRAPH_SCOPES,
                },
                timeout=30,
            )
            response.raise_for_status()
            token_data = response.json()

        entra_access_token: str = token_data["access_token"]
        entra_refresh_token: str = token_data.get("refresh_token", "")
        expires_in: int = int(token_data.get("expires_in", 3600))

        mcp_code = secrets.token_urlsafe(32)
        self._auth_codes[mcp_code] = EntraAuthorizationCode(
            code=mcp_code,
            scopes=context["scopes"],
            expires_at=time.time() + 600,  # 10 minutes
            client_id=context["client_id"],
            code_challenge=context["code_challenge"],
            redirect_uri=AnyUrl(context["mcp_redirect_uri"]),
            redirect_uri_provided_explicitly=context["redirect_uri_provided_explicitly"],
            resource=context.get("resource"),
            entra_access_token=entra_access_token,
            entra_refresh_token=entra_refresh_token,
            entra_expires_at=int(time.time()) + expires_in,
        )

        return construct_redirect_uri(
            context["mcp_redirect_uri"],
            code=mcp_code,
            state=context["mcp_state"],
        )

    # ------------------------------------------------------------------
    # Token endpoint
    # ------------------------------------------------------------------

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> EntraAuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        if code.expires_at < time.time():
            del self._auth_codes[authorization_code]
            return None
        return code

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: EntraAuthorizationCode,
    ) -> OAuthToken:
        self._auth_codes.pop(authorization_code.code, None)

        access_token_str = secrets.token_urlsafe(32)
        refresh_token_str = secrets.token_urlsafe(32)
        expires_in = 3600

        self._access_tokens[access_token_str] = EntraAccessToken(
            token=access_token_str,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + expires_in,
            entra_access_token=authorization_code.entra_access_token,
        )
        self._refresh_tokens[refresh_token_str] = EntraRefreshToken(
            token=refresh_token_str,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            entra_refresh_token=authorization_code.entra_refresh_token,
        )

        return OAuthToken(
            access_token=access_token_str,
            token_type="bearer",
            expires_in=expires_in,
            refresh_token=refresh_token_str,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_access_token(self, token: str) -> EntraAccessToken | None:
        access_token = self._access_tokens.get(token)
        if access_token is None:
            return None
        if access_token.expires_at is not None and access_token.expires_at < time.time():
            del self._access_tokens[token]
            return None
        return access_token

    # ------------------------------------------------------------------
    # Refresh token endpoint
    # ------------------------------------------------------------------

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> EntraRefreshToken | None:
        rt = self._refresh_tokens.get(refresh_token)
        if rt is None or rt.client_id != client.client_id:
            return None
        return rt

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: EntraRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token.entra_refresh_token,
                    "scope": _GRAPH_SCOPES,
                },
                timeout=30,
            )
            response.raise_for_status()
            token_data = response.json()

        entra_access_token: str = token_data["access_token"]
        new_entra_refresh = str(
            token_data.get("refresh_token", refresh_token.entra_refresh_token)
        )
        expires_in: int = int(token_data.get("expires_in", 3600))

        self._refresh_tokens.pop(refresh_token.token, None)

        new_access_str = secrets.token_urlsafe(32)
        new_refresh_str = secrets.token_urlsafe(32)
        effective_scopes = scopes or refresh_token.scopes

        self._access_tokens[new_access_str] = EntraAccessToken(
            token=new_access_str,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=int(time.time()) + expires_in,
            entra_access_token=entra_access_token,
        )
        self._refresh_tokens[new_refresh_str] = EntraRefreshToken(
            token=new_refresh_str,
            client_id=client.client_id,
            scopes=effective_scopes,
            entra_refresh_token=new_entra_refresh,
        )

        return OAuthToken(
            access_token=new_access_str,
            token_type="bearer",
            expires_in=expires_in,
            refresh_token=new_refresh_str,
            scope=" ".join(effective_scopes),
        )
