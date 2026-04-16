"""Error hierarchy mapping JSON-RPC error codes to CLI exit codes."""

from __future__ import annotations

from dataclasses import dataclass, field

# CLI exit codes
EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_AUTH = 4
EXIT_NOT_FOUND = 5
EXIT_FORBIDDEN = 6
EXIT_VALIDATION = 7
EXIT_RATE_LIMIT = 8
EXIT_SERVER = 9
EXIT_NETWORK = 10


@dataclass
class FulfilError(Exception):
    """Base error for all Fulfil CLI errors."""

    message: str
    exit_code: int = EXIT_SERVER
    hint: str | None = None

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable error representation."""
        d: dict[str, object] = {
            "error": type(self).__name__,
            "message": self.message,
            "exit_code": self.exit_code,
        }
        if self.hint:
            d["hint"] = self.hint
        return d


@dataclass
class ConfigError(FulfilError):
    """Configuration is missing or invalid."""

    exit_code: int = field(default=EXIT_CONFIG)


@dataclass
class KeyringError(ConfigError):
    """System keyring storage is unavailable or rejected a write."""

    exit_code: int = field(default=EXIT_CONFIG)


@dataclass
class AuthError(FulfilError):
    """Authentication failed."""

    exit_code: int = field(default=EXIT_AUTH)


@dataclass
class NotFoundError(FulfilError):
    """Record or resource not found."""

    exit_code: int = field(default=EXIT_NOT_FOUND)


@dataclass
class ForbiddenError(FulfilError):
    """Permission denied."""

    exit_code: int = field(default=EXIT_FORBIDDEN)


@dataclass
class ValidationError(FulfilError):
    """Invalid parameters or data."""

    exit_code: int = field(default=EXIT_VALIDATION)


@dataclass
class RateLimitError(FulfilError):
    """Rate limited."""

    exit_code: int = field(default=EXIT_RATE_LIMIT)


@dataclass
class ServerError(FulfilError):
    """Server-side error."""

    exit_code: int = field(default=EXIT_SERVER)


@dataclass
class NetworkError(FulfilError):
    """Network connectivity error."""

    exit_code: int = field(default=EXIT_NETWORK)


# JSON-RPC error code → exception class mapping
JSONRPC_ERROR_MAP: dict[int, type[FulfilError]] = {
    -32700: ValidationError,  # Parse error
    -32600: ValidationError,  # Invalid request
    -32601: NotFoundError,  # Method not found
    -32602: ValidationError,  # Invalid params
    -32603: ServerError,  # Internal error
    -32000: AuthError,  # Auth error
    -32001: ForbiddenError,  # Permission denied
    -32002: NotFoundError,  # Not found
    -32003: RateLimitError,  # Rate limited
}


def error_from_jsonrpc(error: dict) -> FulfilError:
    """Create a FulfilError from a JSON-RPC error object."""
    code = error.get("code", -32603)
    message = error.get("message", "Unknown error")
    data = error.get("data", {})

    hint = None
    if isinstance(data, dict):
        hint = data.get("hint")
        # Surface additional detail from server error data
        description = data.get("description") or data.get("detail") or data.get("details")
        if description and description != message:
            message = f"{message}: {description}"
    elif isinstance(data, str) and data:
        # Some errors return data as a plain string with details
        if data != message:
            message = f"{message}: {data}"

    cls = JSONRPC_ERROR_MAP.get(code, ServerError)
    return cls(message=message, hint=hint)
