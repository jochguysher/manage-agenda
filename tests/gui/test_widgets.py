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


def test_form_layout_grows_every_non_fixed_field(qapp):
    from PySide6.QtWidgets import QFormLayout

    from manage_agenda.gui.widgets import form_layout

    assert form_layout().fieldGrowthPolicy() == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow


def test_fit_columns_caps_the_content_columns_and_stretches_the_last(qapp):
    from PySide6.QtWidgets import QHeaderView, QTableWidget

    from manage_agenda.gui.widgets import MAX_COLUMN_WIDTH, cell, fit_columns

    table = QTableWidget(1, 3)
    table.resize(500, 100)
    path = "/very/long/path/" + "x" * 300 + ".json"
    for column, text in enumerate(("a", path, path)):
        table.setItem(0, column, cell(text))
    fit_columns(table)
    assert table.columnWidth(0) < 60
    assert table.columnWidth(1) == MAX_COLUMN_WIDTH
    assert table.horizontalHeader().sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch
    assert table.item(0, 2).toolTip() == path
    assert not table.item(0, 2).flags() & Qt.ItemFlag.ItemIsEditable


def test_collapsible_box_hides_its_body_until_toggled(qapp):
    from PySide6.QtWidgets import QLabel

    from manage_agenda.gui.widgets import CollapsibleBox

    box = CollapsibleBox("More")
    inner = QLabel("x", box.body)
    box.show()
    assert box.isCheckable() and not box.isChecked() and box.body.isHidden()
    assert box.property("folded") is True
    box.setChecked(True)
    assert not box.body.isHidden() and inner.isVisible()
    assert box.property("folded") is False
    box.setChecked(False)
    assert box.body.isHidden() and box.property("folded") is True
