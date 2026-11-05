"""Tests for the describe output."""

from __future__ import annotations

from fulfil_cli.output.describe import print_endpoint_detail


def _field(name: str, *, required: bool = False) -> dict:
    return {"name": name, "type": "str", "required": required, "description": ""}


def test_shows_the_request_body_as_parameters(capsys):
    print_endpoint_detail(
        {
            "rpc_name": "publish",
            "parameters": [],
            "body_schemas": {
                "PublishParams": [_field("function", required=True), _field("version")]
            },
        },
        "custom_function",
    )

    out = capsys.readouterr().out
    assert "Parameters" in out
    assert "function" in out
    assert "version" in out
    assert "No parameters." not in out


def test_shows_models_the_request_body_references(capsys):
    print_endpoint_detail(
        {
            "rpc_name": "get_list_url",
            "body_schemas": {
                "GetListUrlParams": [_field("where")],
                "WhereClause": [_field("root", required=True)],
            },
        },
        "sales_order",
    )

    out = capsys.readouterr().out
    assert "where" in out
    assert "WhereClause" in out
    assert "root" in out
    assert "fulfil sales_order call get_list_url" in out


def test_keeps_parameters_outside_the_body(capsys):
    print_endpoint_detail(
        {"rpc_name": "find", "parameters": [_field("limit")]},
        "sales_order",
    )

    assert "limit" in capsys.readouterr().out


def test_says_so_when_there_are_no_parameters(capsys):
    print_endpoint_detail({"rpc_name": "ping", "parameters": [], "body_schemas": {}}, "system")

    assert "No parameters." in capsys.readouterr().out
