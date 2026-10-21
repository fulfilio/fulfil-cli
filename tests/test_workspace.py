"""Tests for the Python library API (fulfil_cli.Workspace)."""

from __future__ import annotations

import json

import pytest

import fulfil_cli
from fulfil_cli import Workspace
from fulfil_cli.client.errors import NotFoundError, ValidationError
from fulfil_cli.workspace import parse_order

URL = "https://acme.fulfil.io/api/v3/jsonrpc"


@pytest.fixture
def ws(monkeypatch):
    monkeypatch.setenv("FULFIL_API_KEY", "sk_test")
    monkeypatch.delenv("FULFIL_WORKSPACE", raising=False)
    with Workspace("acme") as workspace:
        yield workspace


def page(data, cursor=None):
    return {"data": data, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}}


def respond(httpx_mock, result):
    httpx_mock.add_response(url=URL, json={"jsonrpc": "2.0", "result": result, "id": 1})


def sent(httpx_mock):
    return [json.loads(r.content) for r in httpx_mock.get_requests()]


def test_exports():
    assert fulfil_cli.Workspace is Workspace
    assert issubclass(fulfil_cli.FulfilError, Exception)


def test_workspace_is_explicit_and_normalized(ws, monkeypatch):
    monkeypatch.setenv("FULFIL_WORKSPACE", "other.fulfil.io")
    assert ws.name == "acme.fulfil.io"
    assert ws.client.url == URL
    assert Workspace("beta.fulfil.app").name == "beta.fulfil.app"


def test_models_by_attribute_and_item(ws):
    assert ws["sales_order"].name == "sales_order"
    assert ws["fiscal_year"].name == "fiscal_year"
    with pytest.raises(AttributeError):
        ws._private  # noqa: B018


def test_find_follows_pagination(ws, httpx_mock):
    respond(httpx_mock, page([{"id": 1}, {"id": 2}], cursor="c1"))
    respond(httpx_mock, page([{"id": 3}]))

    records = ws["task"].find(
        {"state": "open"}, fields="id, name,owner.name", order="due_date:desc,name"
    )

    assert [r["id"] for r in records] == [1, 2, 3]
    first, second = sent(httpx_mock)
    assert first["method"] == "model.task.find"
    assert first["params"] == {
        "page_size": 500,
        "where": {"state": "open"},
        "fields": ["id", "name", "owner.name"],
        "ordering": {"due_date": "DESC", "name": "ASC"},
    }
    assert second["params"]["cursor"] == "c1"


def test_find_limit_stops_early(ws, httpx_mock):
    respond(httpx_mock, page([{"id": 1}, {"id": 2}], cursor="c1"))

    assert ws["task"].find(limit=2) == [{"id": 1}, {"id": 2}]
    assert len(httpx_mock.get_requests()) == 1
    assert sent(httpx_mock)[0]["params"]["page_size"] == 2


def test_get_with_fields_keeps_order(ws, httpx_mock):
    respond(httpx_mock, page([{"id": 2, "name": "B"}, {"id": 1, "name": "A"}]))

    assert ws["task"].get([1, 2], fields=["name"]) == [
        {"id": 1, "name": "A"},
        {"id": 2, "name": "B"},
    ]
    assert sent(httpx_mock)[0]["params"]["where"] == {"id": {"in": [1, 2]}}


def test_get_single_id_and_missing(ws, httpx_mock):
    respond(httpx_mock, page([{"id": 7, "name": "G"}]))
    assert ws["task"].get(7, fields="name") == {"id": 7, "name": "G"}

    respond(httpx_mock, page([]))
    with pytest.raises(NotFoundError, match=r"ID\(s\): 8"):
        ws["task"].get(8, fields="name")


def test_get_without_fields_serializes(ws, httpx_mock):
    respond(httpx_mock, [{"id": 7, "rec_name": "G"}])
    assert ws["task"].get(7) == {"id": 7, "rec_name": "G"}
    assert sent(httpx_mock)[0] == {
        "jsonrpc": "2.0",
        "method": "model.task.serialize",
        "params": [[7]],
        "id": 1,
    }


def test_writes(ws, httpx_mock):
    for result in ([11, 12], None, None, {"ok": True}, 4):
        respond(httpx_mock, result)

    assert ws["task"].create([{"name": "A"}, {"name": "B"}]) == [11, 12]
    ws["task"].update([11, 12], {"owner": 5})
    ws["task"].delete(12)
    assert ws["task"].call("done", ids=11, note="x") == {"ok": True}
    assert ws["task"].count({"state": "done"}) == 4

    calls = [(r["method"], r["params"]) for r in sent(httpx_mock)]
    assert calls == [
        ("model.task.create", {"vlist": [{"name": "A"}, {"name": "B"}]}),
        ("model.task.update", {"ids": [11, 12], "values": {"owner": 5}}),
        ("model.task.delete", {"ids": [12]}),
        ("model.task.done", {"note": "x", "ids": [11]}),
        ("model.task.count", {"where": {"state": "done"}}),
    ]


def test_create_single_record_is_batched(ws, httpx_mock):
    respond(httpx_mock, [11])
    ws["task"].create({"name": "A"})
    assert sent(httpx_mock)[0]["params"] == {"vlist": [{"name": "A"}]}


def test_system_calls(ws, httpx_mock):
    respond(httpx_mock, {"id": 1, "name": "Me"})
    respond(httpx_mock, {"fields": []})
    assert ws.whoami()["name"] == "Me"
    assert ws["task"].describe() == {"fields": []}
    methods = [(r["method"], r["params"]) for r in sent(httpx_mock)]
    assert methods == [("system.whoami", {}), ("system.describe_model", {"model": "task"})]


def test_errors_propagate(ws, httpx_mock):
    httpx_mock.add_response(
        url=URL,
        json={"jsonrpc": "2.0", "error": {"code": -32602, "message": "bad field"}, "id": 1},
    )
    with pytest.raises(ValidationError):
        ws["task"].find(fields="nope")


def test_parse_order():
    assert parse_order("a:desc,b") == {"a": "DESC", "b": "ASC"}
    assert parse_order({"a": "desc"}) == {"a": "DESC"}
