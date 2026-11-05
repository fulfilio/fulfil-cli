"""Rich output for model describe / fields commands."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table


def print_model_describe(data: dict[str, Any]) -> None:
    """Render a model description with fields and endpoints tables."""
    console = Console()

    # Header info
    name = data.get("model_name", "")
    desc = data.get("description", "")
    category = data.get("category", "")
    header = f"[bold]{name}[/bold]"
    if desc and desc != name:
        header += f" — {desc}"
    if category:
        header += f"  [dim]({category})[/dim]"
    console.print(header)
    console.print()

    # Fields table
    fields = data.get("fields", [])
    if fields:
        table = Table(title="Fields", show_lines=False, title_style="bold")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Type", no_wrap=True)
        table.add_column("Description")
        table.add_column("Req", justify="center", no_wrap=True)
        table.add_column("RO", justify="center", no_wrap=True)
        table.add_column("Relation", style="dim", no_wrap=True)

        for f in fields:
            req = "[green]✓[/green]" if f.get("required") else ""
            ro = "[dim]✓[/dim]" if f.get("readonly") else ""
            desc = f.get("description", "") or ""
            help_text = f.get("help_text", "") or ""
            display_desc = desc or help_text
            relation = f.get("relation_model", "") or ""
            table.add_row(
                f.get("name", ""),
                f.get("type", ""),
                display_desc,
                req,
                ro,
                relation,
            )

        console.print(table)
    else:
        console.print("[dim]No fields.[/dim]")

    # Commands section — standard CRUD + custom endpoints
    console.print()
    name = data.get("model_name", "")
    table = Table(
        title="Commands [dim](use 'fulfil <model> describe <name>' for details)[/dim]",
        show_lines=False,
        title_style="bold",
    )
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description")

    # Standard commands every model supports
    standard = [
        ("list", "List records matching filters"),
        ("get", "Get records by ID"),
        ("create", "Create new records"),
        ("update", "Update records by ID"),
        ("delete", "Delete records by ID"),
        ("count", "Count records matching filters"),
    ]
    for cmd, cmd_desc in standard:
        table.add_row(cmd, cmd_desc)

    # Custom endpoints from the server
    endpoints = data.get("endpoints", [])
    for ep in endpoints:
        method = ep.get("rpc_name", "") or ep.get("name", "")
        ep_desc = ep.get("description", "") or ""
        table.add_row(method, ep_desc)

    console.print(table)


def _parameters_table(title: str, params: list[dict[str, Any]]) -> Table:
    """A table of an endpoint's parameters, or of a model they reference."""
    table = Table(title=title, show_lines=False, title_style="bold")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Required", justify="center", no_wrap=True)
    table.add_column("Description")

    for p in params:
        req = "[green]✓[/green]" if p.get("required") else ""
        table.add_row(
            escape(p.get("name") or ""),
            escape(p.get("type") or ""),
            req,
            escape(p.get("description") or ""),
        )
    return table


def print_endpoint_detail(endpoint: dict[str, Any], model: str) -> None:
    """Render detailed info for a single endpoint."""
    console = Console()

    name = endpoint.get("rpc_name", "") or endpoint.get("name", "")
    desc = endpoint.get("description", "") or ""

    console.print(f"[bold]{model}.{name}[/bold]")
    if desc:
        console.print(f"  {escape(desc)}")
    console.print()

    # The first schema is the request body itself; the rest are models it references.
    schemas = endpoint.get("body_schemas") or {}
    body, *referenced = schemas.items() or [(None, [])]
    params = [*(endpoint.get("parameters") or []), *body[1]]
    if params:
        console.print(_parameters_table("Parameters", params))
        for model_name, fields in referenced:
            console.print(_parameters_table(model_name, fields))
    else:
        console.print("[dim]No parameters.[/dim]")

    console.print()
    console.print(f"[dim]Call: fulfil {model} call {name} --data '{{...}}'[/dim]")
