"""The UI port is enforced, not just documented: no library module reads the terminal.

Walks the AST of every module under manage_agenda/ (a GUI subpackage included, once there
is one) except the console implementation itself, and fails on anything that would block a
GUI process on stdin or bypass the port: input(), click.prompt/confirm, socialModules'
select_from_list or rules.selectRuleInteractive, questionary, and any import of
manage_agenda.interactive (the console-only selection helpers). An AST walk rather than a
grep: docstrings and comments legitimately mention these names."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "manage_agenda"

# The console implementation (and the helpers only it uses) may read stdin; the message
# catalogue only holds strings.
EXEMPT = {"ui/console.py", "interactive.py", "messages.py"}

FORBIDDEN_NAME_CALLS = {"input", "select_from_list"}
FORBIDDEN_ATTRIBUTE_CALLS = {"selectRuleInteractive"}
FORBIDDEN_CLICK_CALLS = {"prompt", "confirm"}
FORBIDDEN_MODULES = {"questionary", "manage_agenda.interactive"}


def _violations(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAME_CALLS:
                found.append((node.lineno, f"{func.id}()"))
            elif isinstance(func, ast.Attribute):
                if func.attr in FORBIDDEN_ATTRIBUTE_CALLS:
                    found.append((node.lineno, f".{func.attr}()"))
                if (
                    func.attr in FORBIDDEN_CLICK_CALLS
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "click"
                ):
                    found.append((node.lineno, f"click.{func.attr}()"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_MODULES:
                    found.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = {alias.name for alias in node.names}
            if module in FORBIDDEN_MODULES:
                found.append((node.lineno, f"from {module} import ..."))
            if module == "manage_agenda" and "interactive" in names:
                found.append((node.lineno, "from manage_agenda import interactive"))
            if module == "socialModules.configMod" and "select_from_list" in names:
                found.append((node.lineno, "from socialModules.configMod import select_from_list"))
    return found


def test_no_library_module_reads_the_terminal_or_bypasses_the_ui_port():
    violations = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).as_posix()
        if relative in EXEMPT:
            continue
        found = _violations(path)
        if found:
            violations[relative] = found
    assert violations == {}, (
        "terminal prompts outside the console UI (route them through manage_agenda.ui.get_ui()):"
        f" {violations}"
    )


def test_the_guard_itself_catches_each_forbidden_form(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import questionary\n"
        "from manage_agenda.interactive import select_one\n"
        "from manage_agenda import interactive\n"
        "from socialModules.configMod import select_from_list\n"
        "def f(rules):\n"
        "    input('x')\n"
        "    click.prompt('x')\n"
        "    click.confirm('x')\n"
        "    select_from_list([])\n"
        "    rules.selectRuleInteractive('gmail')\n"
        "    other.prompt('fine: not click')\n",
        encoding="utf-8",
    )
    kinds = [what for _line, what in _violations(sample)]
    assert kinds == [
        "import questionary",
        "from manage_agenda.interactive import ...",
        "from manage_agenda import interactive",
        "from socialModules.configMod import select_from_list",
        "input()",
        "click.prompt()",
        "click.confirm()",
        "select_from_list()",
        ".selectRuleInteractive()",
    ]
