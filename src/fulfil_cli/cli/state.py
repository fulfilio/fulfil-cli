"""Application context — Click-idiomatic state via ctx.obj."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import typer

from fulfil_cli.auth.api_key import resolve_credentials, resolve_workspace
from fulfil_cli.auth.keyring_store import get_oauth_tokens, store_oauth_tokens
from fulfil_cli.auth.oauth import OAuthTokens, discover_oidc, refresh_access_token
from fulfil_cli.client.http import FulfilClient
from fulfil_cli.config.manager import ConfigManager


@dataclass
class AppContext:
    """CLI application context, stored in Click's ctx.obj."""

    token: str | None = None
    workspace: str | None = None
    base_url: str | None = None
    debug: bool = False
    quiet: bool = False
    output_format: str | None = None
    _client: FulfilClient | None = field(default=None, repr=False, init=False)

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

    def get_client(self) -> FulfilClient:
        """Get or create the FulfilClient from resolved credentials."""
        if self._client is not None:
            return self._client

        config = ConfigManager()
        workspace = resolve_workspace(
            workspace_flag=self.workspace,
            config_workspace=config.workspace,
        )
        auth_method = config.get_auth_method(workspace)
        creds = resolve_credentials(
            token_flag=self.token, workspace=workspace, auth_method=auth_method
        )

        token_refresher = None
        if creds.method == "oauth":

            def _refresh() -> str:
                tokens_json = get_oauth_tokens(workspace)
                if not tokens_json:
                    raise RuntimeError("No OAuth tokens found for refresh")
                tokens = OAuthTokens.from_json(tokens_json)
                if not tokens.refresh_token:
                    raise RuntimeError("No refresh token available")
                oidc = discover_oidc(workspace)
                new_tokens = refresh_access_token(oidc["token_endpoint"], tokens.refresh_token)
                store_oauth_tokens(workspace, new_tokens.to_json().decode())
                return new_tokens.access_token

            token_refresher = _refresh

        self._client = FulfilClient(
            workspace=workspace,
            api_key=creds.api_key,
            access_token=creds.access_token,
            token_refresher=token_refresher,
            base_url=self.base_url,
            debug=self.debug,
        )
        return self._client


_current: AppContext | None = None


def _set_current(ctx: AppContext) -> None:
    global _current
    _current = ctx


def _get_current() -> AppContext | None:
    return _current


VALID_FORMATS = ("table", "json", "csv", "ndjson")


def _validate_format(value: str | None) -> str | None:
    if value is None:
        return None
    lowered = value.lower()
    if lowered not in VALID_FORMATS:
        raise typer.BadParameter(
            f"Invalid format '{value}'. Choose from: {', '.join(VALID_FORMATS)}"
        )
    return lowered


format_option = typer.Option(
    None,
    "--format",
    callback=_validate_format,
    help="Output format: table, json, csv, ndjson (default: table for TTY, json when piped)",
)
