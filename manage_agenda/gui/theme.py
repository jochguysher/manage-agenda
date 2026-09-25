"""The window's look: the Fusion style, one of two explicit palettes (light, dark) or the
platform's own, and a small stylesheet derived from the palette in force. The theme is a
choice of the user (View › Theme, kept in gui.ini), not of the desktop: the same window
looks the same on every machine unless "system" is chosen. Applied by app.run() and by the
Theme menu only - create_window() stays style-free for the tests.

The stylesheet touches a deliberately small set of selectors (the sidebar, group boxes,
the primary buttons, the labels with a `role`, table headers, the status bar): a partial
stylesheet on a combo box or a spin box breaks their arrows and popups under Fusion. The
accent is spent on two things only, the selected sidebar entry and the primary button, so
the main action of a screen is the first thing the eye finds.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

THEMES = ("light", "dark", "system")
DEFAULT_THEME = "system"

# Both palettes cover every role Fusion reads, plus the disabled group (which Fusion would
# otherwise derive, unevenly, from the active one) and the Accent role (Qt >= 6.6).
LIGHT = {
    "window": "#f2f2f2",
    "window_text": "#1e1f22",
    "base": "#ffffff",
    "alternate_base": "#f5f6f7",
    "text": "#1e1f22",
    "button": "#e7e8ea",
    "button_text": "#1e1f22",
    "bright_text": "#d0021b",
    "highlight": "#2f7fd6",
    "highlighted_text": "#ffffff",
    "tooltip_base": "#fffbe6",
    "tooltip_text": "#1e1f22",
    "placeholder_text": "#8b9096",
    "link": "#1f63b8",
    "light": "#ffffff",
    "midlight": "#e1e2e4",
    "mid": "#c6c8cc",
    "dark": "#9a9da3",
    "shadow": "#6b6e74",
    "disabled_text": "#9a9da3",
    "disabled_highlight": "#c6c8cc",
    "hint": "#5c6168",
    "error": "#b3261e",
    "ok": "#1b6e3a",
}

DARK = {
    "window": "#2b2e33",
    "window_text": "#eaecee",
    "base": "#1f2124",
    "alternate_base": "#26292d",
    "text": "#eaecee",
    "button": "#383c42",
    "button_text": "#eaecee",
    "bright_text": "#ff6b6b",
    "highlight": "#3d9be9",
    "highlighted_text": "#ffffff",
    "tooltip_base": "#3a3e45",
    "tooltip_text": "#eaecee",
    "placeholder_text": "#8e949c",
    "link": "#6cb4ee",
    "light": "#4d525a",
    "midlight": "#3d4249",
    "mid": "#4a4f57",
    "dark": "#1a1c1f",
    "shadow": "#101214",
    "disabled_text": "#7a8088",
    "disabled_highlight": "#4a4f57",
    "hint": "#a3a8ae",
    "error": "#f2b8b5",
    "ok": "#8fd19e",
}

_ROLES = {
    "window": QPalette.ColorRole.Window,
    "window_text": QPalette.ColorRole.WindowText,
    "base": QPalette.ColorRole.Base,
    "alternate_base": QPalette.ColorRole.AlternateBase,
    "text": QPalette.ColorRole.Text,
    "button": QPalette.ColorRole.Button,
    "button_text": QPalette.ColorRole.ButtonText,
    "bright_text": QPalette.ColorRole.BrightText,
    "highlight": QPalette.ColorRole.Highlight,
    "highlighted_text": QPalette.ColorRole.HighlightedText,
    "tooltip_base": QPalette.ColorRole.ToolTipBase,
    "tooltip_text": QPalette.ColorRole.ToolTipText,
    "placeholder_text": QPalette.ColorRole.PlaceholderText,
    "link": QPalette.ColorRole.Link,
    "light": QPalette.ColorRole.Light,
    "midlight": QPalette.ColorRole.Midlight,
    "mid": QPalette.ColorRole.Mid,
    "dark": QPalette.ColorRole.Dark,
    "shadow": QPalette.ColorRole.Shadow,
}

_system_palette: QPalette | None = None
_current_mode = DEFAULT_THEME
_custom_palette_set = False
_following: set = set()  # ids of the applications whose colorSchemeChanged is connected


def make_palette(spec):
    """A QPalette from a colour spec (LIGHT or DARK)."""
    palette = QPalette()
    for key, role in _ROLES.items():
        palette.setColor(role, QColor(spec[key]))
    accent = getattr(QPalette.ColorRole, "Accent", None)
    if accent is not None:
        palette.setColor(accent, QColor(spec["highlight"]))
    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(disabled, role, QColor(spec["disabled_text"]))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor(spec["disabled_highlight"]))
    palette.setColor(disabled, QPalette.ColorRole.HighlightedText, QColor(spec["disabled_text"]))
    return palette


def is_dark(palette):
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def accent_color(palette):
    """The palette's accent (Qt >= 6.6), or its selection colour when there is none."""
    role = getattr(QPalette.ColorRole, "Accent", None)
    color = palette.color(role) if role is not None else None
    if color is None or not color.isValid():
        color = palette.color(QPalette.ColorRole.Highlight)
    return color


