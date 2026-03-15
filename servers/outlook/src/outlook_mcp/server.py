"""Outlook MCP server entry point.

Starts a FastMCP server with:
- Streamable HTTP transport (for Claude custom connectors)
- OAuth 2.1 Authorization Server that proxies to Microsoft Entra ID
- Tools for searching and reading Outlook emails and calendar events

Environment variables
---------------------
ENTRA_TENANT_ID    : Entra ID tenant ID (use "common" for personal/outlook.com accounts)
ENTRA_CLIENT_ID    : App registration client ID
ENTRA_CLIENT_SECRET: App registration client secret
SERVER_URL         : Public URL of this server (default: http://localhost:8000)
HOST               : Bind host (default: 0.0.0.0 for Docker, 127.0.0.1 otherwise)
PORT               : Bind port (default: 8000)
"""

import logging
import os

from dotenv import load_dotenv
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP

from outlook_mcp.auth.entra_provider import MCP_SCOPES, EntraOAuthProvider
from outlook_mcp.tools.calendar import register_calendar_tools
from outlook_mcp.tools.mail import register_mail_tools

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
_client_id = os.environ.get("ENTRA_CLIENT_ID", "")
_client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "")
_server_url = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
_host = os.environ.get("HOST", "0.0.0.0")
_port = int(os.environ.get("PORT", "8000"))

if not all([_tenant_id, _client_id, _client_secret]):
    logger.warning(
        "ENTRA_TENANT_ID, ENTRA_CLIENT_ID, and ENTRA_CLIENT_SECRET must be set. "
        "Authentication will fail until these are configured."
    )

# ---------------------------------------------------------------------------
# Auth provider
# ---------------------------------------------------------------------------

provider = EntraOAuthProvider(
    tenant_id=_tenant_id,
    client_id=_client_id,
    client_secret=_client_secret,
    server_url=_server_url,
)

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

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
            valid_scopes=MCP_SCOPES,
            default_scopes=MCP_SCOPES,
        ),
        required_scopes=MCP_SCOPES,
    ),
    host=_host,
    port=_port,
)

# ---------------------------------------------------------------------------
# OAuth callback route (Entra ID redirects here after user login)
# ---------------------------------------------------------------------------


@mcp.custom_route("/oauth/callback", methods=["GET"])
async def oauth_callback(request: Request) -> Response:
    """Handle the Microsoft Entra ID authorization code callback.

    Entra ID redirects the user here after successful login. This handler
    exchanges the Entra authorization code for tokens, then redirects the
    user back to Claude's OAuth callback with an MCP authorization code.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    error_description = request.query_params.get("error_description", "")

    if error:
        logger.error("Entra ID returned an error: %s — %s", error, error_description)
        return Response(
            f"Authentication error: {error}. {error_description}",
            status_code=400,
        )

    if not code or not state:
        return Response(
            "Bad request: missing 'code' or 'state' parameter.",
            status_code=400,
        )

    try:
        redirect_url = await provider.handle_entra_callback(code, state)
    except Exception as exc:
        logger.exception("Error handling Entra ID callback")
        return Response(f"Internal error: {exc}", status_code=500)

    return RedirectResponse(redirect_url, status_code=302)


# ---------------------------------------------------------------------------
# Register tools
# ---------------------------------------------------------------------------

register_mail_tools(mcp)
register_calendar_tools(mcp)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the Outlook MCP server with Streamable HTTP transport."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
