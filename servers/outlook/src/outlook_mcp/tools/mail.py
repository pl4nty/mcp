"""Outlook email tools."""

from __future__ import annotations

import re
from typing import Any

from kiota_abstractions.api_error import APIError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph_beta import GraphServiceClient
from msgraph_beta.generated.users.item.mail_folders.item.messages.messages_request_builder import (
    MessagesRequestBuilder as FolderMessagesRequestBuilder,
)
from msgraph_beta.generated.users.item.messages.messages_request_builder import (
    MessagesRequestBuilder,
)

from mcp.server.fastmcp import FastMCP

_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _validate_datetime(value: str, param_name: str) -> None:
    if not _ISO8601_RE.match(value):
        raise ValueError(
            f"{param_name} must be an ISO 8601 datetime string "
            "(e.g. '2025-01-01T00:00:00Z'), got: {value!r}"
        )


def register_mail_tools(mcp: FastMCP, client: GraphServiceClient, user_id: str) -> None:
    """Register all email-related MCP tools on *mcp*."""

    user = client.users.by_user_id(user_id)

    @mcp.tool()
    async def search_emails(
        query: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search emails in the user's Outlook mailbox.

        Args:
            query: Free-text search query (OData $search syntax),
                   e.g. "subject:invoice" or "from:boss@example.com".
            max_results: Maximum number of emails to return (1–50, default 10).
        """
        max_results = max(1, min(max_results, 50))
        try:
            result = await user.messages.get(
                request_configuration=RequestConfiguration(
                    query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                        search=f'"{query}"',
                        top=max_results,
                        orderby=["receivedDateTime DESC"],
                    )
                )
            )
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return [
            {
                "id": m.id,
                "subject": m.subject,
                "from": m.from_.email_address.address if m.from_ and m.from_.email_address else None,
                "receivedDateTime": m.received_date_time,
                "isRead": m.is_read,
                "bodyPreview": m.body_preview,
            }
            for m in (result.value or [])
        ]

    @mcp.tool()
    async def list_emails(
        folder: str = "inbox",
        max_results: int = 10,
        only_unread: bool = False,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
    ) -> list[dict[str, Any]]:
        """List emails from a mailbox folder.

        Args:
            folder: Folder name: inbox, drafts, sentitems, deleteditems,
                    or junkemail (default inbox).
            max_results: Maximum number of emails to return (1–50, default 10).
            only_unread: If True, return only unread messages.
            start_datetime: ISO 8601 lower bound on receivedDateTime,
                            e.g. "2025-01-01T00:00:00Z".
            end_datetime: ISO 8601 upper bound on receivedDateTime.
        """
        max_results = max(1, min(max_results, 50))
        filter_parts: list[str] = []
        if only_unread:
            filter_parts.append("isRead eq false")
        if start_datetime:
            _validate_datetime(start_datetime, "start_datetime")
            filter_parts.append(f"receivedDateTime ge {start_datetime}")
        if end_datetime:
            _validate_datetime(end_datetime, "end_datetime")
            filter_parts.append(f"receivedDateTime le {end_datetime}")

        try:
            result = await user.mail_folders.by_mail_folder_id(folder).messages.get(
                request_configuration=RequestConfiguration(
                    query_parameters=FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                        top=max_results,
                        orderby=["receivedDateTime DESC"],
                        filter=" and ".join(filter_parts) if filter_parts else None,
                    )
                )
            )
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return [
            {
                "id": m.id,
                "subject": m.subject,
                "from": m.from_.email_address.address if m.from_ and m.from_.email_address else None,
                "receivedDateTime": m.received_date_time,
                "isRead": m.is_read,
                "bodyPreview": m.body_preview,
            }
            for m in (result.value or [])
        ]

    @mcp.tool()
    async def read_email(email_id: str) -> dict[str, Any]:
        """Read the full content of a specific email.

        Args:
            email_id: The unique message ID returned by search_emails or list_emails.
        """
        try:
            message = await user.messages.by_message_id(email_id).get()
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        if message is None:
            raise RuntimeError(f"Email not found: {email_id!r}")

        return {
            "id": message.id,
            "subject": message.subject,
            "from": message.from_.email_address.address if message.from_ and message.from_.email_address else None,
            "to": [r.email_address.address for r in (message.to_recipients or []) if r.email_address],
            "cc": [r.email_address.address for r in (message.cc_recipients or []) if r.email_address],
            "receivedDateTime": message.received_date_time,
            "sentDateTime": message.sent_date_time,
            "isRead": message.is_read,
            "hasAttachments": message.has_attachments,
            "importance": message.importance,
            "bodyPreview": message.body_preview,
            "body": message.body.content if message.body else None,
            "bodyContentType": message.body.content_type if message.body else None,
        }
