"""Outlook calendar tools for the MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kiota_abstractions.api_error import APIError

from outlook_mcp.graph_client import get_graph_client
from outlook_mcp.tools.utils import format_email_address

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_calendar_tools(mcp: "FastMCP") -> None:
    """Register all calendar-related MCP tools on *mcp*."""

    @mcp.tool()
    async def list_calendar_events(
        max_results: int = 10,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
    ) -> list[dict[str, Any]]:
        """List upcoming calendar events for the signed-in user.

        Args:
            max_results: Maximum number of events to return (1–50, default 10).
            start_datetime: ISO 8601 start date/time filter, e.g.
                            ``"2025-01-01T00:00:00Z"``. Defaults to now.
            end_datetime: ISO 8601 end date/time filter. Optional.
        """
        max_results = max(1, min(max_results, 50))
        client = get_graph_client()

        try:
            from msgraph_beta.generated.me.events.events_request_builder import (
                EventsRequestBuilder,
            )
            from kiota_abstractions.base_request_configuration import RequestConfiguration

            filter_parts: list[str] = []
            if start_datetime:
                filter_parts.append(f"start/dateTime ge '{start_datetime}'")
            if end_datetime:
                filter_parts.append(f"end/dateTime le '{end_datetime}'")
            odata_filter = " and ".join(filter_parts) if filter_parts else None

            query_params = EventsRequestBuilder.EventsRequestBuilderGetQueryParameters(
                top=max_results,
                select=["id", "subject", "start", "end", "location", "organizer",
                        "isAllDay", "showAs", "bodyPreview"],
                order_by=["start/dateTime ASC"],
                filter=odata_filter,
            )
            config = RequestConfiguration(query_parameters=query_params)
            result = await client.me.events.get(request_configuration=config)
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return _format_events(result.value or [])

    @mcp.tool()
    async def search_calendar_events(
        query: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search calendar events by subject or body text.

        Args:
            query: Free-text search string. The Graph API uses OData $search
                   against event subjects and bodies.
            max_results: Maximum number of events to return (1–50, default 10).
        """
        max_results = max(1, min(max_results, 50))
        client = get_graph_client()

        try:
            from msgraph_beta.generated.me.events.events_request_builder import (
                EventsRequestBuilder,
            )
            from kiota_abstractions.base_request_configuration import RequestConfiguration

            query_params = EventsRequestBuilder.EventsRequestBuilderGetQueryParameters(
                search=f'"{query}"',
                top=max_results,
                select=["id", "subject", "start", "end", "location", "organizer",
                        "isAllDay", "showAs", "bodyPreview"],
            )
            config = RequestConfiguration(query_parameters=query_params)
            result = await client.me.events.get(request_configuration=config)
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return _format_events(result.value or [])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _format_events(events: list) -> list[dict[str, Any]]:
    return [_format_event(e) for e in events]


def _format_event(event) -> dict[str, Any]:
    return {
        "id": event.id,
        "subject": event.subject,
        "start": _format_date_time_tz(event.start),
        "end": _format_date_time_tz(event.end),
        "location": event.location.display_name if event.location else None,
        "organizer": format_email_address(event.organizer),
        "isAllDay": event.is_all_day,
        "showAs": str(event.show_as.value) if event.show_as else None,
        "bodyPreview": event.body_preview,
    }


def _format_date_time_tz(dt_tz) -> dict[str, str] | None:
    if dt_tz is None:
        return None
    return {
        "dateTime": dt_tz.date_time or "",
        "timeZone": dt_tz.time_zone or "UTC",
    }
