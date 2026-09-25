"""Every widget a person can act on has an object name (what Qt Pilot targets), given by
AutoNamed from the attribute it is kept under, prefixed by its screen or dialog."""

import threading

from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from manage_agenda.gui import dialogs
from manage_agenda.gui.bridge import UIRequest
from manage_agenda.gui.main_window import MainWindow
from manage_agenda.gui.screens.accounts import AccountDialog
from manage_agenda.gui.widgets import CalendarSelectionDialog

ACTIONABLE = (QAbstractButton, QLineEdit, QComboBox, QAbstractItemView, QSpinBox, QPlainTextEdit)


def _actionable(root):
    return [w for w in root.findChildren(QWidget) if isinstance(w, ACTIONABLE)]


def _inside(widget, types):
    parent = widget.parent()
    while parent is not None:
        if isinstance(parent, types):
            return True
        parent = parent.parent()
    return False


def _unnamed(root):
    """The actionable widgets under `root` without a name, Qt's own internals excepted."""
    found = []
    for widget in _actionable(root):
        if isinstance(widget, QHeaderView) or widget.objectName().startswith("qt_"):
            continue
        if _inside(widget, (QComboBox, QSpinBox, QAbstractItemView)):
            continue  # a combo's popup list or line edit, a spin box's, a view's corner button
        if not widget.objectName():
            found.append(f"{type(widget).__name__} {widget.text() if hasattr(widget, 'text') else ''}")
    return found


def _names(root):
    return [w.objectName() for w in _actionable(root) if w.objectName() and not w.objectName().startswith("qt_")]


def _request(kind, **payload):
    request = UIRequest(kind, payload)
    request.done = threading.Event()
    return request


def test_every_screen_names_its_widgets(qapp):
    window = MainWindow()
    try:
        assert _unnamed(window) == []
        names = _names(window)
        assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)
        for expected in (
            "home_source", "home_run_button", "home_review_summary", "home_table",
            "add_run_button", "add_advanced_box", "accounts_add_button", "settings_save_button",
            "ledger_reconcile_button", "accounts_check_auth_button", "accounts_oauth_button",
            "lists_run_button", "evaluate_run_button", "calendar_ops_run_button",
            "main_cancel_button", "main_theme_menu", "main_tools_menu", "theme_dark", "install_browser",
            "main_log_summary", "log_details_button", "logSummary",
        ):
            assert window.findChild(object, expected) is not None, expected
        assert window.nav.objectName() == "nav" and window.log_dock.objectName() == "logDock"
        assert window.screens[0].title_label.objectName() == "screenTitle"
    finally:
        window.close()


def test_every_dialog_names_its_widgets(qapp):
    event = {"summary": "x", "start": {"dateTime": "2030-06-01T10:00:00Z"}}
    requests = [
        _request("choose_one", options=["a", "b"], title="t", identifier=None, default=None),
        _request("choose_many", options=["a", "b"], title="t", identifier=None),
        _request("choose_action", actions=[("keep", "Keep"), ("drop", "Drop")], prompt_text="?", default=""),
        _request("confirm", text="?", default=True),
        _request("ask_text", text="?", default=""),
        _request("ask_multiline", text="?"),
        _request("review_event", event=event, label="", context={}),
        _request("select_events", events=[event], labels=["x"], title="t", prompt_text=""),
    ]
    for request in requests:
        dialog = dialogs.build(request)
        assert _unnamed(dialog) == [], request.kind
        assert any(name.startswith(request.kind) for name in _names(dialog)), request.kind
        dialog.deleteLater()
    review = dialogs.build(requests[6])
    assert review.summary.objectName() == "review_event_summary"
    assert review.findChild(object, "review_event_accept_button") is not None
    review.deleteLater()
    actions = dialogs.build(requests[2])
    assert actions.buttons["keep"].objectName() == "choose_action_keep"
    actions.deleteLater()

    account = AccountDialog(lambda *_: None)
    assert _unnamed(account) == [] and account.save_button.objectName() == "account_save_button"
    account.deleteLater()
    calendars = CalendarSelectionDialog([{"id": "c1", "summary": "One"}])
    assert _unnamed(calendars) == [] and calendars.ok_button.objectName() == "calendars_ok_button"
    calendars.deleteLater()
    from manage_agenda.gui.bridge import Bridge
    from manage_agenda.gui.jobs import JobRunner
    from manage_agenda.gui.screens.install import InstallDialog

    install = InstallDialog(JobRunner(Bridge()))
    assert _unnamed(install) == [] and install.run_button.objectName() == "install_run_button"
    install.deleteLater()
