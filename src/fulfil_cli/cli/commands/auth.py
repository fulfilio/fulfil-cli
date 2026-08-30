"""Auth commands: login, logout, status, token, workspaces, use."""

from __future__ import annotations

import os
import sys

import httpx
import typer
from rich.console import Console

from fulfil_cli.auth.api_key import normalize_workspace, resolve_credentials, resolve_workspace
from fulfil_cli.auth.keyring_store import (
    delete_api_key,
    delete_oauth_tokens,
    get_api_key,
    get_oauth_tokens,
    store_api_key,
    store_oauth_tokens,
)
from fulfil_cli.auth.oauth import OAuthTokens, run_oauth_flow
from fulfil_cli.cli.commands.common import handle_error
from fulfil_cli.client.errors import EXIT_CONFIG, EXIT_GENERAL, AuthError, FulfilError
from fulfil_cli.client.http import FulfilClient
from fulfil_cli.config.manager import ConfigManager

app = typer.Typer(help="Manage authentication.")
console = Console()


def _login_api_key(workspace: str, api_key: str | None, config: ConfigManager) -> None:
    """Login with an API key."""
    if not api_key:
        api_key = typer.prompt("API key", hide_input=True)

    console.print(f"[dim]Validating credentials for {workspace}...[/dim]")
    try:
        client = FulfilClient(workspace=workspace, api_key=api_key)
        client.call("system.version")
    except FulfilError as exc:
        console.print(f"[red]Authentication failed: {exc}[/red]")
        raise typer.Exit(code=exc.exit_code) from None
    except httpx.HTTPError:
        console.print(
            "[yellow]Warning: Could not validate credentials "
            "(v3 API may not be deployed yet).[/yellow]"
        )

    try:
        store_api_key(workspace, api_key)
    except FulfilError as exc:
        handle_error(exc, context="auth")
    config.set_auth_method(workspace, "api_key")
    config.add_workspace(workspace)
    config.workspace = workspace
    console.print(f"[green]Logged in to workspace '{workspace}'.[/green]")


def _login_oauth(workspace: str, config: ConfigManager) -> None:
    """Login with OAuth 2.0 (authorization code + PKCE)."""
    console.print(f"[dim]Starting OAuth login for {workspace}...[/dim]")
    console.print("[dim]Opening browser for authentication...[/dim]")

    try:
        tokens = run_oauth_flow(workspace)
    except (RuntimeError, httpx.HTTPError) as exc:
        console.print(f"[red]OAuth login failed: {exc}[/red]")
        raise typer.Exit(code=EXIT_GENERAL) from None

    # Validate the token
    console.print(f"[dim]Validating credentials for {workspace}...[/dim]")
    try:
        client = FulfilClient(workspace=workspace, access_token=tokens.access_token)
        client.call("system.version")
    except FulfilError as exc:
        console.print(f"[red]Authentication failed: {exc}[/red]")
        raise typer.Exit(code=exc.exit_code) from None
    except httpx.HTTPError:
        console.print(
            "[yellow]Warning: Could not validate credentials "
            "(v3 API may not be deployed yet).[/yellow]"
        )

    try:
        store_oauth_tokens(workspace, tokens.to_json().decode())
    except FulfilError as exc:
        handle_error(exc, context="auth")
    config.set_auth_method(workspace, "oauth")
    config.add_workspace(workspace)
    config.workspace = workspace
    console.print(f"[green]Logged in to workspace '{workspace}' via OAuth.[/green]")


@app.command()
def login(
    workspace: str | None = typer.Option(None, help="Workspace domain (e.g. 'acme.fulfil.io')"),
    api_key: str | None = typer.Option(None, "--api-key", help="API key"),
    method: str | None = typer.Option(None, "--method", help="Auth method: 'oauth' or 'api_key'"),
) -> None:
    """Authenticate with a Fulfil workspace."""
    config = ConfigManager()

    if not workspace:
        workspace = typer.prompt("Workspace domain (e.g. acme.fulfil.io)")
    workspace = normalize_workspace(workspace)

    # If --api-key is provided, use API key method directly
    if api_key:
        _login_api_key(workspace, api_key, config)
        return

    # If --method is specified, use that
    if method:
        if method == "oauth":
            _login_oauth(workspace, config)
        elif method == "api_key":
            _login_api_key(workspace, None, config)
        else:
            console.print(f"[red]Unknown auth method: {method}[/red]")
            raise typer.Exit(code=EXIT_GENERAL)
        return

    # Interactive prompt
    console.print("\nHow would you like to authenticate?")
    console.print("  1. Login with Fulfil (OAuth)")
    console.print("  2. I have an API key")
    choice = typer.prompt("\nChoice", default="1")

    if choice == "1":
        _login_oauth(workspace, config)
    elif choice == "2":
        _login_api_key(workspace, None, config)
    else:
        console.print("[red]Invalid choice.[/red]")
        raise typer.Exit(code=EXIT_GENERAL)


