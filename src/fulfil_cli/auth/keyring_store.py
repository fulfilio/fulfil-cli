"""Keyring-based storage for API keys."""

from __future__ import annotations

import contextlib

import keyring

SERVICE_NAME = "fulfil-cli"


def store_api_key(workspace: str, api_key: str) -> None:
    """Store an API key in the system keyring."""
    keyring.set_password(SERVICE_NAME, workspace, api_key)


def get_api_key(workspace: str) -> str | None:
    """Retrieve an API key from the system keyring. Returns None if no keyring backend."""
    with contextlib.suppress(keyring.errors.NoKeyringError):
        return keyring.get_password(SERVICE_NAME, workspace)
    return None


def delete_api_key(workspace: str) -> None:
    """Delete an API key from the system keyring."""
    with contextlib.suppress(keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
        keyring.delete_password(SERVICE_NAME, workspace)


def store_oauth_tokens(workspace: str, tokens_json: str) -> None:
    """Store OAuth tokens in the system keyring."""
    keyring.set_password(SERVICE_NAME, f"oauth:{workspace}", tokens_json)


def get_oauth_tokens(workspace: str) -> str | None:
    """Retrieve OAuth tokens from the system keyring. Returns None if not found."""
    with contextlib.suppress(keyring.errors.NoKeyringError):
        return keyring.get_password(SERVICE_NAME, f"oauth:{workspace}")
    return None


def delete_oauth_tokens(workspace: str) -> None:
    """Delete OAuth tokens from the system keyring."""
    with contextlib.suppress(keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
        keyring.delete_password(SERVICE_NAME, f"oauth:{workspace}")
