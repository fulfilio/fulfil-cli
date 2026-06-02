"""Dynamic model subcommand actions: list/get/create/update/delete/count/call/fields."""

from __future__ import annotations

import difflib
import sys
from typing import Any

import typer
from rich.console import Console

from fulfil_cli.cli.commands.common import handle_error, parse_json_arg
from fulfil_cli.cli.state import AppContext, format_option
from fulfil_cli.client.errors import EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE, FulfilError
from fulfil_cli.output.formatter import output, output_model_describe

console = Console(stderr=True)


def _parse_fields(value: str | None) -> list[str] | None:
    """Parse comma-separated field names."""
    if not value:
        return None
    return [f.strip() for f in value.split(",") if f.strip()]


def _parse_ids(value: str) -> list[int]:
    """Parse comma-separated IDs."""
    try:
        return [int(x.strip()) for x in value.split(",")]
    except ValueError:
        console.print("[red]IDs must be comma-separated integers.[/red]")
        raise typer.Exit(code=EXIT_USAGE) from None


def _parse_order(value: str) -> dict[str, str]:
    """Parse order string like 'sale_date:desc,name:asc' into {"sale_date": "DESC", "name": "ASC"}.

    Each pair is field:direction where direction defaults to ASC if omitted.
    """
    result: dict[str, str] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            field, direction = part.split(":", 1)
            result[field.strip()] = direction.strip().upper()
        else:
            result[part] = "ASC"
    return result


