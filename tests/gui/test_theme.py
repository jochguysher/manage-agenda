"""gui/theme.py: the stylesheet follows the palette (light or dark) and apply_theme() installs
Fusion plus that stylesheet on the application."""

from PySide6.QtGui import QColor, QPalette

from manage_agenda.gui import theme


def _palette(window, text):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    return palette


def test_stylesheet_follows_the_palette(qapp):
    light = theme.stylesheet(_palette("#ffffff", "#000000"))
    dark = theme.stylesheet(_palette("#202020", "#ffffff"))
    for sheet in (light, dark):
        assert "QListWidget#nav" in sheet and 'QPushButton[primary="true"]' in sheet
        assert 'QLabel[role="hint"]' in sheet and "QLabel#screenTitle" in sheet
    assert not theme.is_dark(_palette("#ffffff", "#000000"))
    assert theme.is_dark(_palette("#202020", "#ffffff"))
    assert light != dark
    assert theme.accent_color(QPalette()).isValid()


def test_apply_theme_installs_fusion_and_the_stylesheet(qapp):
    previous_sheet = qapp.styleSheet()
    try:
        # app.style() is the stylesheet proxy once a stylesheet is set: check what was
        # installed through the style setStyle() returned instead.
        style = theme.apply_theme(qapp)
        assert style is not None and style.objectName().lower() == "fusion"
        assert "QListWidget#nav" in qapp.styleSheet()
    finally:
        qapp.setStyleSheet(previous_sheet)
