"""Tests for dynamic model subcommands (list/get/create/update/delete/count/call/describe)."""

from __future__ import annotations

import json

import click
import pytest
from typer.testing import CliRunner

from fulfil_cli.cli.app import app
from fulfil_cli.cli.commands.model import _parse_ids
from fulfil_cli.workspace import parse_fields, parse_order

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestParseFields:
    def test_comma_separated(self):
        assert parse_fields("name,state, x") == ["name", "state", "x"]

    def test_none_returns_none(self):
        assert parse_fields(None) is None

    def test_empty_string_returns_none(self):
        assert parse_fields("") is None

    def test_strips_whitespace(self):
        assert parse_fields(" foo , bar ") == ["foo", "bar"]


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
        assert parse_order("date:desc,name") == {"date": "DESC", "name": "ASC"}

    def test_default_asc(self):
        assert parse_order("name") == {"name": "ASC"}

    def test_multiple_directions(self):
        assert parse_order("a:asc,b:desc") == {"a": "ASC", "b": "DESC"}


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

    def test_with_fields_routes_via_find(
        self, httpx_mock, cli_env, jsonrpc_success, pagination_response
    ):
        httpx_mock.add_response(
            json=jsonrpc_success(pagination_response([{"id": 42, "settings_json": {}}]))
        )

        result = runner.invoke(app, ["sale_order", "get", "42", "--fields", "settings_json"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data == {"id": 42, "settings_json": {}}

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.find"
        assert body["params"]["where"] == {"id": {"in": [42]}}
        assert body["params"]["fields"] == ["settings_json"]
        assert body["params"]["page_size"] == 1

    def test_with_fields_preserves_input_id_order(
        self, httpx_mock, cli_env, jsonrpc_success, pagination_response
    ):
        httpx_mock.add_response(json=jsonrpc_success(pagination_response([{"id": 1}, {"id": 2}])))

        result = runner.invoke(app, ["sale_order", "get", "2,1", "--fields", "id"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert [r["id"] for r in data] == [2, 1]

    def test_with_fields_missing_id_exits_not_found(
        self, httpx_mock, cli_env, jsonrpc_success, pagination_response
    ):
        httpx_mock.add_response(json=jsonrpc_success(pagination_response([{"id": 1}])))

        result = runner.invoke(app, ["sale_order", "get", "1,999", "--fields", "id"])
        assert result.exit_code == 5
        assert "999" in result.output

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


def _endpoints(**endpoints):
    """A describe_model result whose endpoints take the given body fields."""
    return {
        "endpoints": [
            {"rpc_name": name, "body_schemas": {"Body": [{"name": f} for f in fields]}}
            for name, fields in endpoints.items()
        ]
    }


class TestCallCommand:
    def test_with_ids(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(_endpoints(confirm=["ids"])))
        httpx_mock.add_response(json=jsonrpc_success(True))

        result = runner.invoke(app, ["sale_order", "call", "confirm", "--ids", "1,2,3"])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["method"] == "model.sale_order.confirm"
        assert body["params"]["ids"] == [1, 2, 3]

    def test_ids_to_single_record_endpoint(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(_endpoints(get_attachments=["id"])))
        httpx_mock.add_response(json=jsonrpc_success([]))

        result = runner.invoke(app, ["sale_order", "call", "get_attachments", "--ids", "6"])
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["method"] == "model.sale_order.get_attachments"
        assert body["params"] == {"id": 6}

    def test_many_ids_to_single_record_endpoint(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(_endpoints(get_attachments=["id"])))

        result = runner.invoke(app, ["sale_order", "call", "get_attachments", "--ids", "6,7"])
        assert result.exit_code == 7
        assert "acts on one record" in result.output
        assert len(httpx_mock.get_requests()) == 1

    def test_with_id(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(True))

        result = runner.invoke(
            app,
            ["sale_order", "call", "add_comment", "--id", "6", "--data", '{"message": "hi"}'],
        )
        assert result.exit_code == 0

        body = json.loads(httpx_mock.get_request().content)
        assert body["params"] == {"message": "hi", "id": 6}

    def test_id_and_ids_conflict(self, cli_env):
        result = runner.invoke(app, ["sale_order", "call", "confirm", "--id", "1", "--ids", "2"])
        assert result.exit_code == 2

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
        httpx_mock.add_response(json=jsonrpc_success(_endpoints(process=["ids", "force"])))
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

        body = json.loads(httpx_mock.get_requests()[-1].content)
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


UPLOAD_URL = "https://storage.example.com/temp"
FILE_URL = "https://storage.example.com/files/po.pdf?sig=1"


class TestAttachmentCommands:
    def test_attachments_table_hides_urls(self, httpx_mock, cli_env, jsonrpc_success):
        attachment = {"id": 9, "name": "po.pdf", "mimetype": "application/pdf", "url": FILE_URL}
        httpx_mock.add_response(json=jsonrpc_success([attachment]))

        result = runner.invoke(app, ["sale_order", "attachments", "6", "--format", "table"])
        assert result.exit_code == 0
        assert "po.pdf" in result.output
        assert "storage.example.com" not in result.output

        body = json.loads(httpx_mock.get_request().content)
        assert body["method"] == "model.sale_order.get_attachments"
        assert body["params"] == {"id": 6}

    def test_attachments_download(self, httpx_mock, cli_env, jsonrpc_success, tmp_path):
        attachment = {"id": 9, "name": "po.pdf", "url": FILE_URL}
        httpx_mock.add_response(json=jsonrpc_success([attachment]))
        httpx_mock.add_response(url=FILE_URL, content=b"%PDF")

        out = tmp_path / "out"
        result = runner.invoke(
            app, ["sale_order", "attachments", "6", "--download", str(out), "--format", "json"]
        )
        assert result.exit_code == 0
        assert (out / "po.pdf").read_bytes() == b"%PDF"
        assert json.loads(result.stdout)[0]["path"] == str(out / "po.pdf")

    def test_attach_files(self, httpx_mock, cli_env, jsonrpc_success, tmp_path):
        files = []
        for name in ("a.pdf", "b.png"):
            (tmp_path / name).write_bytes(b"x")
            files.append(str(tmp_path / name))
            upload = {"method": "POST", "url": UPLOAD_URL, "fields": {"key": name}}
            started = {"upload_token": f"tok-{name}", "upload": upload, "max_bytes": 100}
            httpx_mock.add_response(json=jsonrpc_success(started))
            httpx_mock.add_response(url=UPLOAD_URL, method="POST", status_code=204)
            httpx_mock.add_response(json=jsonrpc_success({"id": len(files), "name": name}))

        result = runner.invoke(app, ["sale_order", "attach", "6", *files, "--format", "json"])
        assert result.exit_code == 0, result.output
        assert [a["name"] for a in json.loads(result.stdout)] == ["a.pdf", "b.png"]

        rpc = [json.loads(r.content) for r in httpx_mock.get_requests() if r.url != UPLOAD_URL]
        assert [r["method"].rsplit(".", 1)[1] for r in rpc] == [
            "start_attachment_upload",
            "finish_attachment_upload",
        ] * 2
        assert rpc[1]["params"] == {"id": 6, "upload_token": "tok-a.pdf"}

    def test_attach_missing_file(self, cli_env, tmp_path):
        result = runner.invoke(app, ["sale_order", "attach", "6", str(tmp_path / "nope.pdf")])
        assert result.exit_code == 2

    def test_detach_needs_yes_without_tty(self, cli_env):
        result = runner.invoke(app, ["sale_order", "detach", "6", "9"])
        assert result.exit_code == 2

    def test_detach(self, httpx_mock, cli_env, jsonrpc_success):
        httpx_mock.add_response(json=jsonrpc_success(None))
        httpx_mock.add_response(json=jsonrpc_success(None))

        result = runner.invoke(app, ["sale_order", "detach", "6", "9", "10", "--yes"])
        assert result.exit_code == 0
        params = [json.loads(r.content)["params"] for r in httpx_mock.get_requests()]
        assert params == [{"id": 6, "attachment_id": 9}, {"id": 6, "attachment_id": 10}]


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
