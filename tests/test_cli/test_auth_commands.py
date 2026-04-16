"""Tests for auth subcommands: login, logout, status, use, workspaces."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from fulfil_cli.cli.app import app

runner = CliRunner()


@pytest.fixture
def tmp_config(tmp_path):
    """Provide a ConfigManager backed by a temp file."""
    from fulfil_cli.config.manager import ConfigManager

    return ConfigManager(tmp_path / "config.toml")


def _patch_config(tmp_config):
    """Patch ConfigManager() calls in auth module to use temp config."""
    return patch(
        "fulfil_cli.cli.commands.auth.ConfigManager",
        return_value=tmp_config,
    )


class TestLogin:
    def test_login_success(self, httpx_mock, jsonrpc_success, tmp_config):
        httpx_mock.add_response(json=jsonrpc_success("1.0.0"))

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.cli.commands.auth.store_api_key") as mock_store,
        ):
            result = runner.invoke(
                app, ["auth", "login", "--workspace", "acme.fulfil.io", "--api-key", "sk_test"]
            )

        assert result.exit_code == 0
        assert "Logged in" in result.stdout
        mock_store.assert_called_once_with("acme.fulfil.io", "sk_test")
        assert tmp_config.workspace == "acme.fulfil.io"
        assert "acme.fulfil.io" in tmp_config.workspaces

    def test_login_normalizes_slug(self, httpx_mock, jsonrpc_success, tmp_config):
        httpx_mock.add_response(json=jsonrpc_success("1.0.0"))

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.cli.commands.auth.store_api_key"),
        ):
            result = runner.invoke(
                app, ["auth", "login", "--workspace", "acme", "--api-key", "sk_test"]
            )

        assert result.exit_code == 0
        assert tmp_config.workspace == "acme.fulfil.io"

    def test_login_auth_failure(self, httpx_mock, tmp_config):
        httpx_mock.add_response(status_code=401, json={"error": "unauthorized"})

        with _patch_config(tmp_config):
            result = runner.invoke(
                app, ["auth", "login", "--workspace", "acme.fulfil.io", "--api-key", "bad_key"]
            )

        assert result.exit_code == 4
        assert "failed" in result.stdout.lower()

    def test_login_keyring_rejected_macos(self, httpx_mock, jsonrpc_success, tmp_config):
        """macOS keyring rejection should surface the keychain-delete remediation."""
        from keyring.errors import PasswordSetError

        httpx_mock.add_response(json=jsonrpc_success("1.0.0"))

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.auth.keyring_store.sys.platform", "darwin"),
            patch(
                "fulfil_cli.auth.keyring_store.keyring.set_password",
                side_effect=PasswordSetError("(-25244, 'Unknown Error')"),
            ),
        ):
            result = runner.invoke(
                app, ["auth", "login", "--workspace", "acme.fulfil.io", "--api-key", "sk_test"]
            )

        assert result.exit_code == 3
        output = result.stdout + result.stderr
        assert "security delete-generic-password" in output
        assert "acme.fulfil.io" not in tmp_config.workspaces

    def test_login_keyring_rejected_linux(self, httpx_mock, jsonrpc_success, tmp_config):
        """Non-macOS keyring rejection should surface the generic unlock remediation."""
        from keyring.errors import KeyringLocked

        httpx_mock.add_response(json=jsonrpc_success("1.0.0"))

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.auth.keyring_store.sys.platform", "linux"),
            patch(
                "fulfil_cli.auth.keyring_store.keyring.set_password",
                side_effect=KeyringLocked("keyring is locked"),
            ),
        ):
            result = runner.invoke(
                app, ["auth", "login", "--workspace", "acme.fulfil.io", "--api-key", "sk_test"]
            )

        assert result.exit_code == 3
        output = result.stdout + result.stderr
        assert "unlocked" in output.lower()
        assert "security delete-generic-password" not in output
        assert "acme.fulfil.io" not in tmp_config.workspaces


class TestLogout:
    def test_logout_current(self, tmp_config):
        tmp_config.add_workspace("acme.fulfil.io")
        tmp_config.workspace = "acme.fulfil.io"

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.cli.commands.auth.delete_api_key"),
        ):
            result = runner.invoke(app, ["auth", "logout"])

        assert result.exit_code == 0
        assert "Logged out" in result.stdout
        assert "acme.fulfil.io" not in tmp_config.workspaces

    def test_logout_specific_workspace(self, tmp_config):
        tmp_config.add_workspace("acme.fulfil.io")
        tmp_config.add_workspace("beta.fulfil.io")
        tmp_config.workspace = "acme.fulfil.io"

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.cli.commands.auth.delete_api_key"),
        ):
            result = runner.invoke(app, ["auth", "logout", "beta.fulfil.io"])

        assert result.exit_code == 0
        assert "acme.fulfil.io" in tmp_config.workspaces
        assert "beta.fulfil.io" not in tmp_config.workspaces

    def test_logout_all(self, tmp_config):
        tmp_config.add_workspace("acme.fulfil.io")
        tmp_config.add_workspace("beta.fulfil.io")

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.cli.commands.auth.delete_api_key"),
        ):
            result = runner.invoke(app, ["auth", "logout", "--all"])

        assert result.exit_code == 0
        assert tmp_config.workspaces == []

    def test_logout_not_logged_in(self, tmp_config):
        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "logout"])

        assert result.exit_code == 0
        assert "Not logged in" in result.stdout


class TestStatus:
    def test_status_logged_in(self, tmp_config):
        tmp_config.add_workspace("acme.fulfil.io")
        tmp_config.workspace = "acme.fulfil.io"

        with (
            _patch_config(tmp_config),
            patch("fulfil_cli.cli.commands.auth.get_api_key", return_value="sk_test"),
        ):
            result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 0
        assert "acme.fulfil.io" in result.stdout

    def test_status_not_logged_in(self, tmp_config):
        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 3
        assert "Not logged in" in result.stdout

    def test_status_with_env_key(self, tmp_config, monkeypatch):
        tmp_config.add_workspace("acme.fulfil.io")
        tmp_config.workspace = "acme.fulfil.io"
        monkeypatch.setenv("FULFIL_API_KEY", "sk_env")

        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 0
        assert "FULFIL_API_KEY" in result.stdout


class TestUse:
    def test_switch_workspace(self, tmp_config):
        tmp_config.add_workspace("acme.fulfil.io")
        tmp_config.add_workspace("beta.fulfil.io")
        tmp_config.workspace = "acme.fulfil.io"

        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "use", "beta.fulfil.io"])

        assert result.exit_code == 0
        assert "Switched" in result.stdout
        assert tmp_config.workspace == "beta.fulfil.io"

    def test_switch_normalizes_slug(self, tmp_config):
        tmp_config.add_workspace("acme.fulfil.io")

        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "use", "acme"])

        assert result.exit_code == 0
        assert tmp_config.workspace == "acme.fulfil.io"

    def test_switch_unknown_workspace(self, tmp_config):
        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "use", "unknown.fulfil.io"])

        assert result.exit_code == 3
        assert "not found" in result.stdout.lower()


class TestWorkspaces:
    def test_list_workspaces(self, tmp_config):
        tmp_config.add_workspace("acme.fulfil.io")
        tmp_config.add_workspace("beta.fulfil.io")
        tmp_config.workspace = "acme.fulfil.io"

        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "workspaces"])

        assert result.exit_code == 0
        assert "acme.fulfil.io" in result.stdout
        assert "beta.fulfil.io" in result.stdout

    def test_no_workspaces(self, tmp_config):
        with _patch_config(tmp_config):
            result = runner.invoke(app, ["auth", "workspaces"])

        assert result.exit_code == 0
        assert "No workspaces" in result.stdout
