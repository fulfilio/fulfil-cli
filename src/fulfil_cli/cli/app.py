"""Root CLI application with dynamic model and report subcommands.

Typer handles the root app and static commands (auth, config, version)
where type-driven argument parsing shines. Click groups are used for
dynamic model and report routing because Typer does not support runtime
subcommand creation via ``get_command`` overrides — the ``FulfilGroup``
and ``ReportGroup`` classes intercept unknown subcommand names and
resolve them as Fulfil model or report names respectively.
"""

from __future__ import annotations

import typer
import typer.core
import typer.main
from rich.console import Console

from fulfil_cli import __version__
from fulfil_cli.cli import state
from fulfil_cli.cli.commands import auth, config
from fulfil_cli.cli.commands.api import api_cmd
from fulfil_cli.cli.commands.common import handle_error
from fulfil_cli.cli.commands.completion import completion_install
from fulfil_cli.cli.commands.model import create_model_group
from fulfil_cli.cli.commands.report import create_report_group
from fulfil_cli.cli.state import VALID_FORMATS, AppContext, format_option
from fulfil_cli.client.errors import EXIT_USAGE, FulfilError
from fulfil_cli.output.formatter import output

console = Console(stderr=True)


class ReportGroup(typer.core.TyperGroup):
    """Typer group that resolves unknown subcommands as report names."""

    def get_command(self, ctx: typer.Context, cmd_name: str):
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        return typer.main.get_command(create_report_group(cmd_name))


class FulfilGroup(typer.core.TyperGroup):
    """Custom Typer group that resolves unknown subcommands as model or report names."""

    _dynamic_commands = ("models", "reports")

    def list_commands(self, ctx: typer.Context) -> list[str]:
        commands = super().list_commands(ctx)
        for name in self._dynamic_commands:
            if name not in commands:
                commands.append(name)
        return commands

    def get_command(self, ctx: typer.Context, cmd_name: str):
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        if cmd_name == "models":
            return typer.main.get_command(models_group)
        if cmd_name == "reports":
            return typer.main.get_command(reports_group)
        return typer.main.get_command(create_model_group(cmd_name))


