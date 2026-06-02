"""Tests for dynamic model subcommands (list/get/create/update/delete/count/call/describe)."""

from __future__ import annotations

import json

import click
import pytest
from typer.testing import CliRunner

from fulfil_cli.cli.app import app
from fulfil_cli.cli.commands.model import _parse_fields, _parse_ids, _parse_order

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestParseFields:
    def test_comma_separated(self):
        assert _parse_fields("name,state, x") == ["name", "state", "x"]

    def test_none_returns_none(self):
        assert _parse_fields(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_fields("") is None

    def test_strips_whitespace(self):
        assert _parse_fields(" foo , bar ") == ["foo", "bar"]


class TestParseIds:
    def test_single_id(self):
        assert _parse_ids("42") == [42]

    def test_multiple_ids(self):
        assert _parse_ids("1,2,3") == [1, 2, 3]

    def test_invalid_raises_exit(self):
        with pytest.raises(click.exceptions.Exit) as exc_info:
            _parse_ids("abc")
        assert exc_info.value.exit_code == 2

    def test_strips_whitespace(self):
        assert _parse_ids(" 1 , 2 ") == [1, 2]


class TestParseOrder:
    def test_with_direction(self):
        assert _parse_order("date:desc,name") == {"date": "DESC", "name": "ASC"}

    def test_default_asc(self):
        assert _parse_order("name") == {"name": "ASC"}

    def test_multiple_directions(self):
        assert _parse_order("a:asc,b:desc") == {"a": "ASC", "b": "DESC"}


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestListCommand:
    def test_happy_path(self, httpx_mock, cli_env, jsonrpc_success, pagination_response):
        records = [{"id": 1, "name": "SO001"}, {"id": 2, "name": "SO002"}]
        envelope = pagination_response(records)
        httpx_mock.add_response(json=jsonrpc_success(envelope))

        result = runner.invoke(app, ["sale_order", "list"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data["data"] == records

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["method"] == "model.sale_order.find"
        assert body["params"]["page_size"] == 20

    def test_with_where(self, httpx_mock, cli_env, jsonrpc_success, pagination_response):
        httpx_mock.add_response(json=jsonrpc_success(pagination_response([{"id": 1}])))

        result = runner.invoke(app, ["sale_order", "list", "--where", '{"state": "confirmed"}'])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["where"] == {"state": "confirmed"}

    def test_with_fields(self, httpx_mock, cli_env, jsonrpc_success, pagination_response):
        httpx_mock.add_response(json=jsonrpc_success(pagination_response([{"id": 1}])))

        result = runner.invoke(app, ["sale_order", "list", "--fields", "name,state"])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["fields"] == ["name", "state"]

    def test_with_order(self, httpx_mock, cli_env, jsonrpc_success, pagination_response):
        httpx_mock.add_response(json=jsonrpc_success(pagination_response([{"id": 1}])))

        result = runner.invoke(app, ["sale_order", "list", "--order", "date:desc,name"])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["ordering"] == {"date": "DESC", "name": "ASC"}

    def test_with_cursor(self, httpx_mock, cli_env, jsonrpc_success, pagination_response):
        httpx_mock.add_response(json=jsonrpc_success(pagination_response([{"id": 2}])))

        result = runner.invoke(app, ["sale_order", "list", "--cursor", "abc123"])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["cursor"] == "abc123"

    def test_with_limit(self, httpx_mock, cli_env, jsonrpc_success, pagination_response):
        httpx_mock.add_response(json=jsonrpc_success(pagination_response([{"id": 1}])))

        result = runner.invoke(app, ["sale_order", "list", "--limit", "50"])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["page_size"] == 50

    def test_bare_array_fallback(self, httpx_mock, cli_env, jsonrpc_success):
        """Servers returning a bare array instead of pagination envelope."""
        httpx_mock.add_response(json=jsonrpc_success([{"id": 1}, {"id": 2}]))

        result = runner.invoke(app, ["sale_order", "list"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_invalid_where_json(self, cli_env):
        result = runner.invoke(app, ["sale_order", "list", "--where", "not-json"])
        assert result.exit_code == 7


class TestGetCommand:
    def test_single_id(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success([{"id": 42, "name": "SO042"}]))

        result = runner.invoke(app, ["sale_order", "get", "42"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        # Single ID -> unwraps to single dict
        assert data == {"id": 42, "name": "SO042"}

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.serialize"
        assert body["params"] == [[42]]

    def test_multiple_ids(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success([{"id": 1}, {"id": 2}]))

        result = runner.invoke(app, ["sale_order", "get", "1,2"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_invalid_ids(self, cli_env):
        result = runner.invoke(app, ["sale_order", "get", "abc"])
        assert result.exit_code == 2


class TestCreateCommand:
    def test_single_object(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success([101]))

        result = runner.invoke(
            app,
            ["sale_order", "create"],
            input='{"name": "Test"}',
        )
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.create"
        assert body["params"]["vlist"] == [{"name": "Test"}]

    def test_array_of_objects(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success([101, 102]))

        result = runner.invoke(
            app,
            ["sale_order", "create"],
            input='[{"name": "A"}, {"name": "B"}]',
        )
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["vlist"] == [{"name": "A"}, {"name": "B"}]

    def test_invalid_json_data(self, cli_env):
        result = runner.invoke(app, ["sale_order", "create"], input="bad")
        assert result.exit_code == 7


class TestUpdateCommand:
    def test_update(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(None))

        result = runner.invoke(
            app,
            ["sale_order", "update", "1,2"],
            input='{"state": "confirmed"}',
        )
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.update"
        assert body["params"]["ids"] == [1, 2]
        assert body["params"]["values"] == {"state": "confirmed"}


class TestDeleteCommand:
    def test_with_yes_flag(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(None))

        result = runner.invoke(app, ["sale_order", "delete", "42", "--yes"])
        assert result.exit_code == 0
        assert "Deleted" in result.stderr or "Deleted" in (result.output + result.stderr)

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.delete"
        assert body["params"]["ids"] == [42]

    def test_without_yes_non_tty(self, cli_env):
        """Non-TTY without --yes should fail with exit 2."""
        result = runner.invoke(app, ["sale_order", "delete", "42"])
        assert result.exit_code == 2


class TestCountCommand:
    def test_count_json(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(42))

        result = runner.invoke(app, ["sale_order", "count"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data == {"count": 42}

    def test_count_with_where(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(5))

        result = runner.invoke(app, ["sale_order", "count", "--where", '{"state": "draft"}'])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["where"] == {"state": "draft"}


class TestCallCommand:
    def test_with_ids(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(True))

        result = runner.invoke(app, ["sale_order", "call", "confirm", "--ids", "1,2,3"])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.confirm"
        assert body["params"]["ids"] == [1, 2, 3]

    def test_with_data(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success({"ok": True}))

        result = runner.invoke(
            app,
            ["sale_order", "call", "process", "--data", '{"warehouse": 1}'],
        )
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.process"
        assert body["params"]["warehouse"] == 1

    def test_with_ids_and_data(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(True))

        result = runner.invoke(
            app,
            [
                "sale_order",
                "call",
                "process",
                "--ids",
                "42",
                "--data",
                '{"force": true}',
            ],
        )
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["ids"] == [42]
        assert body["params"]["force"] is True

    def test_data_from_file(self, httpx_mock, cli_env, jsonrpc_success, tmp_path):
        httpx_mock.add_response(json=jsonrpc_success({"ok": True}))

        payload = tmp_path / "payload.json"
        payload.write_text('{"warehouse": 7, "force": true}')

        result = runner.invoke(app, ["sale_order", "call", "process", "--data", f"@{payload}"])
        assert result.exit_code == 0, result.stdout + result.stderr

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"]["warehouse"] == 7
        assert body["params"]["force"] is True

    def test_data_file_missing(self, cli_env):
        result = runner.invoke(
            app, ["sale_order", "call", "process", "--data", "@/no/such/file.json"]
        )
        assert result.exit_code == 7
        assert "Cannot read file" in (result.stdout + result.stderr)


class TestDescribeCommand:
    def test_full_describe(self, httpx_mock, cli_env, jsonrpc_success):
        model_data = {
            "model": "sale_order",
            "description": "Sale Order",
            "fields": {"name": {"type": "char"}},
            "endpoints": [],
        }
        httpx_mock.add_response(json=jsonrpc_success(model_data))

        result = runner.invoke(app, ["sale_order", "describe"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data["model"] == "sale_order"

    def test_specific_endpoint(self, httpx_mock, cli_env, jsonrpc_success):
        model_data = {
            "model": "sale_order",
            "fields": {},
            "endpoints": [
                {"rpc_name": "find", "name": "Find", "params": []},
                {"rpc_name": "confirm", "name": "Confirm", "params": []},
            ],
        }
        httpx_mock.add_response(json=jsonrpc_success(model_data))

        result = runner.invoke(app, ["sale_order", "describe", "find"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data["rpc_name"] == "find"

    def test_endpoint_not_found(self, httpx_mock, cli_env, jsonrpc_success):
        model_data = {
            "model": "sale_order",
            "fields": {},
            "endpoints": [
                {"rpc_name": "find", "name": "Find"},
            ],
        }
        httpx_mock.add_response(json=jsonrpc_success(model_data))

        result = runner.invoke(app, ["sale_order", "describe", "nonexistent"])
        assert result.exit_code == 5


class TestErrorPaths:
    def test_server_error(self, httpx_mock, cli_env, jsonrpc_error):
        httpx_mock.add_response(json=jsonrpc_error(code=-32603, message="Internal error"))

        result = runner.invoke(app, ["sale_order", "list"])
        assert result.exit_code == 9

    def test_auth_error(self, httpx_mock, cli_env):
        httpx_mock.add_response(status_code=401, json={"error": "unauthorized"})

        result = runner.invoke(app, ["sale_order", "list"])
        assert result.exit_code == 4

    def test_validation_error_with_hint(self, httpx_mock, cli_env, jsonrpc_error):
        httpx_mock.add_response(
            json=jsonrpc_error(
                code=-32602,
                message="Invalid field",
                data={"hint": "Check field names"},
            )
        )

        result = runner.invoke(app, ["sale_order", "list"])
        assert result.exit_code == 7
