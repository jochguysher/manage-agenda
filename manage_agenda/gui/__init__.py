"""The desktop window (PySide6), an optional extra: `pip install 'manage-agenda[gui]'`.

Nothing here is imported by the CLI until `manage-agenda gui` runs, and this file imports
nothing itself, so `import manage_agenda.gui` never fails at test collection - only
`manage_agenda.gui.app` needs PySide6.
"""
