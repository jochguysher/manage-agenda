"""Home: the task itself. Read a mailbox for dates, get each event proposed (or planned
without asking), and see what is on the destination calendar with the events the tool
created marked. The other screens are the tool's parts; this one is its purpose.

The run is `add`, exactly as the Add screen submits it: the mailbox picked here and
Args(interactive=<review mode>) - the saved calendar and model apply, and the questions a
review asks come up inline (the proposal box) instead of as dialogs, through
MainWindow._on_ui_request. The calendar table is read on request and after a run only:
connecting the account may open the browser consent, so nothing here connects at startup.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from manage_agenda.connections import _eligible_calendars, missing_calendar_message
from manage_agenda.exceptions import CalendarError
from manage_agenda.gui.persist import gui_settings
from manage_agenda.gui.review_form import EventReviewForm, to_local_text
from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import (
    AccountPicker,
    account_label,
    form_layout,
    hint_label,
    load_rules,
    primary,
    set_role,
)
from manage_agenda.i18n import t
from manage_agenda.sources import (
    Args,
    _get_events_from_calendar,
    add_events_cli,
    load_handled_mail_state,
)
from manage_agenda.ui import describe_nature, describe_source
from manage_agenda.user_config import load_user_config, saved_calendar_ids

MAIL_SERVICES = ("gmail", "imap")
MAX_ROWS = 80
SETTING_SOURCE = "home/source"
SETTING_REVIEW = "home/review"


def tool_created(event):
    """Whether the tool created this calendar event: extraction._add_ai_metadata_to_event()
    leaves its mark in the event's private extended properties."""
    private = (event.get("extendedProperties") or {}).get("private") or {}
    return "ai_model_used" in private


def event_start(event):
    """The start as (sort key, shown text): a dateTime in local time, or an all-day date."""
    start = event.get("start") or {}
    if start.get("dateTime"):
        return str(start["dateTime"]), to_local_text(start["dateTime"])
    date = str(start.get("date") or "")
    return date, date


def ledger_stats(path=None):
    """(messages handled, events recorded, last recorded_at, event_id -> recorded_at) from the
    local ledger - no network."""
    state = load_handled_mail_state(path)
    recorded = {}
    for entry in state.values():
        for ref in entry.get("events") or []:
            if ref.get("event_id"):
                recorded[str(ref["event_id"])] = str(ref.get("recorded_at") or "")
    last = max(
        [str(entry.get("recorded_at") or "") for entry in state.values()] + list(recorded.values()),
        default="",
    )
    return len(state), len(recorded), last, recorded


def fetch_planned(rules, account_key, calendar_ids):
    """Connect calendar account `account_key` and list the upcoming events of `calendar_ids`
    (the account's primary calendar when none is saved): the rows of the "On the calendar"
    table. Runs in the job runner: it may open the OAuth consent or hit the network."""
    api = rules.readConfigSrc("", account_key, rules.more.get(account_key))
    if api is None or api.getClient() is None:
        raise CalendarError(missing_calendar_message(api))
    names = {}
    try:
        names = {
            calendar.get("id"): calendar.get("summary") or calendar.get("id")
            for calendar in _eligible_calendars(api)
        }
    except CalendarError:
        pass
    rows = []
    for calendar_id in list(calendar_ids) or ["primary"]:
        for event in _get_events_from_calendar(Args(), api, calendar_id) or []:
            if not isinstance(event, dict):
                continue
            sort_key, when = event_start(event)
            rows.append(
                {
                    "id": str(event.get("id") or ""),
                    "sort": sort_key,
                    "when": when,
                    "summary": event.get("summary") or "",
                    "calendar": names.get(calendar_id, calendar_id),
                    "link": event.get("htmlLink") or "",
                    "tool": tool_created(event),
                }
            )
    rows.sort(key=lambda row: row["sort"])
    return rows[:MAX_ROWS]


def fetch_planned_or_message(rules, account_key, calendar_ids):
    """fetch_planned(), with the expected failure (no token, no calendar) as the message to
    show under the table instead of the main window's error box."""
    try:
        return fetch_planned(rules, account_key, calendar_ids)
    except CalendarError as error:
        return str(error)


