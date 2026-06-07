"""FlowSavvy tools — task and event management."""

import os
from typing import Optional

import httpx

from tools.runtime import mcp

FLOWSAVVY_COOKIE = os.environ.get("FLOWSAVVY_COOKIE", "")
_BASE = "https://my.flowsavvy.app/api"


def _client() -> httpx.AsyncClient:
    if not FLOWSAVVY_COOKIE:
        raise RuntimeError("FLOWSAVVY_COOKIE environment variable is not set")
    return httpx.AsyncClient(
        cookies={"Identity.Cookie": FLOWSAVVY_COOKIE},
    )


def _extract_item(item: dict) -> dict:
    source = item.get("Item") if isinstance(item.get("Item"), dict) else item
    entry = {
        k: source[k]
        for k in (
            "id", "Title", "ItemType", "DueDateTime", "StartDateTime",
            "EndDateTime", "Notes", "priority", "FixedTime", "AllDay",
            "taskListId", "IsCompleted",
        )
        if k in source
    }
    if "calendarId" in source:
        entry["calendarId"] = source["calendarId"]
    elif "CalendarID" in source:
        entry["calendarId"] = source["CalendarID"]
    if "id" not in entry:
        if "id" in item:
            entry["id"] = item["id"]
        elif "ItemID" in item:
            entry["id"] = item["ItemID"]
    return entry


def _parse_schedule_response(data) -> list[dict]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        schedule = data.get("scheduleResponse", data)
        if isinstance(schedule, dict):
            schedule_items = schedule.get("scheduleItems", [])
            all_day_events = schedule.get("allDayEvents", [])
            if isinstance(schedule_items, list) or isinstance(all_day_events, list):
                items = []
                if isinstance(schedule_items, list):
                    items.extend(schedule_items)
                if isinstance(all_day_events, list):
                    items.extend(all_day_events)
            else:
                items = schedule.get("items", schedule.get("Items", [schedule]))
        else:
            items = [schedule]
    else:
        items = [data]

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = _extract_item(item)
        if entry:
            results.append(entry)
    return results


def _build_item_form(
    title: str,
    item_type: str,
    due_date_time: str,
    start_date_time: str,
    end_date_time: str,
    notes: str = "<p></p>",
    priority: int = 1,
    task_list_id: int = 0,
    calendar_id: int = 0,
    time_profile_id: int = 0,
    fixed_time: bool = False,
    all_day: bool = False,
    item_id: int = 0,
    dont_start_until: str = "0001-01-01T00:00",
    location: str = "",
    busy: bool = True,
) -> dict:
    return {
        "id": str(item_id),
        "InstanceID": "0",
        "Notes": notes,
        "DueDateTime": due_date_time,
        "StartDateTime": start_date_time,
        "EndDateTime": end_date_time,
        "DontStartUntil": dont_start_until,
        "TimeZone": "Floating",
        "IsAutoIgnored": "false",
        "Title": title,
        "ItemType": item_type,
        "ProgressHours": "0",
        "ProgressMinutes": "0",
        "minLengthTotalMinutes": "60",
        "BufferTimeBeforeHours": "0",
        "BufferTimeBeforeMinutes": "0",
        "BufferTimeAfterHours": "0",
        "BufferTimeAfterMinutes": "0",
        "Busy": str(busy).lower(),
        "FixedTime": str(fixed_time).lower(),
        "AllDay": str(all_day).lower(),
        "RepeatType": "Never",
        "Interval": "1",
        "Sunday": "false",
        "Monday": "false",
        "Tuesday": "false",
        "Wednesday": "false",
        "Thursday": "false",
        "Friday": "false",
        "Saturday": "false",
        "MonthlyType": "Each...",
        "Dates": "",
        "MonthOrdinal": "0",
        "WeekDay": "0",
        "EndRepeatType": "Never",
        "EndRepeatDate": "0001-01-01T00:00",
        "NumOccurrences": "1",
        "priority": str(priority),
        "customColor": "",
        "taskListId": str(task_list_id),
        "calendarId": str(calendar_id),
        "timeProfileId": str(time_profile_id),
        "Location": location,
    }


