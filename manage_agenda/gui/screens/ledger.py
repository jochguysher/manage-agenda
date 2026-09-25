"""Ledger: reconcile, migrate-ledger and restore, with their exit codes."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import hint_label, primary
from manage_agenda.i18n import t
from manage_agenda.sources import (
    Args,
    migrate_ledger_cli,
    reconcile_ledger_cli,
    restorable_identities,
    restore_deleted_event_cli,
)


class LedgerScreen(Screen):
    nav_key = "gui.nav.ledger"
    subtitle_key = "gui.ledger.subtitle"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        layout = self.content

        maintenance = QGroupBox(t("gui.ledger.maintenance"), self)
        maintenance_layout = QVBoxLayout(maintenance)
        self.dry_run = QCheckBox(t("gui.ledger.dry_run"), self)
        self.dry_run.setChecked(True)
        self.choose_account = QCheckBox(t("gui.ledger.choose_account"), self)
        maintenance_layout.addWidget(self.dry_run)
        maintenance_layout.addWidget(self.choose_account)
        row = QHBoxLayout()
        self.reconcile_button = self.register_run_button(primary(QPushButton(t("gui.ledger.reconcile"), self)))
        self.migrate_button = self.register_run_button(QPushButton(t("gui.ledger.migrate"), self))
        row.addWidget(self.reconcile_button)
        row.addWidget(self.migrate_button)
        row.addStretch(1)
        maintenance_layout.addLayout(row)
        maintenance_layout.addWidget(hint_label(t("gui.ledger.exit_code_note"), self))
        layout.addWidget(maintenance)

        restore = QGroupBox(t("gui.ledger.restore"), self)
        restore_layout = QVBoxLayout(restore)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(
            [t("gui.ledger.column_identity"), t("gui.ledger.column_events")]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        restore_layout.addWidget(self.table)
        self.restore_empty = QLabel("", self)
        restore_layout.addWidget(self.restore_empty)
        restore_row = QHBoxLayout()
        self.reload_button = QPushButton(t("gui.ledger.restore_list"), self)
        self.restore_button = self.register_run_button(QPushButton(t("gui.ledger.restore_run"), self))
        restore_row.addWidget(self.reload_button)
        restore_row.addWidget(self.restore_button)
        restore_row.addStretch(1)
        restore_layout.addLayout(restore_row)
        layout.addWidget(restore)
        layout.addStretch(1)

        self.reconcile_button.clicked.connect(lambda: self._maintain(reconcile_ledger_cli, "reconcile"))
        self.migrate_button.clicked.connect(lambda: self._maintain(migrate_ledger_cli, "migrate-ledger"))
        self.reload_button.clicked.connect(self.refresh)
        self.restore_button.clicked.connect(self.restore)

    def refresh(self):
        found = restorable_identities()
        self.identities = list(found)
        self.table.setRowCount(len(found))
        for row, (identity, event_ids) in enumerate(found.items()):
            self.table.setItem(row, 0, QTableWidgetItem(identity))
            self.table.setItem(row, 1, QTableWidgetItem(", ".join(event_ids)))
        self.restore_empty.setText("" if found else t("sources.restore_list_empty"))

    def build_args(self):
        """The Args `manage-agenda reconcile|migrate-ledger [-i] [--dry-run-ledger]` builds."""
        return Args(interactive=self.choose_account.isChecked(), dry_run_ledger=self.dry_run.isChecked())

    def _maintain(self, func, name):
        self.submit(t("gui.ledger.job", command=name), func, self.build_args())

    def selected_identity(self):
        row = self.table.currentRow()
        return self.identities[row] if 0 <= row < len(getattr(self, "identities", [])) else None

    def restore(self):
        identity = self.selected_identity()
        if identity is None:
            self.restore_empty.setText(t("gui.ledger.restore_select_one"))
            return
        self.submit(
            t("gui.ledger.job", command="restore"),
            restore_deleted_event_cli,
            Args(interactive=False),
            identity,
        )
