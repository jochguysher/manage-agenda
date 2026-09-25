"""gui/widgets.py: the elided label keeps its full text but never dictates its width."""

from PySide6.QtCore import Qt

from manage_agenda.gui.widgets import ELIDED_MIN_CHARS, ElidedLabel


def test_elided_label_keeps_the_text_and_tooltip_but_not_the_width(qapp):
    text = "x" * 400
    label = ElidedLabel(text)
    assert label.text() == text and label.toolTip() == text
    metrics = label.fontMetrics()
    assert label.sizeHint().width() <= metrics.averageCharWidth() * ELIDED_MIN_CHARS
    assert label.sizeHint().width() < metrics.horizontalAdvance(text)
    label.resize(120, label.sizeHint().height())
    shown = label.elided_text()
    assert shown != text and "…" in shown and len(shown) < len(text)
    label.setText("short")
    assert label.toolTip() == "short" and label.elided_text() == "short"
    assert label.mode == Qt.TextElideMode.ElideMiddle