def create_model_group(model_name: str) -> typer.Typer:
    """Create a Typer app for a model with all standard actions."""

    model_group = typer.Typer(name=model_name, help=f"Interact with {model_name} records.")

    @model_group.command("list")
    def list_cmd(
        ctx: typer.Context,
        where: str | None = typer.Option(
            None,
            "--where",
            help=(
                "MongoDB-style JSON filter. "
                'Equality: \'{"state": "confirmed"}\'. '
                "Operators (gt, gte, lt, lte, ne, in, not_in, contains, startswith, endswith): "
                '\'{"total_amount": {"gte": 100}}\'. '
                'OR logic: \'{"or": [{"state": "draft"}, {"state": "confirmed"}]}\''
            ),
        ),
        fields_str: str | None = typer.Option(
            None,
            "--fields",
            help="Comma-separated field names, e.g. name,state,sale_date",
        ),
        order: str | None = typer.Option(
            None,
            "--order",
            help=(
                "Sort order as field:direction pairs, comma-separated. "
                "Direction is ASC or DESC (default: ASC). "
                "Examples: sale_date:desc  or  sale_date:desc,name:asc  or  name"
            ),
        ),
        cursor: str | None = typer.Option(
            None,
            "--cursor",
            help="Opaque cursor for fetching the next page (from previous response).",
        ),
        page_size: int = typer.Option(
            20, "--page-size", "--limit", help="Records per page (default: 20)"
        ),
        output_format: str | None = format_option,
    ) -> None:
        """List records matching filters.

        Examples:

        \b
          fulfil sales_order list
          fulfil sales_order list --where '{"state": "confirmed"}' --fields name,state
          fulfil sales_order list --order sale_date:desc --limit 50
          fulfil sales_order list --cursor <token>
        """
        app_ctx: AppContext = ctx.obj
        fmt = app_ctx.get_effective_format(output_format)
        params: dict[str, Any] = {"page_size": page_size}

        if where:
            params["where"] = parse_json_arg(where, "--where")
        if order:
            params["ordering"] = _parse_order(order)
        if fields_str:
            params["fields"] = _parse_fields(fields_str)
        if cursor:
            params["cursor"] = cursor

        try:
            client = app_ctx.get_client()
            result = client.call(f"model.{model_name}.find", **params)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        # Handle envelope response: {"data": [...], "pagination": {...}}
        if isinstance(result, dict) and "data" in result and "pagination" in result:
            records = result["data"]
            pagination = result["pagination"]

            if fmt == "json":
                output(result, fmt=fmt)
            elif fmt != "table":
                output(records, fmt=fmt)
            else:
                output(records, fmt="table", title=model_name)
                if not app_ctx.quiet and pagination:
                    count = len(records)
                    next_cursor = pagination.get("next_cursor")
                    has_more = pagination.get("has_more", next_cursor is not None)
                    if has_more:
                        console.print(f"[dim]{count} records (more available)[/dim]")
                        if next_cursor:
                            console.print(
                                f"[dim]Next page: fulfil {model_name} list"
                                f" --cursor {next_cursor}[/dim]"
                            )
                    else:
                        console.print(f"[dim]{count} records[/dim]")
        else:
            output(result, fmt=fmt, title=model_name)

    @model_group.command("get")
    def get_cmd(
        ctx: typer.Context,
        ids: str = typer.Argument(...),
        output_format: str | None = format_option,
    ) -> None:
        """Get records by ID(s). IDS is one or more comma-separated integers (e.g. 123 or 1,2,3)."""
        app_ctx: AppContext = ctx.obj
        parsed_ids = _parse_ids(ids)

        try:
            client = app_ctx.get_client()
            result = client.call(f"model.{model_name}.serialize", parsed_ids)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        if len(parsed_ids) == 1 and isinstance(result, list) and len(result) == 1:
            result = result[0]

        output(result, fmt=app_ctx.get_effective_format(output_format), title=model_name)

    @model_group.command("create")
    def create_cmd(
        ctx: typer.Context,
        data: typer.FileText = typer.Argument("-"),
        output_format: str | None = format_option,
    ) -> None:
        """Create record(s) from JSON. Accepts a single object or an array.

        \b
        DATA is a file path or '-' for stdin (default: stdin).
        Prefer arrays for bulk creation — never loop single creates.

        Examples:
          echo '{"name": "Test"}' | fulfil contact create
          echo '[{"name": "A"}, {"name": "B"}]' | fulfil contact create
          fulfil contact create records.json
        """
        app_ctx: AppContext = ctx.obj
        parsed = parse_json_arg(data.read(), "data")
        vlist = parsed if isinstance(parsed, list) else [parsed]

        try:
            client = app_ctx.get_client()
            result = client.call(f"model.{model_name}.create", vlist=vlist)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        output(result, fmt=app_ctx.get_effective_format(output_format))

    @model_group.command("update")
    def update_cmd(
        ctx: typer.Context,
        ids: str = typer.Argument(...),
        data: typer.FileText = typer.Argument("-"),
        output_format: str | None = format_option,
    ) -> None:
        """Update record(s) by ID.

        \b
        IDS is one or more comma-separated integers (e.g. 42 or 1,2,3).
        DATA is a file path or '-' for stdin (default: stdin).

        Examples:
          echo '{"name": "Updated"}' | fulfil contact update 42
          fulfil contact update 42 updates.json
        """
        app_ctx: AppContext = ctx.obj
        parsed_ids = _parse_ids(ids)
        values = parse_json_arg(data.read(), "data")

        try:
            client = app_ctx.get_client()
            result = client.call(f"model.{model_name}.update", ids=parsed_ids, values=values)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        output(result, fmt=app_ctx.get_effective_format(output_format))

    @model_group.command("delete")
    def delete_cmd(
        ctx: typer.Context,
        ids: str = typer.Argument(...),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    ) -> None:
        """Permanently delete record(s) by ID. This cannot be undone.

        IDS is one or more comma-separated integers.
        """
        app_ctx: AppContext = ctx.obj
        parsed_ids = _parse_ids(ids)

        if not yes:
            if not sys.stdin.isatty():
                console.print(
                    "[red]Error: Delete requires confirmation. "
                    "Use --yes/-y to skip in non-interactive mode.[/red]"
                )
                raise typer.Exit(code=EXIT_USAGE)
            id_list = ", ".join(str(i) for i in parsed_ids)
            if not typer.confirm(
                f"Delete {len(parsed_ids)} record(s) from {model_name} ({id_list})?"
            ):
                console.print("[dim]Aborted.[/dim]")
                raise typer.Exit(code=EXIT_OK)

        try:
            client = app_ctx.get_client()
            client.call(f"model.{model_name}.delete", ids=parsed_ids)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        if not app_ctx.quiet:
            console.print(f"[green]Deleted {len(parsed_ids)} record(s).[/green]")

    @model_group.command("count")
    def count_cmd(
        ctx: typer.Context,
        where: str | None = typer.Option(
            None,
            "--where",
            help=(
                "MongoDB-style JSON filter (same syntax as list --where). "
                'Example: \'{"state": "confirmed"}\''
            ),
        ),
        output_format: str | None = format_option,
    ) -> None:
        """Count records matching filters. Returns a single integer."""
        app_ctx: AppContext = ctx.obj
        params: dict[str, Any] = {}
        if where:
            params["where"] = parse_json_arg(where, "--where")

        try:
            client = app_ctx.get_client()
            result = client.call(f"model.{model_name}.count", **params)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        fmt = app_ctx.get_effective_format(output_format)
        if fmt != "table":
            output({"count": result}, fmt=fmt)
        else:
            console.print(str(result))

    @model_group.command("call")
    def call_cmd(
        ctx: typer.Context,
        method_name: str = typer.Argument(...),
        ids: str | None = typer.Option(
            None,
            "--ids",
            help="Comma-separated record IDs to pass to the method, e.g. 1,2,3",
        ),
        data: str | None = typer.Option(
            None,
            "--data",
            help=("Extra method arguments as a JSON object. Example: '{\"warehouse\": 1}'"),
        ),
        output_format: str | None = format_option,
    ) -> None:
        """Call a custom method on the model.

        METHOD_NAME is the method suffix (e.g. 'confirm', 'process', 'cancel').
        The full RPC method will be model.<model_name>.<METHOD_NAME>.

        \b
        Examples:
          fulfil sales_order call confirm --ids 1,2,3
          fulfil sales_order call process --ids 42
        """
        app_ctx: AppContext = ctx.obj
        params: dict[str, Any] = {}
        if ids:
            params["ids"] = _parse_ids(ids)
        if data:
            extra = parse_json_arg(data, "--data")
            if isinstance(extra, dict):
                params.update(extra)

        try:
            client = app_ctx.get_client()
            result = client.call(f"model.{model_name}.{method_name}", **params)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        output(result, fmt=app_ctx.get_effective_format(output_format))

    @model_group.command("describe")
    def describe_cmd(
        ctx: typer.Context,
        endpoint_name: str | None = typer.Argument(None),
        output_format: str | None = format_option,
    ) -> None:
        """Describe the model, or a specific endpoint.

        \b
          fulfil sales_order describe           # all fields and endpoints
          fulfil sales_order describe find       # details for the find endpoint
          fulfil sales_order describe confirm    # details for the confirm endpoint
        """
        app_ctx: AppContext = ctx.obj
        try:
            client = app_ctx.get_client()
            result = client.call("system.describe_model", model=model_name)
        except FulfilError as exc:
            handle_error(exc, context=model_name)

        fmt = app_ctx.get_effective_format(output_format)
        if endpoint_name:
            _describe_endpoint(result, model_name, endpoint_name, fmt)
        else:
            output_model_describe(result, fmt=fmt)

    @model_group.command("fields")
    def fields_cmd(ctx: typer.Context) -> None:
        """Alias for 'describe'."""
        describe_cmd(ctx, endpoint_name=None, output_format=None)

    return model_group


def _describe_endpoint(model_data: dict, model: str, endpoint_name: str, fmt: str) -> None:
    """Show details for a specific endpoint, or error if not found."""
    from fulfil_cli.output.describe import print_endpoint_detail

    endpoints = model_data.get("endpoints", [])
    for ep in endpoints:
        if ep.get("rpc_name") == endpoint_name or ep.get("name") == endpoint_name:
            if fmt != "table":
                output(ep, fmt=fmt)
            else:
                print_endpoint_detail(ep, model)
            return

    # Not found — show available endpoints
    names = [ep.get("rpc_name", ep.get("name", "")) for ep in endpoints]
    console.print(f"[red]Endpoint '{endpoint_name}' not found on {model}.[/red]")
    if names:
        matches = difflib.get_close_matches(endpoint_name, names, n=3, cutoff=0.4)
        if matches:
            console.print(f"[dim]Did you mean: {', '.join(matches)}?[/dim]")
        else:
            console.print(f"[dim]Available: {', '.join(sorted(names))}[/dim]")
    raise typer.Exit(code=EXIT_NOT_FOUND)
