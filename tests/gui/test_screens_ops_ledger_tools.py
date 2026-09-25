"""Calendar operations, Ledger, Evaluate and Install screens: the Args each builds and the
core function each submits."""

from unittest.mock import patch

from manage_agenda.gui.bridge import Bridge
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.gui.screens import calendar_ops, evaluate, install, ledger
from manage_agenda.sources import Args


def _submitted(screen, module, name):
    """Run the screen's action with `module.name` patched; (positional args, kwargs)."""
    with patch.object(module, name) as func:
        screen.run()
        return func


def test_calendar_ops_args_and_destination_enablement(qapp, pump):
    runner = JobRunner(Bridge())
    screen = calendar_ops.CalendarOpsScreen(runner)
    assert screen.operation.currentData() == "copy"
    assert screen.destination.isEnabled()
    assert screen.build_args() == Args(interactive=True)

    screen.source.setText(" cal-src ")
    screen.destination.setText("cal-dst")
    screen.text.setText("meeting")
    assert screen.build_args() == Args(interactive=True, source="cal-src", destination="cal-dst", text="meeting")

    screen.operation.setCurrentIndex(2)  # delete: no destination
    assert not screen.destination.isEnabled()
    assert screen.build_args() == Args(interactive=True, source="cal-src", text="meeting")


def test_calendar_ops_submits_the_operations_function(qapp, pump):
    runner = JobRunner(Bridge())
    screen = calendar_ops.CalendarOpsScreen(runner)
    calls = []

    def recorder(name):
        return lambda args: calls.append((name, args))

    fake = tuple((name, recorder(name), needs) for name, _func, needs in calendar_ops.OPERATIONS)
    with patch.object(calendar_ops, "OPERATIONS", fake):
        for index in range(len(fake)):
            screen.operation.setCurrentIndex(index)
            screen.run()
            assert pump(lambda: not runner.is_busy())
    assert [name for name, _args in calls] == ["copy", "move", "delete", "clean", "update-status"]
    assert all(args.interactive for _name, args in calls)


def test_ledger_maintenance_args_and_functions(qapp, pump):
    runner = JobRunner(Bridge())
    with patch.object(ledger, "restorable_identities", return_value={}):
        screen = ledger.LedgerScreen(runner)
        screen.refresh()
    assert screen.build_args() == Args(interactive=False, dry_run_ledger=True)
    screen.dry_run.setChecked(False)
    screen.choose_account.setChecked(True)
    assert screen.build_args() == Args(interactive=True, dry_run_ledger=False)

    with patch.object(ledger, "reconcile_ledger_cli", return_value=5) as reconcile:
        screen.reconcile_button.click()
        assert pump(lambda: not runner.is_busy())
    reconcile.assert_called_once_with(Args(interactive=True, dry_run_ledger=False))
    with patch.object(ledger, "migrate_ledger_cli", return_value=0) as migrate:
        screen.migrate_button.click()
        assert pump(lambda: not runner.is_busy())
    migrate.assert_called_once()


def test_ledger_restore_table_and_run(qapp, pump):
    runner = JobRunner(Bridge())
    found = {"msg-a": ["e1", "e2"], "msg-b": ["e3"]}
    with patch.object(ledger, "restorable_identities", return_value=found):
        screen = ledger.LedgerScreen(runner)
        screen.refresh()
    assert screen.table.rowCount() == 2
    assert screen.table.item(0, 1).text() == "e1, e2"
    assert screen.restore_empty.text() == ""

    screen.restore()  # nothing selected
    assert not runner.is_busy() and screen.restore_empty.text()

    screen.table.selectRow(1)
    with patch.object(ledger, "restore_deleted_event_cli", return_value=True) as restore:
        screen.restore()
        assert pump(lambda: not runner.is_busy())
    restore.assert_called_once_with(Args(interactive=False), "msg-b")

    with patch.object(ledger, "restorable_identities", return_value={}):
        screen.refresh()
    assert screen.table.rowCount() == 0 and screen.restore_empty.text()


def test_evaluate_args_prompt_and_type(qapp, pump):
    runner = JobRunner(Bridge())
    screen = evaluate.EvaluateScreen(runner)
    assert screen.evaluation() == (None, "txt")
    assert screen.build_args() == Args(interactive=False, output="file")
    assert not screen.prompt.isEnabled() and screen.prompt.isHidden()
    screen.type.setCurrentText("prompt")
    assert screen.prompt.isEnabled() and not screen.prompt.isHidden()
    screen.prompt.setPlainText(" hello ")
    screen.output.setCurrentText("calendar")
    assert screen.evaluation() == ("hello", None)
    with patch.object(evaluate, "evaluate_models") as models:
        screen.run()
        assert pump(lambda: not runner.is_busy())
    models.assert_called_once_with(Args(interactive=False, output="calendar"), prompt="hello", eval_type=None)


def test_install_submits_the_chosen_browser(qapp, pump):
    runner = JobRunner(Bridge())
    screen = install.InstallScreen(runner)
    screen.browser.setCurrentText("chromium")
    with patch.object(install, "install_playwright_browser", return_value=0) as installer:
        screen.run()
        assert pump(lambda: not runner.is_busy())
    installer.assert_called_once_with("chromium")


def test_enter_in_a_calendar_ops_field_runs(qapp, pump):
    runner = JobRunner(Bridge())
    screen = calendar_ops.CalendarOpsScreen(runner)
    calls = []
    fake = tuple((name, lambda args: calls.append(args), needs) for name, _func, needs in calendar_ops.OPERATIONS)
    with patch.object(calendar_ops, "OPERATIONS", fake):
        screen.text.setText("x")
        screen.text.returnPressed.emit()
        assert pump(lambda: not runner.is_busy())
    assert len(calls) == 1 and calls[0].text == "x"
