# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development

This project uses `uv` for dependency management and builds.

```bash
# Install dependencies
uv sync --dev

# Run all tests
pytest

# Run a single test file
pytest tests/test_client/test_http.py

# Run a single test
pytest tests/test_client/test_http.py::test_name -v

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Auto-fix lint issues
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
```

## Architecture

The CLI is built with **Typer** (on top of Click) and communicates with the Fulfil ERP platform via **JSON-RPC 2.0**.

**Package structure** (`src/fulfil_cli/`):

- **`cli/`** — CLI layer. `app.py` defines the root Typer app with a custom `FulfilGroup` that dynamically resolves any unknown subcommand as a model name (e.g., `fulfil sales_order list`) via `create_model_group()`. Static subcommands: `auth`, `config`, `api`, `completion`, `whoami`, `models`, `version`. The `report` subcommand similarly resolves report names dynamically.
- **`client/`** — `FulfilClient` in `http.py` handles JSON-RPC requests (single and batch). `errors.py` defines the error hierarchy (`FulfilError` base with `AuthError`, `NetworkError`, `ServerError`, etc.), each with an exit code.
- **`auth/`** — API key resolution (`api_key.py`) with priority: CLI flag → env var → keyring. Keyring storage in `keyring_store.py`.
- **`config/`** — TOML config management via `ConfigManager`. Uses `platformdirs` for XDG-compliant paths.
- **`output/`** — Output formatting: `formatter.py` routes to JSON (`orjson`), CSV, NDJSON, or Rich tables based on `--format` flag / TTY detection.
- **`cli/state.py`** — `AppContext` dataclass stored on Click's `ctx.obj`. Holds auth credentials, output format, and a lazily-constructed `FulfilClient`.

**Key pattern**: The `FulfilGroup.get_command()` override is the central routing mechanism — it checks static commands first, then intercepts `report` as a special group, and finally treats any other name as a Fulfil model.

## Code Style

- Ruff with rules: E, F, I, N, W, UP (pyupgrade)
- Line length: 100
- Target: Python 3.11+
- Entry point: `fulfil = "fulfil_cli.cli:main"`
