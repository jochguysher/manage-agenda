"""Sender-specific prompts, message windows, and visit slots before a room is occupied."""

import configparser
import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def social_config_dir():
    return Path.home() / ".mySocial" / "config"


def imap_date(day):
    """English IMAP date. Locale-independent, so a French system still sends Sep."""
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def _parse_config_date(value):
    text = (value or "").strip()
    if not text:
        return None
    return datetime.date.fromisoformat(text)


def _flag(value):
    return str(value or "").strip().lower() in {"yes", "true", "1", "include"}


def imap_age_criteria(details, today=None):
    """SINCE / BEFORE fragment. Older mail is excluded unless include_older or an explicit since."""
    today = today or datetime.date.today()
    since = _parse_config_date(details.get("since"))
    before = _parse_config_date(details.get("before"))
    include_older = _flag(details.get("include_older"))
    max_age = str(details.get("max_age_days") or "").strip()
    if since is None and not include_older and max_age.isdigit():
        since = today - datetime.timedelta(days=int(max_age))
    parts = []
    if since:
        parts.append(f"SINCE {imap_date(since)}")
    if before:
        parts.append(f"BEFORE {imap_date(before)}")
    return " ".join(parts)


def message_age_limit_days(details, today=None):
    """How many days old a message may be. Negative means no age limit."""
    if not any(key in details for key in ("include_older", "max_age_days", "since", "before")):
        return 7
    today = today or datetime.date.today()
    since = _parse_config_date(details.get("since"))
    if since:
        return max((today - since).days, 0)
    if _flag(details.get("include_older")):
        return -1
    max_age = str(details.get("max_age_days") or "").strip()
    if max_age.isdigit():
        return int(max_age)
    return 7


def combine_imap_search(sender_criteria, age_criteria):
    if sender_criteria and age_criteria:
        return f"({sender_criteria} {age_criteria})"
    if sender_criteria:
        return sender_criteria
    if age_criteria:
        return f"({age_criteria})"
    return None


@dataclass
class Availability:
    days: set = field(default_factory=lambda: {0, 1, 2, 3, 4})
    hours: list = field(default_factory=lambda: [(datetime.time(9, 0), datetime.time(17, 0))])
    slot_minutes: int = 60
    timezone: str = "America/Toronto"
    horizon_days: int = 45
    label: str = ""


def _parse_days(value):
    days = set()
    for part in (value or "").split(","):
        key = part.strip().lower()[:3]
        if key in WEEKDAYS:
            days.add(WEEKDAYS[key])
    return days


def _parse_hours(value):
    windows = []
    for part in (value or "").split(","):
        piece = part.strip()
        if not piece or "-" not in piece:
            continue
        start_text, end_text = piece.split("-", 1)
        windows.append(
            (datetime.time.fromisoformat(start_text.strip()), datetime.time.fromisoformat(end_text.strip()))
        )
    return windows


def availability_from_section(section):
    days = _parse_days(section.get("days", ""))
    hours = _parse_hours(section.get("hours", ""))
    slot = str(section.get("slot_minutes", "60")).strip()
    horizon = str(section.get("horizon_days", "45")).strip()
    return Availability(
        days=days or {0, 1, 2, 3, 4},
        hours=hours or [(datetime.time(9, 0), datetime.time(17, 0))],
        slot_minutes=int(slot) if slot.isdigit() else 60,
        timezone=section.get("timezone", "America/Toronto") or "America/Toronto",
        horizon_days=int(horizon) if horizon.isdigit() else 45,
        label=(section.get("label") or "").strip(),
    )


def _read_ini(path):
    parser = configparser.ConfigParser()
    if path.is_file():
        parser.read(path)
    return parser


def _match_score(rule, header):
    from manage_agenda.sources import _parse_sender_rule

    parsed = rule if isinstance(rule, dict) else _parse_sender_rule(str(rule))
    if not parsed:
        return 0
    text = (header or "").casefold()
    if not text:
        return 0
    score = 0
    address = (parsed.get("address") or "").casefold()
    name = (parsed.get("name") or "").casefold()
    if address:
        if address not in text:
            return 0
        score += 1 if address.startswith("@") else 3
    if name:
        if name not in text:
            return 0
        score += 2
    if name and address:
        score += 1
    return score


