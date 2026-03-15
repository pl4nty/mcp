"""Outlook email tools for the MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kiota_abstractions.api_error import APIError

from outlook_mcp.graph_client import get_graph_client
from outlook_mcp.tools.utils import format_datetime, format_email_address

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_mail_tools(mcp: "FastMCP") -> None:
    """Register all email-related MCP tools on *mcp*."""

    @mcp.tool()
    async def search_emails(
        query: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search emails in the signed-in user's Outlook mailbox.

        Args:
            query: Free-text search query. Supports OData $search syntax,
                   e.g. ``"subject:invoice"`` or ``"from:boss@example.com"``.
            max_results: Maximum number of emails to return (1–50, default 10).
        """
        max_results = max(1, min(max_results, 50))
        client = get_graph_client()

        try:
            from msgraph_beta.generated.me.messages.messages_request_builder import (
                MessagesRequestBuilder,
            )
            from kiota_abstractions.base_request_configuration import RequestConfiguration

            query_params = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                search=f'"{query}"',
                top=max_results,
                select=["id", "subject", "from", "receivedDateTime", "isRead", "bodyPreview"],
                order_by=["receivedDateTime DESC"],
            )
            config = RequestConfiguration(query_parameters=query_params)
            result = await client.me.messages.get(request_configuration=config)
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return _format_messages(result.value or [])

    @mcp.tool()
    async def list_emails(
        folder: str = "inbox",
        max_results: int = 10,
        only_unread: bool = False,
    ) -> list[dict[str, Any]]:
        """List emails from a mailbox folder.

        Args:
            folder: Folder name: ``inbox``, ``drafts``, ``sentitems``,
                    ``deleteditems``, or ``junkemail`` (default ``inbox``).
            max_results: Maximum number of emails to return (1–50, default 10).
            only_unread: If True, return only unread messages.
        """
        max_results = max(1, min(max_results, 50))
        client = get_graph_client()

        try:
            from msgraph_beta.generated.me.mail_folders.item.messages.messages_request_builder import (
                MessagesRequestBuilder,
            )
            from kiota_abstractions.base_request_configuration import RequestConfiguration

            query_params = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                top=max_results,
                select=["id", "subject", "from", "receivedDateTime", "isRead", "bodyPreview"],
                order_by=["receivedDateTime DESC"],
                filter="isRead eq false" if only_unread else None,
            )
            config = RequestConfiguration(query_parameters=query_params)
            result = await client.me.mail_folders.by_mail_folder_id(folder).messages.get(
                request_configuration=config
            )
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return _format_messages(result.value or [])

    @mcp.tool()
    async def read_email(email_id: str) -> dict[str, Any]:
        """Read the full content of a specific email.

        Args:
            email_id: The unique message ID returned by ``search_emails`` or
                      ``list_emails``.
        """
        client = get_graph_client()

        try:
            from msgraph_beta.generated.me.messages.item.message_item_request_builder import (
                MessageItemRequestBuilder,
            )
            from kiota_abstractions.base_request_configuration import RequestConfiguration

            query_params = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters(
                select=["id", "subject", "from", "toRecipients", "ccRecipients",
                        "receivedDateTime", "sentDateTime", "isRead", "body", "bodyPreview",
                        "hasAttachments", "importance"],
            )
            config = RequestConfiguration(query_parameters=query_params)
            message = await client.me.messages.by_message_id(email_id).get(
                request_configuration=config
            )
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        if message is None:
            raise RuntimeError(f"Email not found: {email_id!r}")

        result: dict[str, Any] = {
            "id": message.id,
            "subject": message.subject,
            "from": format_email_address(message.from_),
            "to": [format_email_address(r) for r in (message.to_recipients or [])],
            "cc": [format_email_address(r) for r in (message.cc_recipients or [])],
            "received": format_datetime(message.received_date_time),
            "sent": format_datetime(message.sent_date_time),
            "isRead": message.is_read,
            "hasAttachments": message.has_attachments,
            "importance": str(message.importance.value) if message.importance else None,
            "bodyPreview": message.body_preview,
            "body": message.body.content if message.body else None,
            "bodyContentType": message.body.content_type.value if (message.body and message.body.content_type) else None,
        }
        return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _format_messages(messages: list) -> list[dict[str, Any]]:
    return [
        {
            "id": m.id,
            "subject": m.subject,
            "from": format_email_address(m.from_),
            "receivedDateTime": format_datetime(m.received_date_time),
            "isRead": m.is_read,
            "bodyPreview": m.body_preview,
        }
        for m in messages
    ]