app = typer.Typer(
    cls=FulfilGroup,
    name="fulfil",
    help=(
        "The Fulfil CLI — interact with the Fulfil ERP platform from the command line.\n\n"
        "Any Fulfil model name (e.g. sales_order, product, customer_shipment) is a valid\n"
        "subcommand. Each model supports: list, get, create, update, delete, count, call,\n"
        "and describe.\n\n"
        "Examples:\n\n"
        "  # List confirmed sales orders\n"
        '  fulfil sales_order list --where \'{"state": "confirmed"}\'\n\n'
        "  # Get a specific product by ID\n"
        "  fulfil product get 42\n\n"
        "  # Create a new contact\n"
        '  fulfil contact create --data \'{"name": "Acme Corp"}\'\n\n'
        "  # Count open shipments\n"
        '  fulfil customer_shipment count --where \'{"state": "waiting"}\'\n\n'
        "  # Send a raw JSON-RPC call\n"
        '  fulfil api \'{"method": "system.version", "params": {}}\'\n\n'
        "  # Search documentation\n"
        '  fulfil docs "how to create sales orders"\n\n'
        "  # List available models\n"
        "  fulfil models"
    ),
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Static command groups
app.add_typer(auth.app, name="auth")
app.add_typer(config.app, name="config")


@app.callback()
def main_callback(
    ctx: typer.Context,
    token: str | None = typer.Option(None, "--token", envvar="FULFIL_API_KEY", help="API key"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        envvar="FULFIL_WORKSPACE",
        help="Workspace domain (e.g. acme.fulfil.io)",
    ),
    base_url: str | None = typer.Option(None, "--base-url", hidden=True, help="Override base URL"),
    debug: bool = typer.Option(False, "--debug", help="Show debug output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress hints and decorative output"),
    output_format: str | None = typer.Option(
        None,
        "--format",
        help="Output format: table, json, csv, ndjson (default: table for TTY, json when piped)",
    ),
) -> None:
    """Root callback — sets global auth state."""
    if output_format and output_format not in VALID_FORMATS:
        console.print(
            f"[red]Error: Invalid format '{output_format}'. "
            f"Choose from: {', '.join(VALID_FORMATS)}[/red]"
        )
        raise typer.Exit(code=EXIT_USAGE)
    ctx.obj = AppContext(
        token=token,
        workspace=workspace,
        base_url=base_url,
        debug=debug,
        quiet=quiet,
        output_format=output_format,
    )
    state._set_current(ctx.obj)


FORMAT_OPTION = typer.Option(
    None,
    "--format",
    help="Output format: table, json, csv, ndjson",
)


@app.command()
def version(
    ctx: typer.Context,
    output_format: str | None = FORMAT_OPTION,
) -> None:
    """Show CLI version."""
    app_ctx: AppContext = ctx.obj
    fmt = app_ctx.get_effective_format(output_format)
    if fmt == "table":
        typer.echo(f"fulfil-cli {__version__}")
    else:
        output({"version": __version__}, fmt=fmt)


@app.command()
def whoami(
    ctx: typer.Context,
    output_format: str | None = FORMAT_OPTION,
) -> None:
    """Show current user and workspace info."""
    app_ctx: AppContext = ctx.obj
    try:
        client = app_ctx.get_client()
        result = client.call("system.whoami")
    except FulfilError as exc:
        handle_error(exc)

    output(result, fmt=app_ctx.get_effective_format(output_format))


def _flatten_model_row(row: dict) -> dict:
    """Pick key columns and flatten access dict for table display."""
    access = row.get("access", {})
    return {
        "model": row.get("model_name", ""),
        "description": row.get("description", ""),
        "category": row.get("category", ""),
        "read": access.get("read", False),
        "create": access.get("create", False),
        "update": access.get("update", False),
        "delete": access.get("delete", False),
    }


def _list_models(fmt: str, search: str | None = None) -> None:
    """Fetch and display all available models."""
    app_ctx: AppContext = state._get_current()
    try:
        client = app_ctx.get_client()
        result = client.call("system.list_models")
    except FulfilError as exc:
        handle_error(exc)

    if search and isinstance(result, list):
        term = search.lower()
        result = [
            r
            for r in result
            if isinstance(r, dict)
            and (
                term in r.get("model_name", "").lower()
                or term in r.get("description", "").lower()
                or term in r.get("category", "").lower()
            )
        ]

    if fmt == "table" and isinstance(result, list):
        result = [_flatten_model_row(r) for r in result if isinstance(r, dict)]

    output(result, fmt=fmt, title="Available Models")


models_group = typer.Typer(name="models", help="List available models.")


@models_group.callback(invoke_without_command=True)
def _models_callback(
    ctx: typer.Context,
    search: str | None = typer.Option(
        None, "--search", "-s", help="Filter by name, description, or category."
    ),
    output_format: str | None = format_option,
) -> None:
    """List all available models."""
    if ctx.invoked_subcommand is None:
        app_ctx: AppContext = ctx.obj
        _list_models(app_ctx.get_effective_format(output_format), search=search)


@models_group.command("list")
def models_list_cmd(
    ctx: typer.Context,
    search: str | None = typer.Option(
        None, "--search", "-s", help="Filter by name, description, or category."
    ),
    output_format: str | None = format_option,
) -> None:
    """List all available models."""
    app_ctx: AppContext = ctx.obj
    _list_models(app_ctx.get_effective_format(output_format), search=search)


def _list_reports(fmt: str) -> None:
    """Fetch and display all available reports."""
    app_ctx: AppContext = state._get_current()
    try:
        client = app_ctx.get_client()
        result = client.call("system.list_reports")
    except FulfilError as exc:
        handle_error(exc)

    output(result, fmt=fmt, title="Available Reports")


reports_group = typer.Typer(
    name="reports",
    cls=ReportGroup,
    help="Interact with reports.",
)


@reports_group.callback(invoke_without_command=True)
def _reports_callback(
    ctx: typer.Context,
    output_format: str | None = format_option,
) -> None:
    """List all available reports."""
    if ctx.invoked_subcommand is None:
        app_ctx: AppContext = ctx.obj
        _list_reports(app_ctx.get_effective_format(output_format))


@reports_group.command("list")
def reports_list_cmd(
    ctx: typer.Context,
    output_format: str | None = format_option,
) -> None:
    """List all available reports."""
    app_ctx: AppContext = ctx.obj
    _list_reports(app_ctx.get_effective_format(output_format))


@app.command()
def docs(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query for Fulfil documentation"),
    output_format: str | None = FORMAT_OPTION,
) -> None:
    """Search Fulfil documentation."""
    app_ctx: AppContext = ctx.obj
    try:
        client = app_ctx.get_client()
        results = client.call("system.search_docs", query=query)
    except FulfilError as exc:
        handle_error(exc)

    if not results:
        if not app_ctx.quiet:
            console.print("[dim]No results found.[/dim]")
        raise typer.Exit()

    fmt = app_ctx.get_effective_format(output_format)
    if fmt != "table":
        output(results, fmt=fmt)
    else:
        from rich.markdown import Markdown
        from rich.panel import Panel

        out = Console()
        for doc in results:
            title = doc.get("title", "Untitled")
            url = doc.get("url", "")
            content = doc.get("content", "").strip()
            out.print(Panel(Markdown(content), title=title, subtitle=url, expand=True))


@app.command(name="getting-started")
def getting_started() -> None:
    """Show a quick-start guide for using the CLI."""
    from rich.markdown import Markdown

    guide = """\
# Getting Started with Fulfil CLI

## 1. Authenticate

```
fulfil auth login
```

This prompts for your workspace domain and API key, then stores
credentials in your system keyring.

For scripts and CI, use environment variables instead:

```
export FULFIL_API_KEY=sk_live_...
export FULFIL_WORKSPACE=acme.fulfil.io
```

## 2. Explore your data

```
fulfil models                          # list all models
fulfil models --search shipment        # search for models
fulfil sales_order describe            # see fields and endpoints
```

## 3. Query records

```
fulfil sales_order list --fields reference,state,total_amount
fulfil sales_order list --where '{"state": "confirmed"}'
fulfil sales_order count
fulfil sales_order get 42
```

## 4. Create and update records

```
echo '{"name": "Acme Corp"}' | fulfil contact create
fulfil sales_order update 42 updates.json
```

## 5. Call workflow methods

Don't update state fields directly — use workflow methods:

```
fulfil sales_order call confirm --ids 1,2,3
fulfil sales_order call process --ids 42
```

## 6. Reports

```
fulfil reports                                    # list reports
fulfil reports price_list_report describe          # see parameters
fulfil reports price_list_report execute --params '{"date_from": "2024-01-01"}'
```

## Tips

- Use `--format json` to force JSON output (automatic when piped)
- Use `--format csv` or `--format ndjson` for other machine-readable formats
- Use `--debug` to see HTTP request/response details
- Use `-h` on any command for help: `fulfil sales_order list -h`
- Run `fulfil completion` to install shell completions
"""
    Console().print(Markdown(guide))


# Register standalone commands
app.command(name="api")(api_cmd)
app.command(name="completion")(completion_install)

# Top-level aliases for frequently-used auth subcommands
app.command(name="workspaces")(auth.workspaces)
