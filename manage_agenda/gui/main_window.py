"""The main window: a sidebar of screens, the log panel, the status bar with Cancel, and
the slot that turns the worker's UI requests into dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from manage_agenda.gui import dialogs
from manage_agenda.gui.bridge import Bridge, UIRequest
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.gui.log_panel import LogPanel
from manage_agenda.gui.screens.auth import AuthScreen
from manage_agenda.gui.screens.lists import ListsScreen
from manage_agenda.i18n import t

SCREEN_CLASSES = (ListsScreen, AuthScreen)

CLOSE_WAIT_MS = 5000


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
        dock = QDockWidget(t("gui.log_panel_title"), self)
        dock.setWidget(self.log_panel)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        self.nav = QListWidget(self)
        self.nav.setMaximumWidth(220)
        self.stack = QStackedWidget(self)
        self.screens = []
        for screen_class in SCREEN_CLASSES:
            screen = screen_class(self.runner, self)
            self.screens.append(screen)
            self.nav.addItem(screen.title())
            self.stack.addWidget(screen)
        central = QWidget(self)
        layout = QHBoxLayout(central)
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
                self.log_panel.append_line(t("gui.close_job_still_running"))
        event.accept()
