"""Application context — Click-idiomatic state via ctx.obj."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import click

from fulfil_cli.auth.api_key import resolve_workspace
from fulfil_cli.client.http import FulfilClient
from fulfil_cli.config.manager import ConfigManager
from fulfil_cli.workspace import Workspace


@dataclass
class AppContext:
    """CLI application context, stored in Click's ctx.obj."""

    token: str | None = None
    workspace: str | None = None
    base_url: str | None = None
    debug: bool = False
    quiet: bool = False
    output_format: str | None = None
    _workspace: Workspace | None = field(default=None, repr=False, init=False)

    def get_effective_format(self, override: str | None = None) -> str:
        """Resolve output format from --format, env, and TTY detection.

        Priority: command --format > root --format > FULFIL_FORMAT env > non-TTY > CI env > table.
        """
        if override:
            return override
        if self.output_format:
            return self.output_format
        fmt_env = os.environ.get("FULFIL_FORMAT", "").lower()
        if fmt_env in ("table", "json", "csv", "ndjson"):
            return fmt_env
        if not sys.stdout.isatty():
            return "json"
        if os.environ.get("CI"):
            return "json"
        return "table"

    def get_workspace(self) -> Workspace:
        """Get or create the Workspace for --workspace (or the configured default)."""
        if self._workspace is None:
            name = resolve_workspace(
                workspace_flag=self.workspace,
                config_workspace=ConfigManager().workspace,
            )
            self._workspace = Workspace(
                name, token=self.token, base_url=self.base_url, debug=self.debug
            )
        return self._workspace

    def get_client(self) -> FulfilClient:
        """The workspace's JSON-RPC client, for calls without a Workspace method."""
        return self.get_workspace().client


def get_app_ctx() -> AppContext:
    """Get AppContext from the current Click context."""
    return click.get_current_context().obj


VALID_FORMATS = ("table", "json", "csv", "ndjson")

format_option = click.option(
    "--format",
    "output_format",
    type=click.Choice(VALID_FORMATS, case_sensitive=False),
    default=None,
    expose_value=True,
    is_eager=False,
    help="Output format (default: table for TTY, json when piped)",
)
