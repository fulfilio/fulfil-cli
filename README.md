# Fulfil CLI

The command-line interface for [Fulfil](https://fulfil.io) — query data, manage records, run reports, and automate workflows from the terminal.

## Install

```bash
# Recommended: install with uv (https://docs.astral.sh/uv/)
uv tool install fulfil-cli

# Or with pipx
pipx install fulfil-cli
```

> **Don't have uv or pipx?** Install uv first — it's a single command:
> `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or
> `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
> Then run `uv tool install fulfil-cli`.

## Getting Started

```bash
# 1. Log in to your Fulfil workspace
fulfil auth login

# 2. List sales orders
fulfil sales_order list --fields reference,state,total_amount

# 3. Count products
fulfil product count

# 4. Look up a contact
fulfil contact list --where '{"name": "Acme Corp"}' --fields name,email
```

## Authentication

The CLI stores your API key in the system keyring (macOS Keychain, GNOME Keyring, Windows Credential Locker).

```bash
# Interactive — prompts for workspace and API key
fulfil auth login

# Non-interactive
fulfil auth login --workspace acme.fulfil.io --api-key sk_live_...

# Check current auth
fulfil auth status

# List all configured workspaces
fulfil workspaces

# Switch workspace
fulfil auth use other-workspace.fulfil.io

# Log out
fulfil auth logout
```

**Environment variables** (useful for CI/scripts):

```bash
export FULFIL_API_KEY=sk_live_...
export FULFIL_WORKSPACE=acme.fulfil.io
```

Priority: `--token` flag > `FULFIL_API_KEY` env var > system keyring.

## Working with Records

Any Fulfil model name is a valid command. Each model supports: `list`, `get`, `create`, `update`, `delete`, `count`, `call`, and `describe`.

### Listing records

```bash
# List with specific fields
fulfil sales_order list --fields reference,state,total_amount

# Filter with MongoDB-style queries
fulfil sales_order list --where '{"state": "confirmed"}'
fulfil sales_order list --where '{"sale_date": {"gte": "2025-01-01"}}'
fulfil sales_order list --where '{"or": [{"state": "draft"}, {"state": "confirmed"}]}'

# Sort results
fulfil sales_order list --order sale_date:desc
fulfil sales_order list --order sale_date:desc,reference:asc

# Control page size
fulfil sales_order list --limit 50

# Paginate — the CLI prints the full command for the next page
fulfil sales_order list --cursor <token-from-previous-response>
```

**Available filter operators:** `gt`, `gte`, `lt`, `lte`, `ne`, `in`, `not_in`, `contains`, `startswith`, `endswith`.

### Getting records by ID

```bash
fulfil sales_order get 42
fulfil sales_order get 1,2,3
```

### Creating records

```bash
# Single record (from stdin)
echo '{"name": "Acme Corp"}' | fulfil contact create

# Record with nested lines (e.g. contact with addresses)
echo '{"name": "Acme Corp", "addresses": [{"street": "100 Broadway", "city": "New York"}, {"street": "45 Industrial Pkwy", "city": "Newark"}]}' | fulfil contact create

# Multiple records at once (preferred — never loop single creates)
echo '[{"name": "Alice"}, {"name": "Bob"}]' | fulfil contact create

# From a file
fulfil contact create data.json
```

### Updating records

```bash
echo '{"comment": "Approved by finance"}' | fulfil sales_order update 42
```

### Deleting records

```bash
fulfil sales_order delete 42         # asks for confirmation
fulfil sales_order delete 42 --yes   # skip confirmation
```

### Counting records

```bash
fulfil product count
fulfil sales_order count --where '{"state": "draft"}'
```

### Calling custom methods

```bash
fulfil sales_order call confirm --ids 1,2,3
fulfil sales_order call process --ids 42
```

### Exploring models

```bash
# List all models you have access to
fulfil models

# Search for models by name
fulfil models --search shipment

# See fields and endpoints for a model
fulfil sales_order describe
fulfil sales_order describe confirm
```

## Reports

```bash
# List available reports
fulfil reports

# Run a report with parameters
fulfil reports price_list_report execute --params '{"date_from": "2024-01-01"}'

# Interactive — prompts for each parameter
fulfil reports price_list_report execute -i

# See what parameters a report accepts
fulfil reports price_list_report describe
```

## Raw JSON-RPC

For full control, send raw JSON-RPC requests:

```bash
fulfil api '{"method": "system.version", "params": {}}'

# Pipe from stdin
echo '{"method": "model.product.count", "params": {}}' | fulfil api -
```

## Output

| Context | Format |
|---|---|
| Terminal | Rich tables with colors |
| Piped / redirected / CI | JSON (automatic) |
| `--format` flag | table, json, csv, or ndjson |

```bash
# Force JSON and pipe to jq
fulfil sales_order list --fields reference,state --format json | jq '.data[].reference'

# Force format via env var
FULFIL_FORMAT=json fulfil sales_order list

# CSV output
fulfil sales_order list --fields reference,state --format csv
```

## Python Library

The same models, filters and login are available from Python, for scripts that do more than one command can:

```python
from fulfil_cli import Workspace

with Workspace("acme.fulfil.io") as ws:
    # find() follows pagination and returns every match (or the first `limit`)
    orders = ws["sales_order"].find(
        {"state": "confirmed", "sale_date": {"gte": "2025-01-01"}},
        fields=["reference", "party.name", "total_amount"],
        order="sale_date:desc",
    )
    for product in ws["product"].iter(fields="code,name"):  # lazy, page by page
        ...

    ws["sales_order"].get(42, fields="reference,state")      # one id -> dict, list -> list
    ws["contact"].count({"active": True})
    ws["contact"].create([{"name": "Alice"}, {"name": "Bob"}])  # one call for many records
    ws["contact"].update([1, 2], {"comment": "Reviewed"})
    ws["sales_order"].call("confirm", ids=[1, 2, 3])
    ws["sales_order"].describe()
```

- The workspace is always explicit. `Workspace` never falls back to the CLI's default workspace.
- Credentials resolve as in the CLI: `token=` > `FULFIL_API_KEY` > the login stored by `fulfil auth login` for that workspace (OAuth tokens refresh automatically).
- Errors raise the same exceptions the CLI maps to exit codes (`fulfil_cli.FulfilError` and its subclasses in `fulfil_cli.client.errors`).

For a one-off script, declare the dependency inline and run it with `uv run script.py`:

```python
# /// script
# dependencies = ["fulfil-cli>=0.5.0"]
# ///
```

## Configuration

```bash
fulfil config set key value
fulfil config get key
fulfil config list
```

Config file location: `~/.config/fulfil/config.toml`

## Global Options

```
--token TEXT        API key (overrides env and keyring)
--workspace TEXT    Workspace domain (e.g. acme.fulfil.io)
--debug            Show HTTP request/response details
--quiet, -q        Suppress hints and decorative output
--format TEXT      Output format: table, json, csv, ndjson
-h, --help         Show help
```

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `2` | Bad arguments |
| `3` | Configuration error |
| `4` | Authentication error |
| `5` | Not found |
| `6` | Forbidden |
| `7` | Validation error |
| `8` | Rate limited |
| `9` | Server error |
| `10` | Network error |

## Shell Completion

```bash
fulfil completion   # auto-detects zsh/bash/fish
```

## AI Agent Integration

The CLI is designed for programmatic use:

- **JSON output by default** when stdout is piped or redirected (override with `--format` or `FULFIL_FORMAT`)
- **Structured exit codes** for error handling
- **Errors on stderr**, data on stdout — safe to parse stdout directly
- **Environment variable auth** — no interactive prompts: `FULFIL_API_KEY` + `FULFIL_WORKSPACE`

See [AGENTS.md](AGENTS.md) for the full agent guide.

## Development

```bash
git clone https://github.com/fulfilio/fulfil-cli.git
cd fulfil-cli
uv sync --dev
pytest
uv run ruff check .
uv run pre-commit install
```