def _best_section(parser, header):
    best_name = None
    best_score = 0
    for name in parser.sections():
        score = _match_score(parser[name].get("match", ""), header)
        if score > best_score:
            best_name = name
            best_score = score
    return best_name


def prompt_template_for(header, config_dir=None):
    """Specific prompt text when a sender rule matches, otherwise None."""
    config_dir = Path(config_dir) if config_dir else social_config_dir()
    parser = _read_ini(config_dir / "prompts.ini")
    section = _best_section(parser, header)
    if not section:
        return None
    filename = parser[section].get("prompt", "").strip()
    if not filename:
        return None
    path = config_dir / "prompts" / filename
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def availability_for(header, config_dir=None):
    config_dir = Path(config_dir) if config_dir else social_config_dir()
    prompts = _read_ini(config_dir / "prompts.ini")
    availability = _read_ini(config_dir / "availability.ini")
    section_name = "default"
    matched = _best_section(prompts, header)
    if matched:
        named = prompts[matched].get("availability", "").strip()
        if named and availability.has_section(named):
            section_name = named
    if not availability.has_section(section_name):
        return Availability()
    return availability_from_section(availability[section_name])


def _occupied_dates(room):
    dates = []
    for value in room.get("occupied") or []:
        try:
            dates.append(datetime.date.fromisoformat(str(value)[:10]))
        except ValueError:
            continue
    start = room.get("start") or ""
    if start:
        try:
            dates.append(datetime.date.fromisoformat(str(start)[:10]))
        except ValueError:
            pass
    return dates


def _overlaps(slot_start, slot_end, busy):
    for busy_start, busy_end in busy:
        if slot_start < busy_end and busy_start < slot_end:
            return True
    return False


def propose_visit(room_name, occupied_dates, constraints, busy=None, today=None):
    """Earliest allowed slot strictly before the next occupation of this room."""
    today = today or datetime.date.today()
    busy = busy or []
    future = sorted(day for day in occupied_dates if day > today)
    if future:
        deadline = future[0]
        limit_note = deadline
    else:
        deadline = today + datetime.timedelta(days=constraints.horizon_days)
        limit_note = None
    try:
        import pytz

        zone = pytz.timezone(constraints.timezone)
    except Exception:
        import pytz

        zone = pytz.UTC
    day = today + datetime.timedelta(days=1)
    while day < deadline:
        if day.weekday() in constraints.days:
            for window_start, window_end in constraints.hours:
                cursor = datetime.datetime.combine(day, window_start)
                window_stop = datetime.datetime.combine(day, window_end)
                while cursor + datetime.timedelta(minutes=constraints.slot_minutes) <= window_stop:
                    slot_end_naive = cursor + datetime.timedelta(minutes=constraints.slot_minutes)
                    slot_start = zone.localize(cursor)
                    slot_end = zone.localize(slot_end_naive)
                    if not _overlaps(slot_start, slot_end, busy):
                        return {
                            "room": room_name,
                            "start": slot_start,
                            "end": slot_end,
                            "before": limit_note,
                        }
                    cursor = slot_end_naive
        day += datetime.timedelta(days=1)
    return None


def visit_title(label, rooms):
    """ACME - Salle 4, or ACME - Salle 1, 2 when several rooms share one visit."""
    names = []
    for room in rooms:
        text = " ".join(str(room).split())
        if not text or "@" in text:
            continue
        names.append(text)
    if not names:
        names = ["Salle"]
    numbers = []
    for name in names:
        match = re.fullmatch(r"salle\s+(\d+)", name, flags=re.IGNORECASE)
        if not match:
            numbers = []
            break
        numbers.append(match.group(1))
    if numbers:
        body = "Salle " + ", ".join(numbers)
    elif len(names) == 1:
        body = names[0]
    else:
        body = ", ".join(names)
    prefix = (label or "").strip()
    if prefix and not body.lower().startswith(prefix.lower()):
        return f"{prefix} - {body}"
    return body


