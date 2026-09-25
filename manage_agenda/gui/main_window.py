"""The main window: a sidebar of screens, the log panel, the status bar with Cancel, and
the slot that turns the worker's UI requests into dialogs."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QWidget,
)

from manage_agenda.gui import dialogs
from manage_agenda.gui.bridge import Bridge, UIRequest
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.gui.log_panel import LogPanel
from manage_agenda.gui.persist import gui_settings
from manage_agenda.gui.screens.accounts import AccountsScreen
from manage_agenda.gui.screens.add import AddScreen
from manage_agenda.gui.screens.auth import AuthScreen
from manage_agenda.gui.screens.calendar_ops import CalendarOpsScreen
from manage_agenda.gui.screens.evaluate import EvaluateScreen
from manage_agenda.gui.screens.install import InstallScreen
from manage_agenda.gui.screens.ledger import LedgerScreen
from manage_agenda.gui.screens.lists import ListsScreen
from manage_agenda.gui.screens.settings import SettingsScreen
from manage_agenda.i18n import t

SCREEN_CLASSES = (
    AddScreen,
    CalendarOpsScreen,
    LedgerScreen,
    EvaluateScreen,
    AuthScreen,
    ListsScreen,
    InstallScreen,
    AccountsScreen,
    SettingsScreen,
)

CLOSE_WAIT_MS = 5000
NAV_ROW_HEIGHT = 34
LOG_DOCK_HEIGHT = 170


def _scrollable(screen):
    """The screen in a scroll area: a window too short for the page scrolls it instead of
    squeezing its widgets against the log panel."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.viewport().setAutoFillBackground(False)
    area.setWidget(screen)
    return area


class MainWindow(QMainWindow):
    def __init__(self, verbose=False, parent=None):
        super().__init__(parent)
        self.verbose = verbose
        self.setWindowTitle(t("gui.window_title"))
        self.resize(1100, 760)

        self.bridge = Bridge(self)
        self.runner = JobRunner(self.bridge, self)
        self._active_dialog: QDialog | None = None

        self.log_panel = LogPanel(self)
        self.log_dock = QDockWidget(t("gui.log_panel_title"), self)
        self.log_dock.setObjectName("logDock")  # saveState() needs a name
        self.log_dock.setWidget(self.log_panel)
        self.log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.resizeDocks([self.log_dock], [LOG_DOCK_HEIGHT], Qt.Orientation.Vertical)
        self.log_action = self.log_dock.toggleViewAction()
        self.log_action.setShortcut("Ctrl+L")
        self.menuBar().addMenu(t("gui.menu.view")).addAction(self.log_action)

        self.nav = QListWidget(self)
        self.nav.setObjectName("nav")  # styled by gui/theme.py
        self.nav.setFixedWidth(210)
        self.nav.setSpacing(1)
        self.stack = QStackedWidget(self)
        self.screens = []
        for screen_class in SCREEN_CLASSES:
            screen = screen_class(self.runner, self)
            self.screens.append(screen)
            item = QListWidgetItem(screen.title())
            # The theme pads the rows; the row height has to follow (a stylesheet's padding
            # does not reach the item's size hint).
            item.setSizeHint(QSize(0, NAV_ROW_HEIGHT))
            self.nav.addItem(item)
            self.stack.addWidget(_scrollable(screen))
        central = QWidget(self)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.status_label = QLabel("", self)
        self.cancel_button = QPushButton(t("gui.cancel"), self)
        self.cancel_button.setToolTip(t("gui.cancel_tooltip"))
        self.cancel_button.setEnabled(False)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.cancel_button)

        self.bridge.request_ready.connect(self._on_ui_request, Qt.ConnectionType.QueuedConnection)
        self.bridge.echo_line.connect(self.log_panel.append_line, Qt.ConnectionType.QueuedConnection)
        self.bridge.log_record.connect(
            self.log_panel.append_record, Qt.ConnectionType.QueuedConnection
        )
        self.runner.started.connect(self._on_job_started)
        self.runner.finished.connect(self._on_job_finished)
        self.runner.failed.connect(self._on_job_failed)
        self.runner.cancelled.connect(self._on_job_cancelled)
        self.cancel_button.clicked.connect(self.cancel_job)
        self.nav.currentRowChanged.connect(self._show_screen)
        self.nav.setCurrentRow(0)
        self.restore_window_state()

    def show_screen(self, screen_class):
        """Select `screen_class` in the sidebar (which shows and refreshes it)."""
        self.nav.setCurrentRow(self.screens.index(self.screen(screen_class)))

    # --- window geometry and the log panel, kept between sessions ---

    def restore_window_state(self):
        settings = gui_settings()
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value("state")
        if state is not None:
            self.restoreState(state)

    def save_window_state(self):
        settings = gui_settings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState())
        settings.sync()

    def _show_screen(self, row):
        if 0 <= row < len(self.screens):
            self.stack.setCurrentIndex(row)
            self.screens[row].refresh()

    def screen(self, screen_class):
        """The instance of `screen_class`, for tests and shortcuts."""
        for screen in self.screens:
            if isinstance(screen, screen_class):
                return screen
        raise KeyError(screen_class.__name__)

    # --- prompts from the worker ---

    @Slot(object)
    def _on_ui_request(self, request: UIRequest):
        if request.cancelled or request.done.is_set():
            return
        dialog = dialogs.build(request, self)
        self._active_dialog = dialog
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                request.answer(dialog.value())
            else:
                request.cancel()
        finally:
            self._active_dialog = None
            dialog.deleteLater()

    # --- job state ---

    def cancel_job(self):
        self.runner.cancel()
        if self._active_dialog is not None:
            self._active_dialog.reject()

    def _on_job_started(self, name):
        self.status_label.setText(t("gui.job_started", name=name))
        self.cancel_button.setEnabled(True)
        self.log_panel.append_line(f"=== {name} ===")

    def _on_job_finished(self, result):
        self.cancel_button.setEnabled(False)
        if isinstance(result, int) and not isinstance(result, bool) and result != 0:
            self.status_label.setText(t("gui.job_finished_with_code", code=result))
        else:
            self.status_label.setText(t("gui.job_finished"))

    def _on_job_failed(self, summary, trace):
        self.cancel_button.setEnabled(False)
        self.status_label.setText(t("gui.job_failed", error=summary))
        self.log_panel.append_line(trace)
        box = QMessageBox(QMessageBox.Icon.Critical, t("gui.job_failed_title"), summary, parent=self)
        box.setDetailedText(trace)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    def _on_job_cancelled(self):
        self.cancel_button.setEnabled(False)
        self.status_label.setText(t("gui.job_cancelled"))

    def closeEvent(self, event):
        if self.runner.is_busy():
            answer = QMessageBox.question(
                self,
                t("gui.window_title"),
                t("gui.close_while_running"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.cancel_job()
            if not self.runner.wait(CLOSE_WAIT_MS):
                # The worker is inside a call that cannot be interrupted (a model request,
                # a mailbox fetch, the browser consent). Destroying the window would destroy
                # the live QThread, which Qt treats as fatal - so the window stays open;
                # closing again once the call has returned works.
                self.status_label.setText(t("gui.close_job_still_running"))
                self.log_panel.append_line(t("gui.close_job_still_running"))
                event.ignore()
                return
        self.save_window_state()
        event.accept()
