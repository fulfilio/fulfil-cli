"""Tests for the CLI state module."""

from __future__ import annotations

import pytest

from fulfil_cli.cli.state import get_client, is_debug, is_quiet, set_globals
from fulfil_cli.client.errors import AuthError


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset global state before and after each test."""
    set_globals()
    yield
    set_globals()


class TestSetGlobals:
    def test_debug_flag(self):
        set_globals(debug=True)
        assert is_debug() is True

    def test_quiet_flag(self):
        set_globals(quiet=True)
        assert is_quiet() is True

    def test_defaults(self):
        set_globals()
        assert is_debug() is False
        assert is_quiet() is False


class TestGetClient:
    def test_with_env_vars(self, monkeypatch):
        monkeypatch.setenv("FULFIL_API_KEY", "sk_test")
        monkeypatch.setenv("FULFIL_WORKSPACE", "acme.fulfil.io")
        set_globals()

        client = get_client()
        assert client.workspace == "acme.fulfil.io"
        assert client.url == "https://acme.fulfil.io/api/v3/jsonrpc"
        client.close()

    def test_with_token_flag(self, monkeypatch):
        monkeypatch.setenv("FULFIL_WORKSPACE", "acme.fulfil.io")
        set_globals(token="sk_flag_token")

        client = get_client()
        assert client.workspace == "acme.fulfil.io"
        client.close()

    def test_client_cached(self, monkeypatch):
        monkeypatch.setenv("FULFIL_API_KEY", "sk_test")
        monkeypatch.setenv("FULFIL_WORKSPACE", "acme.fulfil.io")
        set_globals()

        client1 = get_client()
        client2 = get_client()
        assert client1 is client2
        client1.close()

    def test_missing_workspace(self, monkeypatch):
        monkeypatch.setenv("FULFIL_API_KEY", "sk_test")
        monkeypatch.delenv("FULFIL_WORKSPACE", raising=False)
        # Ensure no workspace from config file either
        monkeypatch.setattr(
            "fulfil_cli.cli.state.ConfigManager.workspace",
            property(lambda self: None),
        )
        set_globals()

        with pytest.raises(AuthError, match="No workspace"):
            get_client()

    def test_missing_api_key(self, monkeypatch):
        monkeypatch.setenv("FULFIL_WORKSPACE", "acme.fulfil.io")
        monkeypatch.delenv("FULFIL_API_KEY", raising=False)
        set_globals()

        with pytest.raises(AuthError, match="No credentials found"):
            get_client()

    def test_set_globals_resets_cache(self, monkeypatch):
        monkeypatch.setenv("FULFIL_API_KEY", "sk_test")
        monkeypatch.setenv("FULFIL_WORKSPACE", "acme.fulfil.io")
        set_globals()

        client1 = get_client()
        set_globals()  # Should reset cache
        client2 = get_client()
        assert client1 is not client2
        client1.close()
        client2.close()