def _room_label(event):
    for key in ("location", "summary"):
        text = event.get(key) or ""
        match = re.search(r"salle\s*\d+", str(text), flags=re.IGNORECASE)
        if match:
            number = re.search(r"\d+", match.group(0)).group(0)
            return f"Salle {number}"
    summary = " ".join(str(event.get("summary") or "").split())
    if summary and "@" not in summary:
        return summary
    return "Salle"


def _event_day(event):
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date") or ""
    text = str(raw)[:10]
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def as_occupancy(event):
    """Read occupations from a room_occupancy payload or from dates the model copied."""
    item = event[0] if isinstance(event, (list, tuple)) and event else event
    if isinstance(item, dict) and item.get("kind") == "room_occupancy":
        return item
    events = list(event) if isinstance(event, (list, tuple)) else [event]
    rooms = {}
    for one in events:
        if not isinstance(one, dict) or one.get("kind") == "room_occupancy":
            continue
        day = _event_day(one)
        if not day:
            continue
        rooms.setdefault(_room_label(one), set()).add(day)
    return {
        "kind": "room_occupancy",
        "rooms": [{"room": name, "occupied": sorted(days)} for name, days in rooms.items()],
    }


def is_occupancy_sender(header, config_dir=None):
    config_dir = Path(config_dir) if config_dir else social_config_dir()
    parser = _read_ini(config_dir / "prompts.ini")
    section = _best_section(parser, header)
    if not section:
        return False
    return parser[section].get("kind", "").strip().lower() == "occupancy"


def _next_occupation(dates, today, horizon_days):
    future = sorted(day for day in dates if day > today)
    if future:
        return future[0]
    return today + datetime.timedelta(days=horizon_days)


def plan_room_visits(payload, constraints, busy=None, today=None, sender=""):
    """A separate visit for each room, on the next free slot before its own occupation."""
    today = today or datetime.date.today()
    reserved = list(busy or [])
    pending = []
    for room in payload.get("rooms") or []:
        name = room.get("room") or "Salle"
        dates = _occupied_dates(room)
        pending.append((_next_occupation(dates, today, constraints.horizon_days), name, dates))
    pending.sort(key=lambda item: (item[0], item[1]))
    visits = []
    for _deadline, name, dates in pending:
        choice = propose_visit(name, dates, constraints, busy=reserved, today=today)
        if not choice:
            continue
        reserved.append((choice["start"], choice["end"]))
        before = choice["before"]
        if before:
            reason = f"avant la prochaine occupation du {before.isoformat()}"
        else:
            reason = "aucune occupation à venir n'a été trouvée dans l'horizon configuré"
        start = choice["start"]
        end = choice["end"]
        visits.append(
            {
                "summary": visit_title(constraints.label, [name]),
                "location": name,
                "description": (
                    f"Visite proposée {reason}. "
                    f"Créneau selon les contraintes ({constraints.timezone})."
                ),
                "start": {
                    "dateTime": start.strftime("%Y-%m-%d %H:%M:%S"),
                    "timeZone": constraints.timezone,
                },
                "end": {
                    "dateTime": end.strftime("%Y-%m-%d %H:%M:%S"),
                    "timeZone": constraints.timezone,
                },
            }
        )
    return visits


def busy_intervals(events):
    """Aware datetimes from a Google Calendar events.list payload."""
    if not isinstance(events, dict):
        return []
    items = events.get("items")
    if not isinstance(items, list):
        return []
    intervals = []
    for item in items:
        start = ((item.get("start") or {}).get("dateTime")) or ""
        end = ((item.get("end") or {}).get("dateTime")) or ""
        if not start or not end:
            continue
        try:
            start_dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            continue
        if start_dt.tzinfo and end_dt.tzinfo:
            intervals.append((start_dt, end_dt))
    return intervals
