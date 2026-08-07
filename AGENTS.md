# Repository Guidelines

## Project Structure & Module Organization

`app.py` is the PyQt6 entry point. AI orchestration lives in `Agent/CustomerAgent/`, with framework code under `custom/` and callable tools under `tools/`. Platform integrations belong in `Channel/`; Pinduoduo separates connection logic in `core/` from HTTP wrappers in `utils/API/`. Message queues and handlers are in `Message/`, while `bridge/` connects channel events to replies. Shared services, persistence, widgets, and helpers live in `core/`, `service/`, `database/`, `ui/`, and `utils/`. Keep tests in `tests/`, icons in `icon/`, and packaging files in `scripts/`.

## Build, Test, and Development Commands

- `uv sync`: create or update the Python 3.11+ environment from `uv.lock`.
- `uv run python app.py`: launch the desktop application locally.
- `uv run python -m unittest discover -s tests -v`: run the complete regression suite.
- `uv run python -m unittest tests.test_regressions.ConfigRegressionTests`: run one test class.
- `python scripts/build_win_exe.py --clean`: build the Windows onedir package and Inno Setup installer. Use `--skip-installer` when only the PyInstaller output is needed.

## Coding Style & Naming Conventions

Use four-space indentation and standard Python conventions: `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Add type hints to public interfaces and keep async I/O explicitly `async`/`await`. Preserve the existing package boundaries instead of placing channel-specific logic in shared modules. No formatter or linter is configured, so keep imports grouped, docstrings concise, and changes focused.

## Testing Guidelines

Tests use the standard-library `unittest` framework, including `IsolatedAsyncioTestCase` for asynchronous behavior and `unittest.mock` for external services. Name files `test_*.py` and methods `test_<behavior>`. Add regression coverage for identity scoping, configuration persistence, database migrations, message routing, and API response parsing. Tests must not require live marketplace or LLM credentials.

## Commit & Pull Request Guidelines

History follows subjects such as `fix(login): ...`, `feat(packaging): ...`, and `docs(readme): ...`; concise Chinese subjects also occur. Prefer an imperative, scoped subject and keep each commit focused. Pull requests should explain user-visible behavior, list verification commands, link relevant issues, and include screenshots for UI changes. Call out Windows-only validation or untested platform assumptions.

## Security & Configuration

Never commit `config.json`, API keys, cookies, account data, `user_data/`, or `temp/`. Validate marketplace response fields against an actual or recorded response before changing parsers. Preserve secret protection and account-scoping behavior when touching configuration, login, or database code.

# Superpowers
- Follow instructions in .codex/COMMANDS.md when present
- See .codex/ for additional agent configuration and shortcuts
