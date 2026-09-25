"""ConsoleUI: the terminal implementation of the UI port (manage_agenda.ui), and the only
module of the package allowed to read stdin.

Every method reproduces what the library did inline before the port existed - the same
prompt texts, the same `input()` calls, the same parsing of what was typed - so the CLI
behaves as it always has. The date-review helpers at the bottom are the code that used to
live in manage_agenda.events, moved here unchanged.
"""

import datetime
from datetime import timedelta

from socialModules.configMod import safe_get

from manage_agenda.events import (
    DATETIME_FORMAT,
    _format_datetime_for_display,
    _parse_event_times,
    adjust_event_times,
)
from manage_agenda.i18n import t
from manage_agenda.interactive import select_many, select_one
from manage_agenda.ui import describe_nature, describe_source


class ConsoleUI:
    """The UI port on a terminal. See manage_agenda.ui.UI for what each method means."""

    def choose_one(self, options, title="", identifier=None, default=None):
        # questionary's arrow-key list when there is a TTY, socialModules' numbered prompt
        # otherwise - see manage_agenda.interactive.
        return select_one(options, title=title, identifier=identifier, default=default)

    def choose_many(self, options, title="", identifier=None):
        return select_many(options, title=title, identifier=identifier)

    def choose_action(self, actions, prompt_text, default=""):
        # The raw line: the callers (extraction's r/p/s, events' clean menu) map it
        # themselves, exactly as they did when they called input() directly.
        return input(prompt_text)

    def confirm(self, text, default=False):
        return input(text).lower() == "y"

    def ask_text(self, text, default=""):
        return input(text)

    def ask_multiline(self, text):
        print(text)
        lines = []
        while True:
            try:
                lines.append(input())
            except EOFError:
                break
        return "\n".join(lines)

    def review_event(self, event, label="", context=None):
        for line in (describe_source(context), describe_nature(context)):
            if line:
                print(line)
        decision = "accept"
        confirmed = False
        while not confirmed:
            current_start, current_end = _parse_event_times(event)
            confirmation = input(f"{label}{t('events.date_confirm_prompt')}").lower()

            if confirmation == "r":
                decision = "retry"
                confirmed = True
            elif confirmation in ("s", ""):
                confirmed = True
            else:
                event = _process_date_modification(event, confirmation, current_start, current_end)

        return event, decision

    def select_events(self, events, labels, title="", prompt_text="", render=None):
        if title:
            print(title)
        if render is not None:
            render()

        print(t("events.all_option", index=len(events)))

        selection = input(prompt_text)

        if selection.lower() == "all" or selection == str(len(events)):
            return list(events)

        selected_events = []
        try:
            indices = [int(i.strip()) for i in selection.split(",")]
        except ValueError:
            indices = None
        if indices is not None and all(0 <= idx < len(events) for idx in indices):
            # All numbers are valid indices: number-based selection.
            return [events[i] for i in indices]

        # A number out of range, or not numbers at all: match the labels instead.
        lowered = [label.lower() for label in labels]
        for term in selection.split(","):
            term = term.strip().lower()
            for i, event in enumerate(events):
                if term in lowered[i] and event not in selected_events:
                    selected_events.append(event)
        return selected_events

    def echo(self, *parts, sep=" ", end="\n", flush=False):
        print(*parts, sep=sep, end=end, flush=flush)


# --- Date review on the terminal (formerly manage_agenda.events) ---


def _get_datetime_input(field_name):
    """Get datetime input from user with a consistent prompt."""
    return input(t("events.datetime_input_prompt", field=field_name))


def _process_full_datetime_modification(event):
    """Process full date/time modification (confirmation == 'f')."""
    new_start_str = _get_datetime_input("start")
    if new_start_str:
        event.setdefault("start", {})["dateTime"] = new_start_str
        try:
            start_dt = datetime.datetime.strptime(new_start_str, DATETIME_FORMAT)
            end_dt = start_dt + timedelta(minutes=45)
            new_end_str_default = end_dt.strftime(DATETIME_FORMAT)

            modify_end_time = input(
                t("events.default_end_time_prompt", new_end_str_default=new_end_str_default)
            ).lower()
            if modify_end_time == "y":
                new_end_str = _get_datetime_input("end")
            else:
                new_end_str = new_end_str_default
        except ValueError:
            print(t("events.invalid_start_time_format"))
            new_end_str = ""
    else:
        new_end_str = _get_datetime_input("end")

    if new_end_str:
        event.setdefault("end", {})["dateTime"] = new_end_str

    return event


def _process_individual_component_modification(event, confirmation, current_start, current_end):
    """Process an individual year, month, day, hour, or minute modification."""
    component_map = {"y": "year", "m": "month", "d": "day", "h": "hour", "i": "minute"}
    component = component_map.get(confirmation)

    for time_key, event_key, current_time in [
        ("start", "start", current_start),
        ("end", "end", current_end),
    ]:
        if current_time and component:
            new_time = _modify_single_component(current_time, component, time_key)
            event.setdefault(event_key, {})["dateTime"] = new_time.isoformat()

    return event


def _process_date_modification(event, confirmation, current_start, current_end):
    """Modify an event date according to the interactive confirmation choice."""
    if confirmation == "f":
        event = _process_full_datetime_modification(event)
    elif confirmation in ["m", "d", "h", "y", "i"]:
        event = _process_individual_component_modification(
            event, confirmation, current_start, current_end
        )

    event = adjust_event_times(event)

    start_time = safe_get(event, ["start", "dateTime"])
    end_time = safe_get(event, ["end", "dateTime"])
    print(t("events.updated_times_header"))
    print(t("events.start_label", value=_format_datetime_for_display(start_time)))
    print(t("events.end_label", value=_format_datetime_for_display(end_time)))
    print(t("events.updated_times_footer"))

    return event


def _modify_single_component(dt, component, time_label):
    """Modify one datetime component based on interactive input."""
    print(t("events.modifying_component", component=component, time_label=time_label))
    print(t("events.current_value", value=dt))

    value_str = input(
        t("events.new_component_prompt", component=component, current=getattr(dt, component))
    ).strip()
    if value_str:
        try:
            new_value = int(value_str)
            if component == "year":
                new_dt = dt.replace(year=new_value)
            elif component == "month":
                new_dt = dt.replace(month=new_value)
            elif component == "day":
                new_dt = dt.replace(day=new_value)
            elif component == "hour":
                new_dt = dt.replace(hour=new_value)
            elif component == "minute":
                new_dt = dt.replace(minute=new_value)
            else:
                print(t("events.unknown_component", component=component))
                return dt

            print(t("events.new_time_label", time_label=time_label, value=new_dt))
            return new_dt
        except ValueError as error:
            print(t("events.invalid_value", error=error))
            return dt

    return dt
