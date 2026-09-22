"""Evaluate: `manage-agenda llm evaluate` - every installed Ollama model against a prompt
or a source workflow; the comparison goes to the log panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from manage_agenda.evaluation import evaluate_models
from manage_agenda.gui.screens.base import Screen
from manage_agenda.i18n import t
from manage_agenda.sources import Args

TYPES = ("txt", "email", "web", "prompt")
OUTPUTS = ("file", "calendar")


class EvaluateScreen(Screen):
    nav_key = "gui.nav.evaluate"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.type = QComboBox(self)
        self.type.addItems(TYPES)
        self.output = QComboBox(self)
        self.output.addItems(OUTPUTS)
        self.prompt = QPlainTextEdit(self)
        self.prompt.setPlaceholderText(t("gui.evaluate.prompt_placeholder"))
        form.addRow(t("gui.evaluate.type"), self.type)
        form.addRow(t("gui.evaluate.output"), self.output)
        form.addRow(t("gui.evaluate.prompt"), self.prompt)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.run_button = self.register_run_button(QPushButton(t("gui.evaluate.run"), self))
        row.addWidget(self.run_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.type.currentTextChanged.connect(lambda kind: self.prompt.setEnabled(kind == "prompt"))
        self.prompt.setEnabled(False)
        self.run_button.clicked.connect(self.run)

    def build_args(self):
        return Args(interactive=False, output=self.output.currentText())

    def evaluation(self):
        """(prompt, eval_type) as cli.py's `llm evaluate` derives them."""
        if self.type.currentText() == "prompt":
            return self.prompt.toPlainText().strip() or None, None
        return None, self.type.currentText()

    def run(self):
        prompt, eval_type = self.evaluation()
        self.submit(
            t("gui.evaluate.job"), evaluate_models, self.build_args(), prompt=prompt, eval_type=eval_type
        )
