import json
import random
from datetime import datetime

from mobile_world.runtime.utils.helpers import execute_adb

# make sure the emulator is rootable and adb root
db_path = "/data/user/0/org.fossify.calendar/databases/events.db"

# Column order for the fossify-calendar `events` INSERT. Single source of truth for
# single-row inserts and any batch seeder built on build_event_values_row.
EVENTS_INSERT_COLUMNS = (
    "start_ts, end_ts, title, location, description, "
    "reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, "
    "reminder_1_type, reminder_2_type, reminder_3_type, "
    "repeat_interval, repeat_rule, repeat_limit, "
    "repetition_exceptions, attendees, import_id, time_zone, "
    "flags, event_type, parent_id, last_updated, source, "
    "availability, access_level, color, type, status"
)


def _sql_escape(value) -> str:
    return str(value).replace("'", "''")


def build_event_values_row(
    *,
    start_ts: int,
    end_ts: int,
    title: str,
    location: str = "",
    description: str = "",
    reminder_1_minutes: int = -1,
    reminder_2_minutes: int = -1,
    reminder_3_minutes: int = -1,
    reminder_1_type: int = 0,
    reminder_2_type: int = 0,
    reminder_3_type: int = 0,
    repeat_interval: int = 0,
    repeat_rule: int = 0,
    repeat_limit: int = 0,
    repetition_exceptions: str = "[]",
    attendees: str = "[]",
    time_zone: str = "UTC",
    flags: int = 0,
    event_type: int = 1,
    parent_id: int = 0,
    source: str = "manual",
    availability: int = 0,
    access_level: int = 0,
    color: int = 0,
    type_field: int = 0,
    status: int = 1,
    last_updated: int | None = None,
) -> str:
    """Build one ``( … )`` VALUES tuple for the events INSERT, in EVENTS_INSERT_COLUMNS
    order. CalendarEvent-agnostic so the single-row and batch insert paths share it.

    NOTE: text values must not contain a double-quote character — that would break the
    outer ``adb shell "…"`` quoting; ``_sql_escape`` only doubles single quotes (SQLite
    standard). ``import_id`` is generated here (4-digit; may collide within a batch but is
    ignored by verification). ``last_updated`` defaults to "now" in ms; pass ``0`` for a
    deterministic value.
    """
    import_id = f"mock{random.randint(1000, 9999)}"
    if last_updated is None:
        last_updated = int(datetime.now().timestamp() * 1000)
    return (
        f"({start_ts}, {end_ts}, '{_sql_escape(title)}', "
        f"'{_sql_escape(location)}', '{_sql_escape(description)}', "
        f"{reminder_1_minutes}, {reminder_2_minutes}, {reminder_3_minutes}, "
        f"{reminder_1_type}, {reminder_2_type}, {reminder_3_type}, "
        f"{repeat_interval}, {repeat_rule}, {repeat_limit}, "
        f"'{_sql_escape(repetition_exceptions)}', '{_sql_escape(attendees)}', "
        f"'{import_id}', '{_sql_escape(time_zone)}', "
        f"{flags}, {event_type}, {parent_id}, {last_updated}, '{_sql_escape(source)}', "
        f"{availability}, {access_level}, {color}, {type_field}, {status})"
    )


