"""Widgets shared by several screens: account and calendar pickers, and the small helpers
that give every screen the same layout and the theme's roles (see gui/theme.py)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from manage_agenda.connections import _eligible_calendars, missing_calendar_message
from manage_agenda.exceptions import CalendarError
from manage_agenda.i18n import t
from manage_agenda.ui import label_for


def form_layout(parent=None):
    """A form whose fields take the available width, with the spacing every screen uses."""
    form = QFormLayout(parent) if parent is not None else QFormLayout()
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(8)
    return form


def set_role(widget, role):
    """Give `widget` the `role` the theme styles (hint, error, ok), re-polishing it so a
    change after the widget was shown takes effect."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def hint_label(text, parent=None):
    """A wrapped, muted label: the notes under a form or a field."""
    label = QLabel(text, parent)
    label.setWordWrap(True)
    set_role(label, "hint")
    return label


def primary(button):
    """Mark `button` as the screen's main action: the theme colours it with the accent."""
    button.setProperty("primary", True)
    return button


ELIDED_MIN_CHARS = 12


class ElidedLabel(QLabel):
    """A one-line label that shortens its text to the width it is given (an ellipsis in the
    middle) instead of demanding that width from its layout - a plain QLabel with a long
    calendar id widens the whole page. text() is still the full text, which is also the
    tooltip. Meant for a value in a form row, where a wrapped label would be clipped."""

    def __init__(self, text="", parent=None, mode=Qt.TextElideMode.ElideMiddle):
        super().__init__(parent)
        self.mode = mode
        # Expanding, with a size hint of a few characters: takes the width the layout has,
        # never asks for more (form_layout() only grows expanding fields).
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        return QSize(self.fontMetrics().averageCharWidth() * ELIDED_MIN_CHARS, super().minimumSizeHint().height())

    def sizeHint(self):
        return self.minimumSizeHint()

    def elided_text(self):
        """What is drawn: the text shortened to the current width."""
        return self.fontMetrics().elidedText(self.text(), self.mode, self.contentsRect().width())

    def paintEvent(self, _event):
        painter = QPainter(self)
        # QPainter starts with a black pen: take the colour the label would use itself (its
        # palette's foreground role, which a `role` rule in the theme's stylesheet sets).
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        painter.setPen(self.palette().color(group, self.foregroundRole()))
        painter.drawText(
            self.contentsRect(), int(self.alignment()) | Qt.TextFlag.TextSingleLine, self.elided_text()
        )


def load_rules():
    """socialModules' configured accounts (~/.mySocial/config/.rssBlogs), re-read each time -
    the same call every CLI command makes first."""
    from socialModules.moduleRules import moduleRules

    return moduleRules.from_config()


def rule_keys(rules, services):
    """The configured rule keys of `services`, in socialModules' order."""
    keys = []
    for service in services:
        keys.extend(rules.selectRule(service, "") or [])
    return keys


def account_label(key):
    """A rule key shown as "<nick> (<service>)" - `('imap', 'set', 'royal-review', 'posts')`
    reads as `royal-review (imap)` - and a pseudo-source (web, text) as its service name;
    anything else as label_for() shows it."""
    if isinstance(key, tuple) and len(key) >= 4 and key[2]:
        return f"{key[2]} ({key[0]})"
    if isinstance(key, tuple) and key and isinstance(key[0], str):
        return key[0]
    return label_for(key)


class AccountPicker(QComboBox):
    """The configured accounts of one or more services (e.g. ["gmail", "imap"])."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = list(services)
        self.keys = []

    def refresh(self, rules):
        current = self.current_key()
        self.keys = rule_keys(rules, self.services)
        self.clear()
        for key in self.keys:
            self.addItem(account_label(key))
        if current in self.keys:
            self.setCurrentIndex(self.keys.index(current))

    def current_key(self):
        index = self.currentIndex()
        return self.keys[index] if 0 <= index < len(self.keys) else None


def fetch_calendars(rules, key):
    """Connect the calendar account `key` and list its writable calendars: (api, calendars).
    Runs in the job runner (it may open the OAuth flow or hit the network)."""
    api = rules.readConfigSrc("", key, rules.more.get(key))
    if api is None or api.getClient() is None:
        raise CalendarError(missing_calendar_message(api))
    return api, _eligible_calendars(api)


class CalendarPicker(QListWidget):
    """Checkable list of an account's writable calendars, filled by fetch_calendars()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.api = None
        self.calendars = []

    def fill(self, api, calendars, checked_ids=()):
        self.api = api
        self.calendars = list(calendars)
        self.clear()
        for calendar in self.calendars:
            item = QListWidgetItem(label_for(calendar, "summary"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = calendar.get("id") in checked_ids
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.addItem(item)

    def checked_ids(self):
        return [
            self.calendars[row]["id"]
            for row in range(self.count())
            if self.item(row).checkState() == Qt.CheckState.Checked
        ]

    def set_all(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.count()):
            self.item(row).setCheckState(state)


def select_all_none_row(target, parent=None):
    """Select all / none buttons for a checkable list with a set_all(bool) method."""
    row = QHBoxLayout()
    select_all = QPushButton(t("gui.dialog.select_all"), parent)
    select_none = QPushButton(t("gui.dialog.select_none"), parent)
    select_all.clicked.connect(lambda: target.set_all(True))
    select_none.clicked.connect(lambda: target.set_all(False))
    row.addWidget(select_all)
    row.addWidget(select_none)
    row.addStretch(1)
    return row


class CalendarSelectionDialog(QDialog):
    """An account's calendars to check or uncheck: what the Add screen's "Load calendars…"
    opens once the account is connected. checked_ids() is the choice when accepted."""

    def __init__(self, calendars, checked_ids=(), parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(t("gui.add.calendars"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(hint_label(t("gui.add.calendars_note"), self))
        self.picker = CalendarPicker(self)
        self.picker.fill(None, calendars, checked_ids)
        layout.addWidget(self.picker)
        layout.addLayout(select_all_none_row(self.picker, self))
        buttons = QHBoxLayout()
        cancel = QPushButton(t("gui.dialog.cancel"), self)
        ok = primary(QPushButton(t("gui.dialog.ok"), self))
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def checked_ids(self):
        return self.picker.checked_ids()
