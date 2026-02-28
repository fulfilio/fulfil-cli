"""Root CLI application with dynamic model subcommands."""

from __future__ import annotations

import click
import typer
import typer.core
from rich.console import Console

from fulfil_cli import __version__
from fulfil_cli.cli.commands import auth, config
from fulfil_cli.cli.commands.api import api_cmd
from fulfil_cli.cli.commands.completion import completion_install
from fulfil_cli.cli.commands.model import create_model_group
from fulfil_cli.cli.commands.report import create_report_group
from fulfil_cli.cli.state import get_client, is_quiet, set_globals
from fulfil_cli.client.errors import FulfilError
from fulfil_cli.output.formatter import output

console = Console(stderr=True)


def _handle_error(exc: FulfilError) -> None:
    """Print error and exit with appropriate code."""
    console.print(f"[red]Error: {exc}[/red]")
    if exc.hint and not is_quiet():
        console.print(f"[dim]Hint: {exc.hint}[/dim]")
    raise typer.Exit(code=exc.exit_code)


class ReportGroup(click.Group):
    """Click group that resolves unknown subcommands as report names."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        return create_report_group(cmd_name)


class FulfilGroup(typer.core.TyperGroup):
    """Custom Click group that resolves unknown subcommands as model or report names."""

    # Dynamic commands that should appear in help alongside static ones
    _dynamic_commands = ("models", "reports")

    def list_commands(self, ctx: click.Context) -> list[str]:
        commands = super().list_commands(ctx)
        for name in self._dynamic_commands:
            if name not in commands:
                commands.append(name)
        return commands

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        # Check static commands first
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        # `fulfil models` / `fulfil models list`
        if cmd_name == "models":
            return models_group
        # `fulfil reports` / `fulfil reports list` / `fulfil reports <name> execute`
        if cmd_name == "reports":
            return reports_group
        # Treat as model name → return model sub-group
        return create_model_group(cmd_name)


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
) -> None:
    """Root callback — sets global auth state."""
    set_globals(token=token, workspace=workspace, base_url=base_url, debug=debug, quiet=quiet)


@app.command()
def version(
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show CLI version."""
    if json_flag:
        output({"version": __version__}, json_flag=True)
    else:
        typer.echo(f"fulfil-cli {__version__}")


@app.command()
def whoami(
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show current user and workspace info."""
    try:
        client = get_client()
        result = client.call("system.whoami")
    except FulfilError as exc:
        _handle_error(exc)

    output(result, json_flag=json_flag)


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


def _list_models(json_flag: bool, search: str | None = None) -> None:
    """Fetch and display all available models."""
    try:
        client = get_client()
        result = client.call("system.list_models")
    except FulfilError as exc:
        _handle_error(exc)

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

    if not json_flag and isinstance(result, list):
        result = [_flatten_model_row(r) for r in result if isinstance(r, dict)]

    output(result, json_flag=json_flag, title="Available Models")


@click.group(name="models", help="List available models.", invoke_without_command=True)
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON")
@click.option("--search", "-s", default=None, help="Filter by name, description, or category.")
@click.pass_context
def models_group(ctx: click.Context, json_flag: bool, search: str | None) -> None:
    """List all available models."""
    ctx.ensure_object(dict)
    ctx.obj["json_flag"] = json_flag
    ctx.obj["search"] = search
    if ctx.invoked_subcommand is None:
        _list_models(json_flag, search=search)


@models_group.command("list")
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON")
@click.option("--search", "-s", default=None, help="Filter by name, description, or category.")
@click.pass_context
def models_list_cmd(ctx: click.Context, json_flag: bool, search: str | None) -> None:
    """List all available models."""
    _list_models(json_flag, search=search)


def _list_reports(json_flag: bool) -> None:
    """Fetch and display all available reports."""
    try:
        client = get_client()
        result = client.call("system.list_reports")
    except FulfilError as exc:
        _handle_error(exc)

    output(result, json_flag=json_flag, title="Available Reports")


@click.group(
    name="reports",
    cls=ReportGroup,
    help="Interact with reports.",
    invoke_without_command=True,
)
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON")
@click.pass_context
def reports_group(ctx: click.Context, json_flag: bool) -> None:
    """List all available reports."""
    ctx.ensure_object(dict)
    ctx.obj["json_flag"] = json_flag
    if ctx.invoked_subcommand is None:
        _list_reports(json_flag)


@reports_group.command("list")
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON")
@click.pass_context
def reports_list_cmd(ctx: click.Context, json_flag: bool) -> None:
    """List all available reports."""
    _list_reports(json_flag)


@app.command()
def docs(
    query: str = typer.Argument(..., help="Search query for Fulfil documentation"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search Fulfil documentation."""
    try:
        client = get_client()
        results = client.call("system.search_docs", query=query)
    except FulfilError as exc:
        _handle_error(exc)

    if not results:
        console.print("[dim]No results found.[/dim]")
        raise typer.Exit()

    if json_flag:
        output(results, json_flag=True)
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
fulfil contact create --data '{"name": "Acme Corp"}'
fulfil sales_order update 42 --data '{"comment": "Approved"}'
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

- Use `--json` to force JSON output (automatic when piped)
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