def insert_calendar_event(
    title: str,
    start_time: int | datetime | str,
    end_time: int | datetime | str,
    location: str = "",
    description: str = "",
    reminder_1_minutes: int = -1,
    reminder_2_minutes: int = -1,
    reminder_3_minutes: int = -1,
    reminder_1_type: int = 0,
    reminder_2_type: int = 0,
    reminder_3_type: int = 0,
    repeat_interval: int = 0,
    repeat_rule: int = 0,
    repeat_limit: int = 0,
    repetition_exceptions: str = "[]",
    attendees: str = "[]",
    time_zone: str = "UTC",
    flags: int = 0,
    event_type: int = 1,
    parent_id: int = 0,
    source: str = "manual",
    availability: int = 0,
    access_level: int = 0,
    color: int = 0,
    type_field: int = 0,
    status: int = 1,
):
    """
    Insert a new calendar event into the database.

    Args:
        title: Event title
        start_time: Start timestamp (unix timestamp, datetime object, or string in format "YYYY-MM-DD HH:MM:SS")
        end_time: End timestamp (unix timestamp, datetime object, or string in format "YYYY-MM-DD HH:MM:SS")
        location: Event location (optional)
        description: Event description (optional)
        reminder_1_minutes: Minutes before event for first reminder (-1 for no reminder)
        reminder_2_minutes: Minutes before event for second reminder (-1 for no reminder)
        reminder_3_minutes: Minutes before event for third reminder (-1 for no reminder)
        ... (other fields with defaults)

    Returns:
        bool: True if successful, False otherwise
    """
    # Convert start_time to timestamp
    if isinstance(start_time, datetime):
        start_ts = int(start_time.timestamp())
    elif isinstance(start_time, str):
        if ":" not in start_time:
            start_time = f"{start_time} 00:00:00"
        start_ts = int(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").timestamp())
    else:
        start_ts = start_time

    # Convert end_time to timestamp
    if isinstance(end_time, datetime):
        end_ts = int(end_time.timestamp())
    elif isinstance(end_time, str):
        if ":" not in end_time:
            end_time = f"{end_time} 23:59:59"
        end_ts = int(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").timestamp())
    else:
        end_ts = end_time

    # Build one VALUES row via the shared builder (single source of truth for the
    # column order + escaping).
    row = build_event_values_row(
        start_ts=start_ts,
        end_ts=end_ts,
        title=title,
        location=location,
        description=description,
        reminder_1_minutes=reminder_1_minutes,
        reminder_2_minutes=reminder_2_minutes,
        reminder_3_minutes=reminder_3_minutes,
        reminder_1_type=reminder_1_type,
        reminder_2_type=reminder_2_type,
        reminder_3_type=reminder_3_type,
        repeat_interval=repeat_interval,
        repeat_rule=repeat_rule,
        repeat_limit=repeat_limit,
        repetition_exceptions=repetition_exceptions,
        attendees=attendees,
        time_zone=time_zone,
        flags=flags,
        event_type=event_type,
        parent_id=parent_id,
        source=source,
        availability=availability,
        access_level=access_level,
        color=color,
        type_field=type_field,
        status=status,
    )
    insert_sql = f"INSERT INTO events ({EVENTS_INSERT_COLUMNS}) VALUES {row};"

    cmd = f'adb shell "sqlite3 {db_path} \\"{insert_sql}\\""'
    result = execute_adb(cmd, root_required=True)

    if not result.success:
        raise RuntimeError(f"Failed to insert calendar event: {result.error}")

    return True


def get_calendar_events(
    time_range: list[int, int] | list[datetime, datetime] | list[str, str] | None = None,
    format_timestamp: bool = False,
):
    """
    Get all calendar events from the database.

    Sample output:
    [{'id': 1,
      'start_ts': 1759622400,
      'end_ts': 1759665600,
      'title': 'flight to Sdyney',
      'location': '',
      'description': '',
      'reminder_1_minutes': 10,
      'reminder_2_minutes': -1,
      'reminder_3_minutes': -1,
      'reminder_1_type': 0,
      'reminder_2_type': 0,
      'reminder_3_type': 0,
      'repeat_interval': 0,
      'repeat_rule': 0,
      'repeat_limit': 0,
      'repetition_exceptions': '[]',
      'attendees': '[]',
      'import_id': '44c7a7d76c7c46b9a1fbd54b4ffefe481760620226475',
      'time_zone': 'UTC',
      'flags': 1,
      'event_type': 1,
      'parent_id': 0,
      'last_updated': 1760620226475,
      'source': 'simple-calendar',
      'availability': 0,
      'access_level': 0,
      'color': 0,
      'type': 0,
      'status': 1}]
    """

    if time_range is not None:
        if isinstance(time_range[0], int) and isinstance(time_range[1], int):
            start_time, end_time = time_range
        elif isinstance(time_range[0], datetime) and isinstance(time_range[1], datetime):
            start_time = int(time_range[0].timestamp())
            end_time = int(time_range[1].timestamp())
        elif isinstance(time_range[0], str) and isinstance(time_range[1], str):
            if ":" not in time_range[0]:
                time_range[0] = f"{time_range[0]} 00:00:00"
            if ":" not in time_range[1]:
                time_range[1] = f"{time_range[1]} 23:59:59"
            start_time = int(datetime.strptime(time_range[0], "%Y-%m-%d %H:%M:%S").timestamp())
            end_time = int(datetime.strptime(time_range[1], "%Y-%m-%d %H:%M:%S").timestamp())
        else:
            raise ValueError(f"Invalid time range: {time_range}")
        cmd = f'adb shell "sqlite3 -json {db_path} \\"select * from events where start_ts >= {start_time} and end_ts <= {end_time}\\""'
    else:
        cmd = f'adb shell "sqlite3 -json {db_path} \\"select * from events\\""'
    result = execute_adb(cmd, root_required=True)
    if not result.success:
        raise RuntimeError(f"Failed to get calendar events: {result.error}")
    try:
        events = json.loads(result.output)
    except json.JSONDecodeError:
        return []

    if format_timestamp:
        for event in events:
            event["start_ts"] = datetime.fromtimestamp(event["start_ts"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            event["end_ts"] = datetime.fromtimestamp(event["end_ts"]).strftime("%Y-%m-%d %H:%M:%S")
    return events
