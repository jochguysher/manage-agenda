"""gui/theme.py: two explicit palettes, a stylesheet that follows the palette it is given, and
apply_theme(app, mode) installing Fusion plus the palette and stylesheet of `mode` - without
ever depending on the palette of the machine the tests run on."""

from PySide6.QtGui import QColor, QPalette

from manage_agenda.gui import theme


def _palette(window, text):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    return palette


def test_the_two_palettes_cover_every_role_and_the_disabled_group(qapp):
    light, dark = theme.make_palette(theme.LIGHT), theme.make_palette(theme.DARK)
    assert not theme.is_dark(light) and theme.is_dark(dark)
    for palette, spec in ((light, theme.LIGHT), (dark, theme.DARK)):
        assert palette.color(QPalette.ColorRole.Window).name() == spec["window"]
        assert palette.color(QPalette.ColorRole.AlternateBase).name() == spec["alternate_base"]
        assert palette.color(QPalette.ColorRole.ToolTipBase).name() == spec["tooltip_base"]
        assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == spec["disabled_text"]
        assert theme.accent_color(palette).name() == spec["highlight"]
    assert theme.palette_for("light").color(QPalette.ColorRole.Window).name() == theme.LIGHT["window"]
    assert theme.palette_for("dark").color(QPalette.ColorRole.Window).name() == theme.DARK["window"]


def test_stylesheet_follows_the_palette_with_fixed_role_colours(qapp):
    light = theme.stylesheet(_palette("#ffffff", "#000000"))
    dark = theme.stylesheet(_palette("#202020", "#ffffff"))
    for sheet in (light, dark):
        assert "QListWidget#nav" in sheet and 'QPushButton[primary="true"]' in sheet
        assert 'QLabel[role="hint"]' in sheet and "QLabel#screenTitle" in sheet
        assert 'QGroupBox[folded="true"]' in sheet
    assert theme.LIGHT["hint"] in light and theme.LIGHT["error"] in light and theme.LIGHT["ok"] in light
    assert theme.DARK["hint"] in dark and theme.DARK["error"] in dark and theme.DARK["ok"] in dark
    assert light != dark
    assert theme.accent_color(QPalette()).isValid()


def test_apply_theme_installs_fusion_the_palette_and_the_stylesheet(qapp):
    previous_palette, previous_sheet = QPalette(qapp.palette()), qapp.styleSheet()
    try:
        # app.style() is the stylesheet proxy once a stylesheet is set: check what was
        # installed through the style setStyle() returned instead.
        style = theme.apply_theme(qapp, "dark")
        assert style is not None and style.objectName().lower() == "fusion"
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == theme.DARK["window"]
        assert "QListWidget#nav" in qapp.styleSheet() and theme.DARK["hint"] in qapp.styleSheet()

        theme.apply_theme(qapp, "light")
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == theme.LIGHT["window"]
        assert theme.LIGHT["hint"] in qapp.styleSheet()

        # "system" is the palette captured before the first theme of ours.
        theme.apply_theme(qapp, "system")
        assert qapp.palette().color(QPalette.ColorRole.Window) == theme.system_palette(qapp).color(
            QPalette.ColorRole.Window
        )
        assert theme.palette_for("nonsense", qapp) is theme.system_palette(qapp)
    finally:
        qapp.setPalette(previous_palette)
        qapp.setStyleSheet(previous_sheet)


def test_system_theme_follows_a_desktop_scheme_change(qapp):
    previous_palette, previous_sheet = QPalette(qapp.palette()), qapp.styleSheet()
    try:
        theme.apply_theme(qapp, "system")
        assert theme.current_mode() == "system"
        qapp.setStyleSheet("")
        theme.on_system_scheme_changed(qapp)
        assert "QListWidget#nav" in qapp.styleSheet()  # recomputed from the live palette

        theme.apply_theme(qapp, "dark")
        qapp.setStyleSheet("")
        theme.on_system_scheme_changed(qapp)
        assert qapp.styleSheet() == ""  # not "system": the desktop is ignored
    finally:
        qapp.setPalette(previous_palette)
        qapp.setStyleSheet(previous_sheet)