def scan_mailbox(args, rules, key):
    """The home's run: `add` on mailbox `key`, once the mailbox has answered. socialModules
    hands back a client-less api when the connection fails (a local bridge down, a wrong
    password) and the flow then carries on reading nothing - which would end here as a
    scan that found nothing. ("unreachable", message) instead; add_events_cli's result
    otherwise. Runs in the job runner."""
    api = rules.readConfigSrc("", key, rules.more.get(key))
    if api is None or api.getClient() is None:
        return ("unreachable", t("gui.home.mailbox_unreachable", account=account_label(key)))
    return add_events_cli(args, rules, key)


def mailbox_warning(rules, key):
    """What to say about mailbox `key` before a scan: an IMAP account whose sender filter
    is present but empty selects nothing (the .rssBlogs header documents that as a way to
    park an account), so a scan of it is empty by construction."""
    details = (rules.more.get(key) if rules is not None and key is not None else None) or {}
    if str(details.get("service") or "").lower() != "imap":
        return ""
    if "from" in details and not str(details.get("from") or "").strip():
        return t("gui.home.inert_mailbox")
    return ""


class HomeScreen(Screen):
    nav_key = "gui.nav.home"
    subtitle_key = "gui.home.subtitle"
    open_screen = Signal(object)  # a Screen subclass the main window should show

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        self.rules = None
        self.saved = {}
        self.rows = []
        self.review_request = None
        self.running_from_home = False
        self._run_started_at = ""
        layout = self.content

        run_box = QGroupBox(t("gui.home.run_box"), self)
        run_layout = QVBoxLayout(run_box)
        form = form_layout()
        self.source = AccountPicker(MAIL_SERVICES, self)
        mode_row = QHBoxLayout()
        self.review_mode = QRadioButton(t("gui.home.mode_review"), self)
        self.auto_mode = QRadioButton(t("gui.home.mode_auto"), self)
        self.review_mode.setChecked(True)
        mode_row.addWidget(self.review_mode)
        mode_row.addWidget(self.auto_mode)
        mode_row.addStretch(1)
        self.destination = QLabel("", self)
        form.addRow(t("gui.home.source"), self.source)
        form.addRow(t("gui.home.mode"), mode_row)
        form.addRow(t("gui.home.destination"), self.destination)
        run_layout.addLayout(form)
        self.mailbox_hint = hint_label("", self)
        set_role(self.mailbox_hint, "error")
        self.mailbox_hint.hide()
        run_layout.addWidget(self.mailbox_hint)
        run_layout.addWidget(hint_label(t("gui.home.mode_hint"), self))
        row = QHBoxLayout()
        self.run_button = self.register_run_button(primary(QPushButton(t("gui.home.run"), self)))
        self.advanced_button = QPushButton(t("gui.home.open_advanced"), self)
        self.settings_button = QPushButton(t("gui.home.open_settings"), self)
        row.addWidget(self.run_button)
        row.addStretch(1)
        row.addWidget(self.advanced_button)
        row.addWidget(self.settings_button)
        run_layout.addLayout(row)
        self.message = QLabel("", self)
        self.message.setWordWrap(True)
        run_layout.addWidget(self.message)
        layout.addWidget(run_box)

        self.review_box = QGroupBox(t("gui.home.review_box"), self)
        review_layout = QVBoxLayout(self.review_box)
        self.review_label = hint_label("", self)
        self.review_form = EventReviewForm(self)
        review_layout.addWidget(self.review_label)
        review_layout.addWidget(self.review_form)
        review_buttons = QHBoxLayout()
        self.stop_button = QPushButton(t("gui.home.review_stop"), self)
        self.retry_button = QPushButton(t("events.review_retry"), self)
        self.accept_button = primary(QPushButton(t("gui.home.review_accept"), self))
        review_buttons.addWidget(self.stop_button)
        review_buttons.addStretch(1)
        review_buttons.addWidget(self.retry_button)
        review_buttons.addWidget(self.accept_button)
        review_layout.addLayout(review_buttons)
        self.review_box.hide()
        layout.addWidget(self.review_box)

        planned_box = QGroupBox(t("gui.home.planned_box"), self)
        planned_layout = QVBoxLayout(planned_box)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            [
                t("gui.home.column_when"),
                t("gui.home.column_title"),
                t("gui.home.column_calendar"),
                t("gui.home.column_origin"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(180)
        planned_layout.addWidget(self.table, 1)
        planned_row = QHBoxLayout()
        self.ledger_summary = hint_label("", self)
        self.refresh_button = self.register_run_button(QPushButton(t("gui.home.refresh"), self))
        planned_row.addWidget(self.ledger_summary, 1)
        planned_row.addWidget(self.refresh_button)
        planned_layout.addLayout(planned_row)
        self.planned_message = hint_label(t("gui.home.planned_hint"), self)
        planned_layout.addWidget(self.planned_message)
        layout.addWidget(planned_box, 1)

        self.run_button.clicked.connect(self.run)
        self.refresh_button.clicked.connect(self.refresh_planned)
        self.advanced_button.clicked.connect(lambda: self._open("add"))
        self.settings_button.clicked.connect(lambda: self._open("settings"))
        self.accept_button.clicked.connect(lambda: self.answer_review("accept"))
        self.retry_button.clicked.connect(lambda: self.answer_review("retry"))
        self.stop_button.clicked.connect(self.stop_run)
        self.table.itemDoubleClicked.connect(self._open_row)
        self.source.currentIndexChanged.connect(self._remember_choices)
        self.source.currentIndexChanged.connect(self._update_mailbox_hint)
        self.review_mode.toggled.connect(self._remember_choices)
        runner.finished.connect(self._after_run)
        runner.failed.connect(self._run_aborted)
        runner.cancelled.connect(self._run_aborted)

    # --- local state: what is shown without connecting anywhere ---

    def refresh(self):
        try:
            self.rules = load_rules()
            self.last_error = ""
        except Exception as error:  # noqa: BLE001 - shown, the screen stays usable
            self.rules = None
            self.last_error = f"{type(error).__name__}: {error}"
            self.message.setText(self.last_error)
        self.saved = load_user_config()
        if self.rules is not None:
            self._restore_choices()
        self._update_mailbox_hint()
        self.destination.setText(self._destination_text())
        self._update_ledger_summary()

    def _update_mailbox_hint(self, *_ignored):
        warning = mailbox_warning(self.rules, self.source.current_key())
        self.mailbox_hint.setText(warning)
        self.mailbox_hint.setVisible(bool(warning))

    def _restore_choices(self):
        """Refill the mailbox picker and put back the last mailbox and mode. The picker's
        signals stay blocked meanwhile: refilling it would otherwise be remembered as a
        choice of its first entry before the saved one is read."""
        settings = gui_settings()
        wanted = settings.value(SETTING_SOURCE, "")
        review = str(settings.value(SETTING_REVIEW, "true")).lower() != "false"
        self.source.blockSignals(True)
        try:
            self.source.refresh(self.rules)
            labels = [str(key) for key in self.source.keys]
            if wanted in labels:
                self.source.setCurrentIndex(labels.index(wanted))
        finally:
            self.source.blockSignals(False)
        (self.review_mode if review else self.auto_mode).setChecked(True)

    def _remember_choices(self, *_ignored):
        key = self.source.current_key()
        if key is None:
            return
        settings = gui_settings()
        settings.setValue(SETTING_SOURCE, str(key))
        settings.setValue(SETTING_REVIEW, "true" if self.review_mode.isChecked() else "false")

    def saved_calendar_account(self):
        account = self.saved.get("calendar_account")
        return tuple(account) if isinstance(account, list) else account

    def _destination_text(self):
        account = self.saved_calendar_account()
        calendars = ", ".join(saved_calendar_ids(self.saved))
        if not account or not calendars:
            where = t("gui.home.no_calendar")
        else:
            where = f"{calendars} ({account_label(account)})"
        model = " / ".join(
            part for part in (self.saved.get("provider"), self.saved.get("model")) if part
        )
        return t("gui.home.destination_text", calendars=where, model=model or t("gui.home.model_default"))

    def _update_ledger_summary(self):
        messages, events, last, _recorded = ledger_stats()
        if not messages:
            self.ledger_summary.setText(t("gui.home.ledger_empty"))
        else:
            self.ledger_summary.setText(
                t("gui.home.ledger_summary", messages=messages, events=events, last=to_local_text(last))
            )

    def _open(self, which):
        from manage_agenda.gui.screens.add import AddScreen
        from manage_agenda.gui.screens.settings import SettingsScreen

        self.open_screen.emit(AddScreen if which == "add" else SettingsScreen)

    # --- the run ---

    def build_args(self):
        """The Args of `manage-agenda add [-i]`: review mode is `-i`."""
        return Args(interactive=self.review_mode.isChecked())

    def run(self):
        key = self.source.current_key()
        if self.rules is None or key is None:
            self.message.setText(t("gui.home.no_source"))
            return
        self.message.setText("")
        self.running_from_home = True
        self._run_started_at = (
            datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        )
        if not self.submit(t("gui.home.job"), scan_mailbox, self.build_args(), self.rules, key):
            self.running_from_home = False

    def _on_ended(self, *_ignored):
        super()._on_ended()
        self._hide_review()

    def _run_aborted(self, *_ignored):
        """A failed or cancelled job: a run started here is over, and a later job's end
        must not be taken for its end (the proposal box is hidden by _on_ended)."""
        self.running_from_home = False

    def _after_run(self, result):
        if not self.running_from_home:
            return
        self.running_from_home = False
        if isinstance(result, tuple) and result and result[0] == "unreachable":
            set_role(self.message, "error")
            self.message.setText(result[1])
            return
        set_role(self.message, "")
        _messages, _events, _last, recorded = ledger_stats()
        new = sum(1 for stamp in recorded.values() if stamp >= self._run_started_at)
        self.message.setText(
            t("gui.home.run_done", events=new) if new else t("gui.home.run_done_none")
        )
        self._update_ledger_summary()
        self.refresh_planned()

    # --- the proposal: a review_event request answered inline ---

    def accepts_review(self):
        return self.running_from_home

    def present_review(self, request):
        self.review_request = request
        context = request.payload.get("context")
        source = describe_source(context)
        label = str(request.payload.get("label") or "").strip().strip("[]").strip()
        if not source and label:
            source = t("gui.home.review_from", label=label)
        lines = [line for line in (source, describe_nature(context)) if line]
        self.review_label.setText("\n".join(lines))
        self.review_form.load(request.payload["event"])
        self.review_box.show()
        self.review_form.summary.setFocus()
        QTimer.singleShot(0, lambda: self._reveal(self.review_box))

    def _reveal(self, widget):
        """Scroll the page (the main window puts each screen in a scroll area) to `widget`."""
        try:
            if not widget.isVisible():
                return
            parent = widget.parent()
            while parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parent()
        except RuntimeError:  # the window was closed before the timer fired
            return
        if parent is not None:
            parent.ensureWidgetVisible(widget, 0, 40)

    def answer_review(self, decision):
        request = self.review_request
        if request is None:
            return
        if decision == "accept" and not self.review_form.validate():
            return
        self._hide_review()
        request.answer((self.review_form.event_data, decision))

    def cancel_review(self):
        request = self.review_request
        self._hide_review()
        if request is not None and not request.done.is_set():
            request.cancel()

    def _hide_review(self):
        self.review_request = None
        self.review_box.hide()

    def stop_run(self):
        self.runner.cancel()
        self.cancel_review()

    # --- what is on the calendar ---

    def refresh_planned(self):
        account = self.saved_calendar_account()
        if self.rules is None or not account:
            self.planned_message.setText(t("gui.home.no_calendar_account"))
            return
        self.submit(
            t("gui.home.job_planned"),
            fetch_planned_or_message,
            self.rules,
            account,
            saved_calendar_ids(self.saved),
            on_done=self.fill_planned,
        )

    def fill_planned(self, result):
        """Show the rows fetch_planned() returned, or its failure message."""
        if isinstance(result, str):
            self.rows = []
            self.table.setRowCount(0)
            self.planned_message.setText(result)
            return
        self.rows = list(result)
        _messages, _events, _last, recorded = ledger_stats()
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            if row["tool"] or row["id"] in recorded:
                recent = recorded.get(row["id"], "") >= self._run_started_at > ""
                origin = t("gui.home.origin_new" if recent else "gui.home.origin_tool")
            else:
                origin = ""
            for column, text in enumerate((row["when"], row["summary"], row["calendar"], origin)):
                self.table.setItem(index, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.planned_message.setText(
            t("gui.home.planned_hint") if self.rows else t("gui.home.planned_empty")
        )

    def _open_row(self, item):
        row = item.row()
        link = self.rows[row]["link"] if 0 <= row < len(self.rows) else ""
        if link:
            QDesktopServices.openUrl(QUrl(link))
