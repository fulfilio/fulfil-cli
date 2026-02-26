"""Global CLI state — resolves client from config/env/flags."""

from __future__ import annotations

from fulfil_cli.auth.api_key import resolve_credentials, resolve_workspace
from fulfil_cli.client.http import FulfilClient
from fulfil_cli.config.manager import ConfigManager

# Module-level state set by the root callback
_token: str | None = None
_workspace_flag: str | None = None
_base_url: str | None = None
_debug: bool = False
_quiet: bool = False

# Cached client
_client: FulfilClient | None = None


def set_globals(
    *,
    token: str | None = None,
    workspace: str | None = None,
    base_url: str | None = None,
    debug: bool = False,
    quiet: bool = False,
) -> None:
    """Set global state from root CLI callback."""
    global _token, _workspace_flag, _base_url, _debug, _quiet, _client
    _token = token
    _workspace_flag = workspace
    _base_url = base_url
    _debug = debug
    _quiet = quiet
    _client = None  # Reset cached client


def is_debug() -> bool:
    """Return whether debug mode is enabled."""
    return _debug


def is_quiet() -> bool:
    """Return whether quiet mode is enabled."""
    return _quiet


def get_client() -> FulfilClient:
    """Get or create the FulfilClient from resolved credentials."""
    global _client
    if _client is not None:
        return _client

    config = ConfigManager()
    workspace = resolve_workspace(
        workspace_flag=_workspace_flag,
        config_workspace=config.workspace,
    )
    auth_method = config.get_auth_method(workspace)
    creds = resolve_credentials(token_flag=_token, workspace=workspace, auth_method=auth_method)

    token_refresher = None
    if creds.method == "oauth":

        def _refresh() -> str:
            from fulfil_cli.auth.keyring_store import get_oauth_tokens, store_oauth_tokens
            from fulfil_cli.auth.oauth import OAuthTokens, discover_oidc, refresh_access_token

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

    _client = FulfilClient(
        workspace=workspace,
        api_key=creds.api_key,
        access_token=creds.access_token,
        token_refresher=token_refresher,
        base_url=_base_url,
    )
    return _client
