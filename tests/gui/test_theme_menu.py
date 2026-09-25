"""View › Theme: the chosen theme is applied to the application at once and kept in gui.ini,
and app.run() would start with it (persist.saved_theme)."""

from PySide6.QtGui import QPalette

from manage_agenda.gui import theme
from manage_agenda.gui.main_window import MainWindow
from manage_agenda.gui.persist import gui_settings, save_theme, saved_theme


def _restore(qapp, palette, sheet):
    qapp.setPalette(palette)
    qapp.setStyleSheet(sheet)


def test_saved_theme_defaults_and_rejects_unknown_values(qapp):
    assert saved_theme() == "system"
    save_theme("dark")
    assert saved_theme() == "dark"
    gui_settings().setValue("appearance/theme", "neon")
    assert saved_theme() == "system"


def test_theme_menu_applies_and_remembers_the_choice(qapp):
    previous_palette, previous_sheet = QPalette(qapp.palette()), qapp.styleSheet()
    save_theme("light")
    window = MainWindow()
    try:
        assert set(window.theme_actions) == set(theme.THEMES)
        assert window.theme_actions["light"].isChecked()
        assert window.theme_group.isExclusive()

        window.theme_actions["dark"].trigger()
        assert saved_theme() == "dark" and window.theme_actions["dark"].isChecked()
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == theme.DARK["window"]
        assert theme.DARK["hint"] in qapp.styleSheet()

        window.choose_theme("light")
        assert saved_theme() == "light" and window.theme_actions["light"].isChecked()
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == theme.LIGHT["window"]
        assert not window.theme_actions["dark"].isChecked()
    finally:
        window.close()
        _restore(qapp, previous_palette, previous_sheet)
