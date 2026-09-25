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


MAX_RANGE_DAYS = 62


def _date_range(first, last):
    """Every day from `first` to `last` inclusive (capped, a model can write anything)."""
    days = []
    day = first
    while day <= last and len(days) < MAX_RANGE_DAYS:
        days.append(day)
        day += datetime.timedelta(days=1)
    return days


def _occupied_dates(room):
    """The occupied days of a room: dates, and ranges written as "2026-09-27/2026-10-03",
    "2026-09-27..2026-10-03" or {"from": ..., "to": ...} - a week announced as one period
    counts for each of its days."""
    dates = []
    for value in room.get("occupied") or []:
        if isinstance(value, dict):
            bounds = [value.get("from") or value.get("start"), value.get("to") or value.get("end")]
        else:
            text = str(value).strip()
            bounds = re.split(r"\s*(?:/|\.\.|\s-\s|\bau\b|\bto\b)\s*", text, maxsplit=1)
        try:
            parsed = [datetime.date.fromisoformat(str(bound).strip()[:10]) for bound in bounds if bound]
        except ValueError:
            continue
        if len(parsed) == 2 and parsed[0] <= parsed[1]:
            dates.extend(_date_range(parsed[0], parsed[1]))
        elif parsed:
            dates.append(parsed[0])
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


def occupation_blocks(dates):
    """The occupied days grouped into runs of consecutive days: [(first, last), ...]. The
    legacy payload (`occupied`: a list of days) has no line-by-line instruction; a run is
    one occupation there."""
    blocks = []
    for day in sorted(set(dates)):
        if blocks and day == blocks[-1][1] + datetime.timedelta(days=1):
            blocks[-1] = (blocks[-1][0], day)
        else:
            blocks.append((day, day))
    return blocks


def _zone(constraints):
    import pytz

    try:
        return pytz.timezone(constraints.timezone)
    except Exception:
        return pytz.UTC


def _parse_when(value, zone, end_of_day=False):
    """An aware datetime from what the model wrote: "YYYY-MM-DDTHH:MM", "YYYY-MM-DD HH:MM"
    or a bare date - midnight, or the next midnight for `end_of_day` (an end written as a
    date covers that whole day). None when unreadable."""
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    try:
        day = datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None
    clock = text[10:].strip()
    if clock:
        try:
            when = datetime.datetime.combine(day, datetime.time.fromisoformat(clock[:5]))
        except ValueError:
            return None
    else:
        when = datetime.datetime.combine(day, datetime.time(0, 0))
        if end_of_day:
            when += datetime.timedelta(days=1)
    return zone.localize(when)


def _truthy(value):
    return str(value).strip().lower() in {"true", "yes", "oui", "1"} if not isinstance(value, bool) else value


def room_occupations(room, constraints):
    """A room's occupations as [{"start", "end", "clean", "deadline"}, ...], aware and in
    time order. The current payload lists them (`occupations`, one per message line, with
    the line's instruction: `clean` true only when the line asks for a cleaning, and the
    limit it gives as `clean_before`); the legacy one lists days (`occupied`), which count
    as whole days to clean after, run by run."""
    zone = _zone(constraints)
    found = []
    for item in room.get("occupations") or []:
        if not isinstance(item, dict):
            continue
        start = _parse_when(item.get("start"), zone)
        end = _parse_when(item.get("end"), zone, end_of_day=True)
        if start is None:
            continue
        if end is None:
            end = zone.localize(datetime.datetime.combine(start.date() + datetime.timedelta(days=1), datetime.time(0, 0)))
        if end <= start:
            # "14 h à 2 h du matin": an end before its start is the next day's.
            end = end + datetime.timedelta(days=1)
        found.append(
            {
                "start": start,
                "end": end,
                "clean": _truthy(item.get("clean", False)),
                "deadline": _parse_when(item.get("clean_before"), zone),
            }
        )
    for first, last in occupation_blocks(_occupied_dates(room)):
        found.append(
            {
                "start": zone.localize(datetime.datetime.combine(first, datetime.time(0, 0))),
                "end": zone.localize(
                    datetime.datetime.combine(last + datetime.timedelta(days=1), datetime.time(0, 0))
                ),
                "clean": True,
                "deadline": None,
            }
        )
    found.sort(key=lambda item: (item["start"], item["end"]))
    return found


