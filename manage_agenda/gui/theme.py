"""The window's look: the Fusion style and a small stylesheet derived from the palette, so it
follows the platform's light or dark colours instead of hardcoding either. Applied by
app.run() only - create_window() stays style-free for the tests.

The stylesheet touches a deliberately small set of selectors (the sidebar, group boxes,
the primary buttons, the labels with a `role`, table headers, the status bar): a partial
stylesheet on a combo box or a spin box breaks their arrows and popups under Fusion.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette


def is_dark(palette):
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def accent_color(palette):
    """The platform accent (Qt >= 6.6), or the selection colour when there is none."""
    role = getattr(QPalette.ColorRole, "Accent", None)
    color = palette.color(role) if role is not None else None
    if color is None or not color.isValid():
        color = palette.color(QPalette.ColorRole.Highlight)
    return color


def _rgba(color, alpha):
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def stylesheet(palette):
    """The stylesheet for `palette`."""
    dark = is_dark(palette)
    accent = accent_color(palette)
    on_accent = palette.color(QPalette.ColorRole.HighlightedText).name()
    window = palette.color(QPalette.ColorRole.Window).name()
    border = palette.color(QPalette.ColorRole.Mid).name()
    muted = palette.color(QPalette.ColorRole.PlaceholderText).name()
    error = "#f2b8b5" if dark else "#b3261e"
    ok = "#8fd19e" if dark else "#1b6e3a"
    return f"""
QListWidget#nav {{
    background: {window};
    border: none;
    outline: 0;
    padding: 6px 4px;
}}
QListWidget#nav::item {{
    padding: 0 12px;
    margin: 0 2px;
    border-radius: 6px;
}}
QListWidget#nav::item:hover {{
    background: {_rgba(accent, 0.15)};
}}
QListWidget#nav::item:selected {{
    background: {accent.name()};
    color: {on_accent};
}}
QLabel#screenTitle {{
    font-size: 17pt;
    font-weight: 600;
}}
QLabel[role="hint"] {{
    color: {muted};
}}
QLabel[role="error"] {{
    color: {error};
}}
QLabel[role="ok"] {{
    color: {ok};
}}
QGroupBox {{
    border: 1px solid {border};
    border-radius: 6px;
    margin-top: 14px;
    padding: 12px 8px 6px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {accent.name()};
}}
QGroupBox[folded="true"] {{
    border: none;
    padding: 0 8px;
}}
QPushButton[primary="true"] {{
    background: {accent.name()};
    color: {on_accent};
    border: 1px solid {accent.darker(115).name()};
    border-radius: 4px;
    padding: 5px 14px;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background: {accent.lighter(110).name()};
}}
QPushButton[primary="true"]:pressed {{
    background: {accent.darker(115).name()};
}}
QPushButton[primary="true"]:disabled {{
    background: {border};
    color: {muted};
    border-color: {border};
}}
QHeaderView::section {{
    background: {window};
    padding: 4px 6px;
    border: none;
    border-bottom: 1px solid {border};
    font-weight: 600;
}}
QTableWidget {{
    gridline-color: {border};
}}
QDockWidget::title {{
    padding: 4px 8px;
    background: {window};
}}
QStatusBar {{
    border-top: 1px solid {border};
}}
QStatusBar::item {{
    border: none;
}}
"""


def apply_theme(app):
    """Fusion plus the stylesheet for the application's palette; the style installed."""
    style = app.setStyle("Fusion")
    app.setStyleSheet(stylesheet(app.palette()))
    return style
