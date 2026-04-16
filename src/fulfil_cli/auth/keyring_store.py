"""Keyring-based storage for API keys."""

from __future__ import annotations

import contextlib
import sys

import keyring
from keyring.errors import KeyringLocked, PasswordSetError

from fulfil_cli.client.errors import KeyringError

SERVICE_NAME = "fulfil-cli"

_MACOS_HINT = (
    "The macOS Keychain refused to store the credential. This usually means an "
    "existing 'fulfil-cli' entry was created by a different binary (e.g. a previous "
    "pip/pipx install) and the current binary lacks the entitlement to update it. "
    "Delete the existing entry and retry:\n\n"
    "  security delete-generic-password -s fulfil-cli\n\n"
    "Run it repeatedly until it reports 'The specified item could not be found'."
)

_GENERIC_HINT = (
    "The system keyring refused to store the credential. Ensure your keyring is "
    "unlocked and accessible (e.g. gnome-keyring/KWallet on Linux, Credential "
    "Manager on Windows), then retry."
)


def _raise_store_error(exc: Exception) -> None:
    """Translate a keyring storage failure into a KeyringError with remediation."""
    hint = _MACOS_HINT if sys.platform == "darwin" else _GENERIC_HINT
    raise KeyringError(
        message=f"Failed to store credential in system keyring: {exc}",
        hint=hint,
    ) from exc


def store_api_key(workspace: str, api_key: str) -> None:
    """Store an API key in the system keyring."""
    try:
        keyring.set_password(SERVICE_NAME, workspace, api_key)
    except (PasswordSetError, KeyringLocked) as exc:
        _raise_store_error(exc)


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
    try:
        keyring.set_password(SERVICE_NAME, f"oauth:{workspace}", tokens_json)
    except (PasswordSetError, KeyringLocked) as exc:
        _raise_store_error(exc)


def get_oauth_tokens(workspace: str) -> str | None:
    """Retrieve OAuth tokens from the system keyring. Returns None if not found."""
    with contextlib.suppress(keyring.errors.NoKeyringError):
        return keyring.get_password(SERVICE_NAME, f"oauth:{workspace}")
    return None


def delete_oauth_tokens(workspace: str) -> None:
    """Delete OAuth tokens from the system keyring."""
    with contextlib.suppress(keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
        keyring.delete_password(SERVICE_NAME, f"oauth:{workspace}")