def _slots_from(earliest, constraints, zone, horizon_days):
    """The allowed slots from `earliest` on, in order, for horizon_days days."""
    slot = datetime.timedelta(minutes=constraints.slot_minutes)
    day = earliest.date()
    deadline = day + datetime.timedelta(days=horizon_days)
    while day < deadline:
        if day.weekday() in constraints.days:
            for window_start, window_end in constraints.hours:
                cursor = datetime.datetime.combine(day, window_start)
                window_stop = datetime.datetime.combine(day, window_end)
                while cursor + slot <= window_stop:
                    slot_start = zone.localize(cursor)
                    if slot_start >= earliest:
                        yield slot_start, zone.localize(cursor + slot)
                    cursor += slot
        day += datetime.timedelta(days=1)


def cleaning_title(label, rooms):
    """ACME - Salle 4, or ACME - Salle 1, 2 when several rooms share one cleaning."""
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


visit_title = cleaning_title  # the former name


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


def _event_days(event):
    """The days an event copied by the model covers, first to last: a week-long event is a
    week of occupation, not its first day."""
    days = []
    for when in ("start", "end"):
        field = event.get(when) or {}
        raw = field.get("dateTime") or field.get("date") or ""
        try:
            days.append(datetime.date.fromisoformat(str(raw)[:10]))
        except ValueError:
            continue
    if not days:
        return []
    first, last = days[0], days[-1]
    if last < first:
        return [first.isoformat()]
    return [day.isoformat() for day in _date_range(first, last)]


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
        days = _event_days(one)
        if not days:
            continue
        rooms.setdefault(_room_label(one), set()).update(days)
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


CLEANING_KIND = "cleaning"
_MINUTE = "%Y-%m-%d %H:%M"


def occupation_text(start, end):
    """"le 2026-09-28 de 00:00 à 21:30", "du 2026-09-27 au 2026-10-03" for whole days, or
    "du 2026-05-30 14:00 au 2026-05-31 02:00"."""
    midnight = datetime.time(0, 0)
    if start.time() == midnight and end.time() == midnight:
        last = (end - datetime.timedelta(days=1)).date()
        if last == start.date():
            return f"le {start.date().isoformat()}"
        return f"du {start.date().isoformat()} au {last.isoformat()}"
    if start.date() == end.date():
        return f"le {start.date().isoformat()} de {start.strftime('%H:%M')} à {end.strftime('%H:%M')}"
    return f"du {start.strftime(_MINUTE)} au {end.strftime(_MINUTE)}"


def _first_slot(earliest, constraints, zone, busy):
    """The first allowed slot starting at or after `earliest` that is free of `busy`."""
    for slot_start, slot_end in _slots_from(earliest, constraints, zone, constraints.horizon_days):
        if not _overlaps(slot_start, slot_end, busy):
            return slot_start, slot_end
    return None


def _block(earliest, count, constraints, zone, busy, deadline=None):
    """`count` consecutive allowed slots (no gap, none busy) starting at or after `earliest`,
    ending by `deadline` when given: one trip for several rooms. None when there is none."""
    run = []
    for slot_start, slot_end in _slots_from(earliest, constraints, zone, constraints.horizon_days):
        if deadline is not None and slot_end > deadline:
            return None
        if _overlaps(slot_start, slot_end, busy):
            run = []
            continue
        if run and slot_start != run[-1][1]:
            run = []
        run.append((slot_start, slot_end))
        if len(run) == count:
            return run
    return None


def _cleaning_windows(payload, constraints, today, busy):
    """Every cleaning a message asks for, with the window its start may take: from the
    first free slot after the occupation (never before the day after `today`) to the last
    slot before the line's deadline - the first slot alone when the line gives none: a
    cleaning does not wait for company unless the message allows it to. A cleaning the
    room's next occupation overtakes is dropped unless a deadline holds it."""
    zone = _zone(constraints)
    tomorrow = zone.localize(
        datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time(0, 0))
    )
    slot = datetime.timedelta(minutes=constraints.slot_minutes)
    windows = []
    for room in payload.get("rooms") or []:
        name = room.get("room") or "Salle"
        occupations = room_occupations(room, constraints)
        for index, occupation in enumerate(occupations):
            if not occupation["clean"]:
                continue
            deadline = occupation.get("deadline")
            earliest = max(occupation["end"], tomorrow)
            first = _first_slot(earliest, constraints, zone, busy)
            if first is None or (deadline is not None and first[1] > deadline):
                if deadline is None or deadline <= earliest:
                    continue
                # Nothing allowed fits before the deadline: the last slot before it, forced.
                forced_start = max(earliest, deadline - slot)
                windows.append(
                    {"name": name, "occupation": occupation, "start": forced_start, "latest": forced_start, "forced_end": deadline}
                )
                continue
            if deadline is None and any(item["start"] < first[0] for item in occupations[index + 1 :]):
                continue
            latest = first[0] if deadline is None else max(first[0], deadline - slot)
            windows.append({"name": name, "occupation": occupation, "start": first[0], "latest": latest, "forced_end": None})
    return windows


