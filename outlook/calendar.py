"""Outlook calendar tools."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from kiota_abstractions.api_error import APIError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.serialization import Parsable
from kiota_serialization_json.json_serialization_writer_factory import (
    JsonSerializationWriterFactory,
)
from msgraph_beta import GraphServiceClient
from msgraph_beta.generated.users.item.events.events_request_builder import (
    EventsRequestBuilder,
)

from mcp.server.fastmcp import FastMCP

_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

_KIOTA_FACTORY = JsonSerializationWriterFactory()


def _to_dict(obj: Parsable) -> dict:
    """Serialize a Kiota Parsable object to a plain dict using Kiota's own serialization."""
    writer = _KIOTA_FACTORY.get_serialization_writer("application/json")
    obj.serialize(writer)
    return json.loads(writer.get_serialized_content())


def _validate_datetime(value: str, param_name: str) -> None:
    if not _ISO8601_RE.match(value):
        raise ValueError(
            f"{param_name} must be an ISO 8601 datetime string "
            f"(e.g. '2025-01-01T00:00:00Z'), got: {value!r}"
        )


def register_calendar_tools(
    mcp: FastMCP, get_client: Callable[[], GraphServiceClient]
) -> None:
    """Register all calendar-related MCP tools on *mcp*."""

    @mcp.tool()
    async def list_calendar_events(
        max_results: int = 10,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
    ) -> list[dict]:
        """List upcoming calendar events.

        Args:
            max_results: Maximum number of events to return (1–50, default 10).
            start_datetime: ISO 8601 start date/time filter,
                            e.g. "2025-01-01T00:00:00Z".
            end_datetime: ISO 8601 end date/time filter.
        """
        max_results = max(1, min(max_results, 50))
        filter_parts: list[str] = []
        if start_datetime:
            _validate_datetime(start_datetime, "start_datetime")
            filter_parts.append(f"start/dateTime ge '{start_datetime}'")
        if end_datetime:
            _validate_datetime(end_datetime, "end_datetime")
            filter_parts.append(f"end/dateTime le '{end_datetime}'")

        me = get_client().me
        try:
            result = await me.events.get(
                request_configuration=RequestConfiguration(
                    query_parameters=EventsRequestBuilder.EventsRequestBuilderGetQueryParameters(
                        top=max_results,
                        orderby=["start/dateTime ASC"],
                        filter=" and ".join(filter_parts) if filter_parts else None,
                    )
                )
            )
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return [_to_dict(e) for e in (result.value or [])]

    @mcp.tool()
    async def search_calendar_events(
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """Search calendar events by subject or body text.

        Args:
            query: Free-text search string.
            max_results: Maximum number of events to return (1–50, default 10).
        """
        max_results = max(1, min(max_results, 50))

        me = get_client().me
        try:
            result = await me.events.get(
                request_configuration=RequestConfiguration(
                    query_parameters=EventsRequestBuilder.EventsRequestBuilderGetQueryParameters(
                        search=f'"{query}"',
                        top=max_results,
                    )
                )
            )
        except APIError as exc:
            raise RuntimeError(f"Graph API error: {exc.message}") from exc

        return [_to_dict(e) for e in (result.value or [])]