@app.command()
def logout(
    workspace: str | None = typer.Argument(
        None, help="Workspace to log out from (default: current)"
    ),
    all_workspaces: bool = typer.Option(False, "--all", help="Log out from all workspaces"),
) -> None:
    """Remove stored credentials."""
    config = ConfigManager()

    if all_workspaces:
        for ws in config.workspaces:
            delete_api_key(ws)
            delete_oauth_tokens(ws)
        config.clear_workspaces()
        console.print("[green]Logged out from all workspaces.[/green]")
        return

    target = workspace or config.workspace
    if target:
        auth_method = config.get_auth_method(target)
        if auth_method == "oauth":
            delete_oauth_tokens(target)
        else:
            delete_api_key(target)
        config.delete(f"workspace_auth.{target}")
        config.remove_workspace(target)
        if config.workspace == target:
            remaining = config.workspaces
            config.workspace = remaining[0] if remaining else None
        console.print(f"[green]Logged out from '{target}'.[/green]")
    else:
        console.print("[dim]Not logged in.[/dim]")


@app.command()
def status() -> None:
    """Show current authentication status."""
    config = ConfigManager()
    workspace = config.workspace
    if not workspace:
        console.print("[yellow]Not logged in.[/yellow]")
        console.print("[dim]Run 'fulfil auth login' to authenticate.[/dim]")
        raise typer.Exit(code=EXIT_CONFIG)

    auth_method = config.get_auth_method(workspace)
    env_key = "FULFIL_API_KEY" in os.environ

    console.print(f"Workspace: [bold]{workspace}[/bold]")
    console.print(f"Method:    [bold]{auth_method}[/bold]")

    if env_key:
        console.print("API Key:   [green]set via FULFIL_API_KEY[/green]")
    elif auth_method == "oauth":
        tokens_json = get_oauth_tokens(workspace)
        if tokens_json:
            tokens = OAuthTokens.from_json(tokens_json)
            if tokens.is_expired:
                if tokens.refresh_token:
                    console.print("Token:     [yellow]expired (will auto-refresh)[/yellow]")
                else:
                    console.print("Token:     [red]expired[/red]")
            else:
                console.print("Token:     [green]valid[/green]")
        else:
            console.print("Token:     [red]not found[/red]")
    else:
        has_key = get_api_key(workspace) is not None
        if has_key:
            console.print("API Key:   [green]stored in keyring[/green]")
        else:
            console.print("API Key:   [red]not found[/red]")

    all_ws = config.workspaces
    if len(all_ws) > 1:
        console.print(f"\nAll workspaces ({len(all_ws)}):")
        for ws in all_ws:
            marker = " [bold green]*[/bold green]" if ws == workspace else ""
            console.print(f"  {ws}{marker}")


@app.command()
def token() -> None:
    """Print the current API key or access token to stdout (for piping)."""
    config = ConfigManager()
    try:
        workspace = resolve_workspace(config_workspace=config.workspace)
        auth_method = config.get_auth_method(workspace)
        creds = resolve_credentials(workspace=workspace, auth_method=auth_method)
    except AuthError as exc:
        console.print(f"[red]{exc}[/red]", file=sys.stderr)
        raise typer.Exit(code=exc.exit_code) from None
    print(creds.access_token or creds.api_key)


@app.command()
def workspaces() -> None:
    """List all stored workspaces."""
    config = ConfigManager()
    all_ws = config.workspaces
    current = config.workspace

    if not all_ws:
        console.print("[dim]No workspaces configured. Run 'fulfil auth login'.[/dim]")
        return

    for ws in all_ws:
        if ws == current:
            console.print(f"  [bold green]*[/bold green] {ws} [dim](current)[/dim]")
        else:
            console.print(f"    {ws}")


@app.command()
def use(
    workspace: str = typer.Argument(help="Workspace to switch to"),
) -> None:
    """Switch the active workspace."""
    config = ConfigManager()

    workspace = normalize_workspace(workspace)

    if workspace not in config.workspaces:
        console.print(f"[red]Workspace '{workspace}' not found.[/red]")
        console.print("[dim]Run 'fulfil auth login' to add it first.[/dim]")
        raise typer.Exit(code=EXIT_CONFIG)

    config.workspace = workspace
    console.print(f"[green]Switched to workspace '{workspace}'.[/green]")
