# Fulfil CLI — Agent Guide

The Fulfil CLI (`fulfil`) is a command-line tool for the [Fulfil](https://fulfil.io) ERP platform. It communicates via JSON-RPC 2.0 with the Fulfil v3 API.

## Setup

```bash
# Install
uv tool install fulfil-cli

# Authenticate (non-interactive)
export FULFIL_API_KEY=sk_live_...
export FULFIL_WORKSPACE=acme.fulfil.io

# Verify
fulfil whoami --format json
```

## Key Rules for Agents

- **Always use `--format json`** for structured output (auto-enabled when stdout is not a TTY)
- **Use env vars** for auth: `FULFIL_API_KEY`, `FULFIL_WORKSPACE` — no interactive prompts
- **Set `FULFIL_FORMAT=json`** to force JSON even when stdout is a TTY
- **Errors go to stderr**, data to stdout — safe to parse stdout directly
- **Exit codes** are structured: 0=ok, 2=usage, 3=config, 4=auth, 5=not-found, 6=forbidden, 7=validation, 8=rate-limit, 9=server, 10=network
- **Never update state/status fields directly** — use workflow methods (`call confirm`, `call process`, etc.)
- **Batch creates, not loops** — pass a JSON array to create multiple records in one call: `echo '[{...}, {...}]' | fulfil contact create`. Never loop single creates.

## Command Reference

### Records (any model name is a valid command)

```bash
# List with filters, sorting, pagination
fulfil sales_order list --where '{"state": "confirmed"}' --fields reference,state --order sale_date:desc --limit 50 --format json

# Get by ID
fulfil sales_order get 42 --format json
fulfil sales_order get 1,2,3 --format json

# Create (single or batch, data from stdin)
echo '{"name": "Acme Corp"}' | fulfil contact create --format json
echo '[{"name": "Alice"}, {"name": "Bob"}]' | fulfil contact create --format json

# Create with nested records
echo '{"name": "Acme Corp", "addresses": [{"street": "100 Broadway", "city": "New York"}]}' | fulfil contact create --format json

# Create from a file
fulfil contact create data.json --format json

# Update data fields (not state — use call for workflow transitions)
echo '{"comment": "Approved by finance"}' | fulfil sales_order update 42 --format json

# Delete (requires --yes in non-interactive mode)
fulfil sales_order delete 42 --yes

# Count
fulfil sales_order count --where '{"state": "draft"}' --format json

# Call workflow methods
fulfil sales_order call confirm --ids 1,2,3 --format json
fulfil sales_order call process --ids 42 --format json

# Describe model fields and endpoints
fulfil sales_order describe --format json
```

### Filter Operators

`gt`, `gte`, `lt`, `lte`, `ne`, `in`, `not_in`, `contains`, `startswith`, `endswith`

```bash
fulfil sales_order list --where '{"sale_date": {"gte": "2025-01-01"}}' --format json
fulfil sales_order list --where '{"or": [{"state": "draft"}, {"state": "confirmed"}]}' --format json
```

### Pagination

The `list` command returns a pagination envelope:

```json
{"data": [...], "pagination": {"has_more": true, "next_cursor": "abc123"}}
```

Use the cursor for the next page:

```bash
fulfil sales_order list --cursor abc123 --format json
```

### Discovery

```bash
# List all models
fulfil models --format json

# Search models
fulfil models --search shipment --format json

# List reports
fulfil reports --format json

# Describe a report's parameters
fulfil reports price_list_report describe --format json
```

### Python

For multi-step scripts, use the library instead of shelling out to the CLI. Same models, `where` syntax, dotted fields and credentials:

```python
from fulfil_cli import Workspace

# The workspace is always explicit, never the default one.
with Workspace("acme.fulfil.io") as ws:
    # find() follows pagination and returns every match.
    rows = ws["task"].find({"state": "open"}, fields="name,owner.name", order="due_date")
    # Batch creates in one call; never loop.
    ws["task"].create([{...}, {...}])
    ws["task"].call("done", ids=[1, 2])
```

### Other Commands

```bash
# Raw JSON-RPC
fulfil api '{"method": "system.version", "params": {}}' --format json

# Auth
fulfil whoami --format json
fulfil auth status
fulfil workspaces

# Version
fulfil version --format json
```