@mcp.tool()
async def get_flowsavvy_schedule(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Get tasks and events from FlowSavvy schedule.

    Args:
        start_date: Optional start date filter in ISO format (e.g. "2026-06-01").
        end_date: Optional end date filter in ISO format (e.g. "2026-06-30").
    """
    params = {}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date

    async with _client() as client:
        resp = await client.get(f"{_BASE}/Schedule/GetSchedule", params=params)
        resp.raise_for_status()
        data = resp.json()

    return _parse_schedule_response(data)


@mcp.tool()
async def list_flowsavvy_items(
    item_type: Optional[str] = None,
) -> list[dict]:
    """List items (tasks and/or events) from FlowSavvy.

    Args:
        item_type: Optional filter — "task" or "event". Omit for all items.
    """
    params = {}
    if item_type:
        params["itemType"] = item_type

    async with _client() as client:
        resp = await client.get(f"{_BASE}/Item/GetItems", params=params)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, list):
        return [_extract_item(i) for i in data if isinstance(i, dict)]
    return _parse_schedule_response(data)


@mcp.tool()
async def get_flowsavvy_item(item_id: int) -> dict:
    """Get details of a single FlowSavvy item by ID.

    Args:
        item_id: The numeric ID of the task or event.
    """
    async with _client() as client:
        resp = await client.get(f"{_BASE}/Item/GetItem", params={"id": item_id})
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, dict):
        return _extract_item(data)
    return data


@mcp.tool()
async def list_flowsavvy_calendars() -> list[dict]:
    """List all calendars available in FlowSavvy."""
    async with _client() as client:
        resp = await client.get(f"{_BASE}/Calendar/GetCalendars")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def list_flowsavvy_lists() -> list[dict]:
    """List all task lists in FlowSavvy."""
    async with _client() as client:
        resp = await client.get(f"{_BASE}/TaskList/GetLists")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def list_flowsavvy_scheduling_hours() -> list[dict]:
    """List all scheduling hour profiles (time profiles) in FlowSavvy."""
    async with _client() as client:
        resp = await client.get(f"{_BASE}/TimeProfile/GetTimeProfiles")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def create_flowsavvy_task(
    title: str,
    due_date_time: str,
    start_date_time: str,
    end_date_time: str,
    notes: str = "<p></p>",
    priority: int = 1,
    task_list_id: int = 0,
    calendar_id: int = 0,
    time_profile_id: int = 0,
    fixed_time: bool = False,
    all_day: bool = False,
) -> dict:
    """Create a new task in FlowSavvy.

    Args:
        title: Task title.
        due_date_time: Due date/time in ISO format (e.g. "2026-05-10T23:59").
        start_date_time: Scheduled start date/time (e.g. "2026-05-10T14:00").
        end_date_time: Scheduled end date/time (e.g. "2026-05-10T15:00").
        notes: HTML notes for the task.
        priority: Priority level (1 = default).
        task_list_id: FlowSavvy task list ID.
        calendar_id: FlowSavvy calendar ID.
        time_profile_id: FlowSavvy time profile ID.
        fixed_time: Whether the task is fixed to its scheduled time.
        all_day: Whether this is an all-day task.
    """
    form_data = _build_item_form(
        title=title,
        item_type="task",
        due_date_time=due_date_time,
        start_date_time=start_date_time,
        end_date_time=end_date_time,
        notes=notes,
        priority=priority,
        task_list_id=task_list_id,
        calendar_id=calendar_id,
        time_profile_id=time_profile_id,
        fixed_time=fixed_time,
        all_day=all_day,
    )

    async with _client() as client:
        resp = await client.post(f"{_BASE}/Item/Create", data=form_data)
        resp.raise_for_status()
        data = resp.json()

    return _extract_item(data) if isinstance(data, dict) else data


@mcp.tool()
async def create_flowsavvy_event(
    title: str,
    start_date_time: str,
    end_date_time: str,
    notes: str = "<p></p>",
    calendar_id: int = 0,
    fixed_time: bool = True,
    all_day: bool = False,
    location: str = "",
    busy: bool = True,
) -> dict:
    """Create a new calendar event in FlowSavvy.

    Args:
        title: Event title.
        start_date_time: Event start date/time in ISO format (e.g. "2026-06-10T14:00").
        end_date_time: Event end date/time in ISO format (e.g. "2026-06-10T15:00").
        notes: HTML notes for the event.
        calendar_id: FlowSavvy calendar ID.
        fixed_time: Whether the event is at a fixed time (default True for events).
        all_day: Whether this is an all-day event.
        location: Optional location string.
        busy: Whether to mark the time as busy.
    """
    form_data = _build_item_form(
        title=title,
        item_type="event",
        due_date_time=end_date_time,
        start_date_time=start_date_time,
        end_date_time=end_date_time,
        notes=notes,
        calendar_id=calendar_id,
        fixed_time=fixed_time,
        all_day=all_day,
        location=location,
        busy=busy,
    )

    async with _client() as client:
        resp = await client.post(f"{_BASE}/Item/Create", data=form_data)
        resp.raise_for_status()
        data = resp.json()

    return _extract_item(data) if isinstance(data, dict) else data


@mcp.tool()
async def update_flowsavvy_task(
    item_id: int,
    title: str,
    due_date_time: str,
    start_date_time: str,
    end_date_time: str,
    notes: str = "<p></p>",
    priority: int = 1,
    task_list_id: int = 0,
    calendar_id: int = 0,
    time_profile_id: int = 0,
    fixed_time: bool = False,
    all_day: bool = False,
) -> dict:
    """Update an existing task in FlowSavvy.

    Args:
        item_id: The numeric ID of the task to update.
        title: Task title.
        due_date_time: Due date/time in ISO format (e.g. "2026-05-10T23:59").
        start_date_time: Scheduled start date/time (e.g. "2026-05-10T14:00").
        end_date_time: Scheduled end date/time (e.g. "2026-05-10T15:00").
        notes: HTML notes for the task.
        priority: Priority level (1 = default).
        task_list_id: FlowSavvy task list ID.
        calendar_id: FlowSavvy calendar ID.
        time_profile_id: FlowSavvy time profile ID.
        fixed_time: Whether the task is fixed to its scheduled time.
        all_day: Whether this is an all-day task.
    """
    form_data = _build_item_form(
        title=title,
        item_type="task",
        due_date_time=due_date_time,
        start_date_time=start_date_time,
        end_date_time=end_date_time,
        notes=notes,
        priority=priority,
        task_list_id=task_list_id,
        calendar_id=calendar_id,
        time_profile_id=time_profile_id,
        fixed_time=fixed_time,
        all_day=all_day,
        item_id=item_id,
    )

    async with _client() as client:
        resp = await client.post(f"{_BASE}/Item/Update", data=form_data)
        resp.raise_for_status()
        data = resp.json()

    return _extract_item(data) if isinstance(data, dict) else data


@mcp.tool()
async def update_flowsavvy_event(
    item_id: int,
    title: str,
    start_date_time: str,
    end_date_time: str,
    notes: str = "<p></p>",
    calendar_id: int = 0,
    fixed_time: bool = True,
    all_day: bool = False,
    location: str = "",
    busy: bool = True,
) -> dict:
    """Update an existing event in FlowSavvy.

    Args:
        item_id: The numeric ID of the event to update.
        title: Event title.
        start_date_time: Event start date/time in ISO format (e.g. "2026-06-10T14:00").
        end_date_time: Event end date/time in ISO format (e.g. "2026-06-10T15:00").
        notes: HTML notes for the event.
        calendar_id: FlowSavvy calendar ID.
        fixed_time: Whether the event is at a fixed time.
        all_day: Whether this is an all-day event.
        location: Optional location string.
        busy: Whether to mark the time as busy.
    """
    form_data = _build_item_form(
        title=title,
        item_type="event",
        due_date_time=end_date_time,
        start_date_time=start_date_time,
        end_date_time=end_date_time,
        notes=notes,
        calendar_id=calendar_id,
        fixed_time=fixed_time,
        all_day=all_day,
        location=location,
        busy=busy,
        item_id=item_id,
    )

    async with _client() as client:
        resp = await client.post(f"{_BASE}/Item/Update", data=form_data)
        resp.raise_for_status()
        data = resp.json()

    return _extract_item(data) if isinstance(data, dict) else data


@mcp.tool()
async def complete_flowsavvy_task(item_id: int) -> dict:
    """Mark a FlowSavvy task as complete.

    Args:
        item_id: The numeric ID of the task to complete.
    """
    async with _client() as client:
        resp = await client.post(
            f"{_BASE}/Item/Complete",
            data={"id": str(item_id)},
        )
        resp.raise_for_status()
        data = resp.json()

    return _extract_item(data) if isinstance(data, dict) else {"id": item_id, "status": "completed"}


@mcp.tool()
async def uncomplete_flowsavvy_task(item_id: int) -> dict:
    """Mark a FlowSavvy task as incomplete (reopen it).

    Args:
        item_id: The numeric ID of the task to reopen.
    """
    async with _client() as client:
        resp = await client.post(
            f"{_BASE}/Item/Uncomplete",
            data={"id": str(item_id)},
        )
        resp.raise_for_status()
        data = resp.json()

    return _extract_item(data) if isinstance(data, dict) else {"id": item_id, "status": "incomplete"}


@mcp.tool()
async def delete_flowsavvy_item(item_id: int) -> dict:
    """Delete a task or event from FlowSavvy.

    Args:
        item_id: The numeric ID of the item to delete.
    """
    async with _client() as client:
        resp = await client.post(
            f"{_BASE}/Item/Delete",
            data={"id": str(item_id)},
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"id": item_id, "deleted": True}


@mcp.tool()
async def recalculate_flowsavvy() -> dict:
    """Trigger FlowSavvy to recalculate and reschedule all tasks."""
    async with _client() as client:
        resp = await client.post(f"{_BASE}/Schedule/Recalculate")
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"status": "recalculated"}
