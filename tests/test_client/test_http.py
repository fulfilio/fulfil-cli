"""Tests for the JSON-RPC HTTP client."""

from __future__ import annotations

import json

import httpx
import pytest

from fulfil_cli.client.errors import (
    AuthError,
    FulfilError,
    NetworkError,
    ServerError,
    ValidationError,
)
from fulfil_cli.client.http import FulfilClient


@pytest.fixture
def client():
    return FulfilClient(
        workspace="test.fulfil.io",
        api_key="sk_test_123",
        base_url="https://test.fulfil.io",
    )


def test_client_url(client: FulfilClient):
    assert client.url == "https://test.fulfil.io/api/v3/jsonrpc"


def test_client_url_default():
    c = FulfilClient(workspace="acme.fulfil.io", api_key="sk_test")
    assert c.url == "https://acme.fulfil.io/api/v3/jsonrpc"


def test_call_success(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(json={"jsonrpc": "2.0", "result": [{"id": 1, "name": "Test"}], "id": 1})
    result = client.call("sales_order.find", where={"state": "draft"})
    assert result == [{"id": 1, "name": "Test"}]

    # Verify request payload
    request = httpx_mock.get_request()
    body = json.loads(request.content)
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "sales_order.find"
    assert body["params"] == {"where": {"state": "draft"}}


def test_call_jsonrpc_error(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(
        json={
            "jsonrpc": "2.0",
            "error": {"code": -32602, "message": "Invalid params"},
            "id": 1,
        }
    )
    with pytest.raises(ValidationError, match="Invalid params"):
        client.call("sales_order.find")


def test_call_401(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(status_code=401)
    with pytest.raises(AuthError, match="Invalid or expired credentials"):
        client.call("system.version")


def test_call_500(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(status_code=500)
    with pytest.raises(ServerError, match="Server error"):
        client.call("system.version")


def test_call_network_error(client: FulfilClient, httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
    with pytest.raises(NetworkError, match="Cannot connect"):
        client.call("system.version")


def test_batch_success(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(
        json=[
            {"jsonrpc": "2.0", "result": 5, "id": 1},
            {"jsonrpc": "2.0", "result": 10, "id": 2},
        ]
    )
    results = client.batch(
        [
            ("sales_order.count", {"where": {"state": "draft"}}),
            ("sales_order.count", {"where": {"state": "processing"}}),
        ]
    )
    assert results == [5, 10]


def test_batch_with_error(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(
        json=[
            {"jsonrpc": "2.0", "result": 5, "id": 1},
            {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Not found"}, "id": 2},
        ]
    )
    with pytest.raises(FulfilError):
        client.batch(
            [
                ("sales_order.count", {}),
                ("bad_model.count", {}),
            ]
        )


def test_call_403(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(status_code=403)
    with pytest.raises(AuthError, match="Access forbidden"):
        client.call("system.version")


def test_call_404(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(status_code=404)
    with pytest.raises(ServerError, match="not found"):
        client.call("system.version")


def test_call_500_with_detail(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(
        status_code=500,
        json={"message": "database connection lost"},
    )
    with pytest.raises(ServerError, match="database connection lost"):
        client.call("system.version")


def test_call_timeout(client: FulfilClient, httpx_mock):
    httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(NetworkError, match="timed out"):
        client.call("system.version")


def test_non_json_response(client: FulfilClient, httpx_mock):
    httpx_mock.add_response(
        status_code=200,
        text="<html>Bad Gateway</html>",
        headers={"content-type": "text/html"},
    )
    with pytest.raises(ServerError, match="Unexpected response"):
        client.call("system.version")


def test_call_positional_args(client: FulfilClient, httpx_mock):
    """Positional args are sent as a JSON array."""
    httpx_mock.add_response(json={"jsonrpc": "2.0", "result": "ok", "id": 1})
    client.call("model.sale_order.serialize", [1, 2, 3])

    body = json.loads(httpx_mock.get_request().content)
    assert body["params"] == [[1, 2, 3]]


def test_context_manager():
    client = FulfilClient(workspace="test.fulfil.io", api_key="sk_test")
    with client as c:
        assert c is client
