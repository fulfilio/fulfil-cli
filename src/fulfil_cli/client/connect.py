"""Build an authenticated FulfilClient for a workspace, the same way the CLI does."""

from __future__ import annotations

from fulfil_cli.auth.api_key import resolve_credentials
from fulfil_cli.auth.keyring_store import get_oauth_tokens, store_oauth_tokens
from fulfil_cli.auth.oauth import OAuthTokens, discover_oidc, refresh_access_token
from fulfil_cli.client.http import FulfilClient
from fulfil_cli.config.manager import ConfigManager


def connect(
    workspace: str,
    *,
    token: str | None = None,
    base_url: str | None = None,
    timeout: float = 30.0,
    debug: bool = False,
) -> FulfilClient:
    """Return a client for ``workspace`` using the CLI's credential resolution.

    Credentials: ``token`` > ``FULFIL_API_KEY`` > the login stored by ``fulfil auth login``
    for this workspace (OAuth tokens are refreshed when they expire).
    """
    auth_method = ConfigManager().get_auth_method(workspace)
    creds = resolve_credentials(token_flag=token, workspace=workspace, auth_method=auth_method)

    token_refresher = None
    if creds.method == "oauth":

        def token_refresher() -> str:
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

    return FulfilClient(
        workspace=workspace,
        api_key=creds.api_key,
        access_token=creds.access_token,
        token_refresher=token_refresher,
        base_url=base_url,
        timeout=timeout,
        debug=debug,
    )