def _group_windows(windows):
    """Cleanings whose windows overlap share one trip: the greedy grouping of intervals by
    earliest end, the shared window narrowing as members join."""
    groups = []
    for window in sorted(windows, key=lambda item: (item["latest"], item["start"])):
        for group in groups:
            low = max(group["start"], window["start"])
            high = min(group["latest"], window["latest"])
            if low <= high and not window["forced_end"] and not group["forced"]:
                group["members"].append(window)
                group["start"], group["latest"] = low, high
                break
        else:
            groups.append(
                {"members": [window], "start": window["start"], "latest": window["latest"], "forced": bool(window["forced_end"])}
            )
    return groups


def _priority(window):
    far = datetime.datetime.max.replace(tzinfo=window["occupation"]["end"].tzinfo)
    return (window["occupation"].get("deadline") or far, window["occupation"]["end"])


def plan_cleanings(payload, constraints, busy=None, today=None, sender=""):
    """The cleanings a message asks for, as calendar events. Each occupation whose line asks
    for a cleaning gets one after it ends, on the configured days and hours, avoiding what
    the calendar holds; the line's deadline, when given, has priority: the cleaning fits
    before it, outside the configured hours if it must. Cleanings that can be done on the
    same trip - their windows overlap - become one event over consecutive slots, the room
    with the earliest deadline first; a deadline lets a cleaning wait for a later one, a
    line without one does not. Each event names the occupations it answers (description,
    private extended properties: kind, room, occupied_from, occupied_to, clean_before)."""
    today = today or datetime.date.today()
    zone = _zone(constraints)
    reserved = list(busy or [])
    windows = _cleaning_windows(payload, constraints, today, reserved)
    events = []
    for group in sorted(_group_windows(windows), key=lambda item: item["start"]):
        members = sorted(group["members"], key=_priority)
        deadlines = [m["occupation"]["deadline"] for m in members if m["occupation"].get("deadline")]
        if group["forced"]:
            member = members[0]
            slots = [(member["start"], member["forced_end"])]
        else:
            slots = _block(group["start"], len(members), constraints, zone, reserved, deadline=min(deadlines, default=None))
            if slots is None:
                # No trip long enough for everyone: each on its own first free slot.
                slots = []
                for member in members:
                    own = _first_slot(member["start"], constraints, zone, reserved)
                    if own is None:
                        continue
                    reserved.append(own)
                    events.append(_cleaning_event([member], own[0], own[1], constraints, forced=False))
                continue
        reserved.extend(slots)
        events.append(_cleaning_event(members, slots[0][0], slots[-1][1], constraints, forced=group["forced"]))
    events.sort(key=lambda event: event["start"]["dateTime"])
    return events


def _cleaning_event(members, start, end, constraints, forced):
    """The calendar event of one trip: its title names every room, its description every
    occupation answered, in the order the rooms are to be done."""
    names = [member["name"] for member in members]
    occupations = [member["occupation"] for member in members]
    parts = []
    for name, occupation in zip(names, occupations, strict=True):
        part = f"{name} {occupation_text(occupation['start'], occupation['end'])}"
        if occupation.get("deadline") is not None:
            part += f", à faire avant le {occupation['deadline'].strftime(_MINUTE)}"
        parts.append(part)
    if len(parts) == 1:
        details = f"Entretien proposé après l'occupation de {parts[0]}"
    else:
        details = (
            "Entretien proposé après les occupations de "
            + " ; ".join(parts)
            + ", en un seul passage dans cet ordre (mêmes locaux)"
        )
    if forced:
        details += " : hors des jours et heures configurés, le délai du message ne laisse pas d'autre créneau."
    else:
        details += f" : premier créneau libre selon les jours et heures configurés ({constraints.timezone})."
    private = {
        "kind": CLEANING_KIND,
        "room": ", ".join(names),
        "occupied_from": min(occupation["start"] for occupation in occupations).strftime(_MINUTE),
        "occupied_to": max(occupation["end"] for occupation in occupations).strftime(_MINUTE),
    }
    deadlines = [occupation["deadline"] for occupation in occupations if occupation.get("deadline")]
    if deadlines:
        private["clean_before"] = min(deadlines).strftime(_MINUTE)
    return {
        "summary": cleaning_title(constraints.label, names),
        "location": ", ".join(names),
        "description": details,
        "start": {"dateTime": start.strftime("%Y-%m-%d %H:%M:%S"), "timeZone": constraints.timezone},
        "end": {"dateTime": end.strftime("%Y-%m-%d %H:%M:%S"), "timeZone": constraints.timezone},
        "extendedProperties": {"private": private},
    }


plan_room_visits = plan_cleanings  # the former name


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