def system_palette(app):
    """The palette the platform gave the application, as it was before any theme of ours:
    captured on the first call, so "system" can be chosen back after "light" or "dark"."""
    global _system_palette
    if _system_palette is None:
        _system_palette = QPalette(app.palette())
    return _system_palette


def palette_for(mode, app=None):
    """The palette of theme `mode` ("light", "dark" or "system"); `app` is needed for
    "system". An unknown mode is the default one."""
    if mode == "light":
        return make_palette(LIGHT)
    if mode == "dark":
        return make_palette(DARK)
    return system_palette(app)


def _rgba(color, alpha):
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def stylesheet(palette):
    """The stylesheet for `palette`. The role colours (hint, error, ok) are constants of the
    light or the dark family, chosen for their contrast on that family's window colour -
    the platform's placeholder colour, which used to give `hint`, is often too faint."""
    family = DARK if is_dark(palette) else LIGHT
    accent = accent_color(palette)
    on_accent = palette.color(QPalette.ColorRole.HighlightedText).name()
    window = palette.color(QPalette.ColorRole.Window).name()
    border = palette.color(QPalette.ColorRole.Mid).name()
    text = palette.color(QPalette.ColorRole.WindowText).name()
    hint, error, ok = family["hint"], family["error"], family["ok"]
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
    color: {hint};
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
    color: {text};
    font-weight: 600;
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
    color: {hint};
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


def current_mode():
    return _current_mode


def apply_theme(app, mode=DEFAULT_THEME):
    """Fusion, the palette of theme `mode` and the stylesheet for it, on the application;
    the style installed. Safe to call again with another mode: the widgets are repolished.

    "system" leaves the platform's palette in place as long as no palette of ours was ever
    set, so a desktop switching between light and dark is followed live (see
    follow_system()); once "light" or "dark" was applied, going back to "system" restores
    the palette captured at startup."""
    global _current_mode, _custom_palette_set
    style = app.setStyle("Fusion")
    system_palette(app)  # captured before our first palette replaces it
    _current_mode = mode if mode in THEMES else DEFAULT_THEME
    if _current_mode == "system" and not _custom_palette_set:
        palette = app.palette()
    else:
        palette = palette_for(_current_mode, app)
        app.setPalette(palette)
        _custom_palette_set = _custom_palette_set or _current_mode != "system"
    app.setStyleSheet(stylesheet(palette))
    follow_system(app)
    return style


def follow_system(app):
    """Recompute the stylesheet when the desktop changes its colour scheme and the theme is
    "system": the palette Qt propagates changed, the stylesheet derived from it must too."""
    hints = app.styleHints()
    if id(app) in _following or not hasattr(hints, "colorSchemeChanged"):
        return
    hints.colorSchemeChanged.connect(lambda _scheme: on_system_scheme_changed(app))
    _following.add(id(app))


def on_system_scheme_changed(app):
    global _system_palette
    if _current_mode != "system":
        return
    if not _custom_palette_set:
        _system_palette = QPalette(app.palette())
    app.setStyleSheet(stylesheet(app.palette()))
