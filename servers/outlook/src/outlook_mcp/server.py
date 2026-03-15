"""Outlook MCP server.

Starts a FastMCP server with Streamable HTTP transport and a simple OAuth 2.1
Authorization Server that accepts pre-configured client credentials from Claude.
Microsoft Graph access uses DefaultAzureCredential.

Environment variables
---------------------
MCP_CLIENT_ID      : OAuth client ID Claude uses to authenticate with this server
MCP_CLIENT_SECRET  : OAuth client secret Claude uses to authenticate with this server
GRAPH_USER         : Microsoft 365 user ID or UPN whose data to access
                     (e.g. user@example.com)
SERVER_URL         : Public URL of this server (default: http://localhost:8000)
HOST               : Bind host (default: 0.0.0.0)
PORT               : Bind port (default: 8000)

Graph API authentication uses DefaultAzureCredential. Configure one of:
  - AZURE_CLIENT_ID + AZURE_TENANT_ID + AZURE_CLIENT_SECRET (service principal)
  - Workload identity / Managed Identity (when running in Azure)
"""

import logging
import os
import secrets
import time

from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from msgraph_beta import GraphServiceClient
from pydantic import AnyHttpUrl, AnyUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from outlook_mcp.tools.calendar import register_calendar_tools
from outlook_mcp.tools.mail import register_mail_tools

load_dotenv()

logger = logging.getLogger(__name__)

_MCP_SCOPES = ["mail.read", "calendar.read"]


class _StaticOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """OAuth AS with one pre-registered client. No dynamic client registration.

    Issues authorization codes immediately; Graph access is handled separately
    via DefaultAzureCredential.
    """

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=[AnyUrl("https://claude.ai/api/mcp/auth_callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._client if client_id == self._client.client_id else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise RegistrationError(
            "invalid_client_metadata", "Dynamic client registration is disabled"
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or _MCP_SCOPES,
            expires_at=time.time() + 600,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return construct_redirect_uri(
            str(params.redirect_uri), code=code, state=params.state
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        if code.expires_at < time.time():
            del self._auth_codes[authorization_code]
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
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
            return None
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
        self._refresh_tokens.pop(refresh_token.token, None)
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
        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
            refresh_token=new_refresh,
            scope=" ".join(effective_scopes),
        )


_mcp_client_id = os.environ.get("MCP_CLIENT_ID", "")
_mcp_client_secret = os.environ.get("MCP_CLIENT_SECRET", "")
_server_url = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
_host = os.environ.get("HOST", "0.0.0.0")
_port = int(os.environ.get("PORT", "8000"))
_graph_user = os.environ.get("GRAPH_USER", "")

if not all([_mcp_client_id, _mcp_client_secret]):
    logger.warning("MCP_CLIENT_ID and MCP_CLIENT_SECRET must be set.")
if not _graph_user:
    logger.warning("GRAPH_USER must be set to a Microsoft 365 user ID or UPN.")

_graph_client = GraphServiceClient(credentials=DefaultAzureCredential())

provider = _StaticOAuthProvider(
    client_id=_mcp_client_id,
    client_secret=_mcp_client_secret,
)

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
            enabled=False,
            valid_scopes=_MCP_SCOPES,
            default_scopes=_MCP_SCOPES,
        ),
        required_scopes=_MCP_SCOPES,
    ),
    host=_host,
    port=_port,
)

register_mail_tools(mcp, _graph_client, _graph_user)
register_calendar_tools(mcp, _graph_client, _graph_user)


def main() -> None:
    """Run the Outlook MCP server with Streamable HTTP transport."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
