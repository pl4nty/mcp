"""FlowSavvy tools — task management."""

import os

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


@mcp.tool()
async def list_flowsavvy_tasks() -> list[dict]:
    """List all tasks and events from FlowSavvy schedule."""
    async with _client() as client:
        resp = await client.get(f"{_BASE}/Schedule/GetSchedule")
        resp.raise_for_status()
        data = resp.json()

    items = data if isinstance(data, list) else data.get("items", data.get("Items", [data]))
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = {
            k: item[k]
            for k in (
                "id", "Title", "ItemType", "DueDateTime", "StartDateTime",
                "EndDateTime", "Notes", "priority", "FixedTime", "AllDay",
                "taskListId", "calendarId",
            )
            if k in item
        }
        if entry:
            results.append(entry)
    return results


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
    form_data = {
        "id": "0",
        "InstanceID": "0",
        "Notes": notes,
        "DueDateTime": due_date_time,
        "StartDateTime": start_date_time,
        "EndDateTime": end_date_time,
        "DontStartUntil": "0001-01-01T00:00",
        "TimeZone": "Floating",
        "IsAutoIgnored": "false",
        "Title": title,
        "ItemType": "task",
        "ProgressHours": "0",
        "ProgressMinutes": "0",
        "minLengthTotalMinutes": "60",
        "BufferTimeBeforeHours": "0",
        "BufferTimeBeforeMinutes": "0",
        "BufferTimeAfterHours": "0",
        "BufferTimeAfterMinutes": "0",
        "Busy": "true",
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
        "EndRepeatDate": "2026-05-17T00:00",
        "NumOccurrences": "1",
        "priority": str(priority),
        "customColor": "",
        "taskListId": str(task_list_id),
        "calendarId": str(calendar_id),
        "timeProfileId": str(time_profile_id),
        "Location": "",
    }

    async with _client() as client:
        resp = await client.post(f"{_BASE}/Item/Create", data=form_data)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, dict):
        return {
            k: data[k]
            for k in (
                "id", "Title", "ItemType", "DueDateTime", "StartDateTime",
                "EndDateTime", "Notes", "priority", "FixedTime", "AllDay",
                "taskListId", "calendarId",
            )
            if k in data
        }
    return data
