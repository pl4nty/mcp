"""Shared utility helpers for the Outlook MCP tools."""

from __future__ import annotations

from typing import Any


def format_email_address(addr: Any) -> dict[str, str] | None:
    """Convert a Graph SDK Recipient / EmailAddress object to a plain dict."""
    if addr is None:
        return None
    ea = getattr(addr, "email_address", addr)
    if ea is None:
        return None
    return {
        "name": ea.name or "",
        "address": ea.address or "",
    }


def format_datetime(dt: Any) -> str | None:
    """Convert a datetime-like object to an ISO 8601 string."""
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
