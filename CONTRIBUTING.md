# Contributing to manage-agenda

Thank you for your interest in contributing to manage-agenda! This document provides guidelines and instructions for contributing.

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/fernand0/manage-agenda.git
   cd manage-agenda
   ```

2. **Install dependencies**
   ```bash
   # Using uv (recommended)
   uv sync --dev
   
   # Or using pip
   pip install -e '.[dev]'
   ```

3. **Install pre-commit hooks**
   ```bash
   pre-commit install
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

## Code Quality Standards

### Linting and import sorting
- **Ruff**: linter, and import sorting through its `I` rules (line length: 100). It is the
  only code-style tool: the pre-commit hook and the CI `lint` job run the same `ruff check`,
  at the version pinned in `uv.lock`.
- Run: `ruff check . --fix`
- Install the hook once: `pre-commit install`

### Security
- **Bandit**: Security issue scanner
- Run: `bandit -r manage_agenda/`

### Pre-commit
All checks run automatically on commit. To run manually:
```bash
pre-commit run --all-files
```

## Testing

### Running Tests
```bash
# All tests
pytest

# With coverage
pytest --cov=manage_agenda --cov-report=html

# Specific test file
pytest tests/test_sources.py

# Specific test
pytest tests/test_sources.py::test_function_name
```

### Writing Tests
- Place tests in the `tests/` directory
- Name test files `test_*.py`
- Name test functions `test_*`
- Use fixtures for common setup
- Mock external API calls

## Making Changes

### Branch Naming
- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation only
- `refactor/description` - Code refactoring

### Commit Messages
Follow conventional commits:
```
type(scope): description

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Example:
```
feat(calendar): add support for recurring events

- Added recurrence pattern parsing
- Updated event validation
- Added tests for recurring events

Closes #123
```

### Pull Request Process

1. **Update your branch**
   ```bash
   git checkout devel
   git pull origin devel
   git checkout your-branch
   git rebase devel
   ```

2. **Run all checks**
   ```bash
   pre-commit run --all-files
   pytest
   ```

3. **Create PR**
   - Target the `devel` branch
   - Provide clear description
   - Reference related issues
   - Add tests for new features
   - Update documentation if needed

## Code Style Guidelines

### Python Code
- Follow PEP 8 (enforced by Black/Ruff)
- Maximum line length: 100 characters
- Use type hints for function signatures
- Document public functions with docstrings

### Docstrings
Use Google style:
```python
def function_name(param1: str, param2: int) -> bool:
    """Brief description.
    
    Longer description if needed.
    
    Args:
        param1: Description of param1.
        param2: Description of param2.
        
    Returns:
        Description of return value.
        
    Raises:
        ValueError: When invalid input is provided.
    """
    pass
```

### Error Handling
- Use custom exceptions from `exceptions.py`
- Log errors appropriately
- Provide helpful error messages
- Don't catch generic `Exception` unless necessary

## Project Structure

```
manage-agenda/
├── manage_agenda/          # Main package
│   ├── __init__.py
│   ├── cli.py             # CLI commands
│   ├── config.py          # Configuration management
│   ├── exceptions.py      # Custom exceptions
│   ├── base.py            # Base utilities
│   ├── connections.py     # External-service connections
│   ├── evaluation.py      # LLM evaluation workflows
│   ├── events.py          # Calendar event operations
│   ├── extraction.py      # LLM event extraction
│   ├── i18n.py            # t(): interface language resolution
│   ├── interactive.py     # questionary lists (console only, see "The UI port")
│   ├── llm.py             # LLM provider clients and selection
│   ├── messages.py        # en/fr message catalogue
│   ├── scheduling.py      # Availability and room-visit planning
│   ├── sources.py         # Source ingestion workflows
│   ├── ui/                # The UI port (see below)
│   │   ├── __init__.py    # UI protocol, get_ui()/set_ui()/use_ui(), echo()
│   │   ├── console.py     # ConsoleUI: the terminal implementation
│   │   └── fake.py        # ScriptedUI: answers from a queue, for tests
│   ├── user_config.py     # config.yaml (saved provider/model/calendars)
│   └── web.py             # Web scraping
├── tests/                 # Test suite
├── .env.example          # Environment template
├── .pre-commit-config.yaml
├── pyproject.toml        # Project configuration
└── README.md
```

A new subpackage must be added to `[tool.setuptools] packages` in `pyproject.toml`: the
list is explicit, and a package left out of it is silently missing from the non-editable
install CI uses.

## The UI port

Library code (everything under `manage_agenda/` except `cli.py`) never reads the terminal
or writes to stdout directly. Every question goes through the current UI object, and every
line shown to the user goes through `echo`:

```python
from manage_agenda.ui import echo, get_ui

if get_ui().confirm(t("sources.confirm_remove_label")):
    ...
chosen = get_ui().choose_one(options, title=t("..."), identifier="summary")
echo(t("extraction.calendar_event_created"))
```

`manage_agenda.ui.UI` lists the prompt kinds (`choose_one`, `choose_many`, `choose_action`,
`confirm`, `ask_text`, `ask_multiline`, `review_event`, `select_events`, `echo`).
`ConsoleUI`, the default, reproduces the classic terminal behaviour, so the CLI does not
change; a GUI answers the same questions with dialogs. Any implementation may raise
`manage_agenda.exceptions.UserCancelled` (a `BaseException`, like `KeyboardInterrupt`) when
the user backs out - never catch it in library code.

Rules, enforced by `tests/test_no_stdin_in_library.py` (an AST walk over the package):

- no `input()`, `click.prompt()`, `click.confirm()`, socialModules' `select_from_list()` or
  `rules.selectRuleInteractive()` outside `manage_agenda/ui/console.py`;
- no import of `manage_agenda.interactive` outside `manage_agenda/ui/console.py`; library
  code uses `manage_agenda.ui.select_one` / `select_many`, which dispatch to the current UI;
- no `questionary` outside `interactive.py`.

In tests, install a `ScriptedUI` with the answers the flow will ask for, then assert on what
it asked:

```python
from manage_agenda.ui import use_ui
from manage_agenda.ui.fake import ScriptedUI

with use_ui(ScriptedUI([("confirm", True), ("choose_one", 0)])) as ui:
    process_something(args)
assert [call.kind for call in ui.calls] == ["confirm", "choose_one"]
```

pytest-style tests can take the `scripted_ui` fixture instead (it also checks every queued
answer was consumed). `ScriptedUI(lenient=True)` answers unqueued prompts with a neutral
default (first option, nothing, no) for tests that do not care about the prompts.

## Getting Help

- Open an issue for bugs or feature requests
- Check existing issues and PRs first
- For questions, use GitHub Discussions

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
