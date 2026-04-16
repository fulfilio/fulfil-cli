"""Shared utilities for CLI commands — error handling and argument parsing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import click
import typer
from rich.console import Console

from fulfil_cli.cli.state import AppContext
from fulfil_cli.client.errors import EXIT_VALIDATION, FulfilError, ValidationError
from fulfil_cli.output.json_output import print_json

console = Console(stderr=True)


def handle_error(exc: FulfilError, *, context: str | None = None) -> NoReturn:
    """Format a FulfilError for the user and exit.

    Uses the current Click context to determine output format.
    When *context* is provided (e.g. a model or report name), it is
    included in the output for orientation.
    """
    ctx = click.get_current_context(silent=True)
    app_ctx: AppContext | None = ctx.obj if ctx else None

    if app_ctx and app_ctx.get_effective_format() != "table":
        err = exc.to_dict()
        if context:
            err["context"] = context
        if not exc.hint and context and isinstance(exc, ValidationError):
            err["hint"] = f"Run 'fulfil {context} describe' to see valid field names."
        print_json(err, file=sys.stderr)
        raise typer.Exit(code=exc.exit_code)

    label = context or "fulfil"
    console.print(f"[red]Error ({label}): {exc}[/red]")
    if exc.hint:
        console.print(f"[dim]Hint: {exc.hint}[/dim]")
    elif app_ctx and not app_ctx.quiet and context and isinstance(exc, ValidationError):
        console.print(f"[dim]Hint: Run 'fulfil {context} describe' to see valid field names.[/dim]")
    raise typer.Exit(code=exc.exit_code)


def parse_json_arg(value: str, arg_name: str) -> Any:
    """Parse a JSON string, exiting with a clear message on failure."""
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON for {arg_name}: {exc}[/red]")
        raise typer.Exit(code=EXIT_VALIDATION) from None


def resolve_value_or_file(value: str, arg_name: str) -> str:
    """Return *value*, or the contents of the referenced file when prefixed with '@'.

    Follows the curl/gh convention: '@path/to/file.json' reads from the file.
    Use '\\@literal' to pass a value that actually starts with a literal '@'.
    """
    if value.startswith("\\@"):
        return value[1:]
    if value.startswith("@"):
        path = Path(value[1:])
        try:
            return path.read_text()
        except OSError as exc:
            console.print(f"[red]Cannot read file for {arg_name}: {exc}[/red]")
            raise typer.Exit(code=EXIT_VALIDATION) from None
    return value
