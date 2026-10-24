"""Tests for error hierarchy and JSON-RPC error mapping."""

from fulfil_cli.client.errors import (
    EXIT_AUTH,
    EXIT_FORBIDDEN,
    EXIT_NOT_FOUND,
    EXIT_RATE_LIMIT,
    EXIT_SERVER,
    EXIT_VALIDATION,
    ApplicationError,
    AuthError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
    error_from_jsonrpc,
)


def test_error_from_jsonrpc_auth():
    err = error_from_jsonrpc({"code": -32000, "message": "Invalid key"})
    assert isinstance(err, AuthError)
    assert err.exit_code == EXIT_AUTH
    assert "Invalid key" in str(err)


def test_error_from_jsonrpc_validation():
    err = error_from_jsonrpc(
        {
            "code": -32602,
            "message": "Unknown field: 'totl_amount'",
            "data": {"hint": "Did you mean 'total_amount'?"},
        }
    )
    assert isinstance(err, ValidationError)
    assert err.exit_code == EXIT_VALIDATION
    assert err.hint == "Did you mean 'total_amount'?"


def test_error_from_jsonrpc_not_found():
    err = error_from_jsonrpc({"code": -32601, "message": "Method not found"})
    assert isinstance(err, NotFoundError)
    assert err.exit_code == EXIT_NOT_FOUND


def test_error_from_jsonrpc_permission():
    err = error_from_jsonrpc({"code": -32001, "message": "Forbidden"})
    assert isinstance(err, ForbiddenError)
    assert err.exit_code == EXIT_FORBIDDEN


def test_error_from_jsonrpc_rate_limit():
    err = error_from_jsonrpc({"code": -32003, "message": "Too many requests"})
    assert isinstance(err, RateLimitError)
    assert err.exit_code == EXIT_RATE_LIMIT


def test_error_from_jsonrpc_application_error():
    # A business rule refusing the request (UserError on the server) is the caller's to fix.
    err = error_from_jsonrpc(
        {
            "code": -32010,
            "message": "File type not allowed",
            "data": {"description": "`.exe` files can't be attached: `tool.exe`", "code": "E1000"},
        }
    )
    assert isinstance(err, ApplicationError)
    assert isinstance(err, ValidationError)
    assert err.exit_code == EXIT_VALIDATION
    assert "tool.exe" in err.message


def test_error_from_jsonrpc_unknown_code():
    err = error_from_jsonrpc({"code": -99999, "message": "Unknown"})
    assert isinstance(err, ServerError)
    assert err.exit_code == EXIT_SERVER
