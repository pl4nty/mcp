"""Helper for building a Microsoft Graph client from an MCP access token.

The Graph SDK expects an AsyncTokenCredential. This module provides a thin
wrapper around a pre-obtained Entra ID bearer token so we can reuse it
without going through another OAuth exchange.
"""

from __future__ import annotations

import time

from azure.core.credentials import AccessToken as AzureAccessToken
from msgraph_beta import GraphServiceClient

from mcp.server.auth.middleware.auth_context import get_access_token

from outlook_mcp.auth.entra_provider import EntraAccessToken


class _StaticTokenCredential:
    """AsyncTokenCredential backed by a single pre-obtained bearer token."""

    def __init__(self, token: str, expires_on: int) -> None:
        self._az_token = AzureAccessToken(token=token, expires_on=expires_on)

    async def get_token(
        self,
        *scopes: str,
        **kwargs,
    ) -> AzureAccessToken:
        return self._az_token

    async def close(self) -> None:
        pass


def get_graph_client() -> GraphServiceClient:
    """Return a GraphServiceClient authenticated with the current request's Entra token.

    Must be called within an active MCP request context (i.e. inside a tool handler).

    Raises:
        RuntimeError: if there is no authenticated user in the current context.
    """
    raw = get_access_token()
    if raw is None:
        raise RuntimeError("No authenticated user in the current request context")

    if not isinstance(raw, EntraAccessToken):
        raise RuntimeError(
            "Access token is not an EntraAccessToken — "
            "is the auth provider configured correctly?"
        )

    entra_token: EntraAccessToken = raw
    expires_on = entra_token.expires_at or int(time.time()) + 3600

    credential = _StaticTokenCredential(
        token=entra_token.entra_access_token,
        expires_on=expires_on,
    )
    return GraphServiceClient(credentials=credential)
