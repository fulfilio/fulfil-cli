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


def test_get_without_fields_missing(ws, httpx_mock):
    respond(httpx_mock, [])
    with pytest.raises(NotFoundError, match=r"ID\(s\): 8"):
        ws["task"].get(8)

    respond(httpx_mock, [{"id": 7, "rec_name": "G"}])
    with pytest.raises(NotFoundError, match=r"ID\(s\): 8$"):
        ws["task"].get([7, 8])


def describe(*endpoints):
    """A describe_model result whose endpoints take the given body fields."""
    return {
        "endpoints": [
            {"rpc_name": name, "body_schemas": {"Body": [{"name": f} for f in fields]}}
            for name, fields in endpoints
        ]
    }


def test_writes(ws, httpx_mock):
    for result in ([11, 12], None, None, describe(("done", ["ids", "note"])), {"ok": True}, 4):
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
        ("system.describe_model", {"model": "task"}),
        ("model.task.done", {"note": "x", "ids": [11]}),
        ("model.task.count", {"where": {"state": "done"}}),
    ]


def test_call_sends_id_or_ids_as_the_endpoint_takes(ws, httpx_mock):
    respond(
        httpx_mock,
        describe(
            ("confirm", ["ids"]),
            ("get_attachments", ["id"]),
            ("add_comment", ["id", "message"]),
        ),
    )
    for _ in range(4):
        respond(httpx_mock, True)

    ws["sale"].call("confirm", ids=6)
    ws["sale"].call("get_attachments", ids=[6])
    ws["sale"].call("add_comment", ids=6, message="hi")
    ws["sale"].call("unlisted", ids=[6, 7])

    calls = [(r["method"], r["params"]) for r in sent(httpx_mock)]
    assert calls == [
        ("system.describe_model", {"model": "sale"}),
        ("model.sale.confirm", {"ids": [6]}),
        ("model.sale.get_attachments", {"id": 6}),
        ("model.sale.add_comment", {"message": "hi", "id": 6}),
        ("model.sale.unlisted", {"ids": [6, 7]}),
    ]


def test_call_single_record_endpoint_rejects_many_ids(ws, httpx_mock):
    respond(httpx_mock, describe(("get_attachments", ["id"])))

    with pytest.raises(ValidationError, match="acts on one record; got 2 ids"):
        ws["sale"].call("get_attachments", ids=[6, 7])
    assert len(httpx_mock.get_requests()) == 1


def test_call_without_ids_skips_describe(ws, httpx_mock):
    respond(httpx_mock, True)
    ws["sale"].call("get_attachments", id=6)
    assert sent(httpx_mock)[0]["params"] == {"id": 6}


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


UPLOAD_URL = "https://storage.example.com/temp"
FILE_URL = "https://storage.example.com/files/po.pdf?sig=1"


def started(max_bytes=1000):
    return {
        "upload_token": "tok",
        "upload": {"method": "POST", "url": UPLOAD_URL, "fields": {"key": "k", "policy": "p"}},
        "max_bytes": max_bytes,
        "expires_at": "2026-10-24T09:00:00",
    }


def test_attach_uploads_then_finishes(ws, httpx_mock, tmp_path):
    path = tmp_path / "po.pdf"
    path.write_bytes(b"%PDF-1.7")
    respond(httpx_mock, started())
    httpx_mock.add_response(url=UPLOAD_URL, method="POST", status_code=204)
    respond(httpx_mock, {"id": 9, "name": "po.pdf"})

    assert ws["sale"].attach(6, path) == {"id": 9, "name": "po.pdf"}

    start, upload, finish = httpx_mock.get_requests()
    assert json.loads(start.content)["params"] == {"id": 6, "filename": "po.pdf"}
    assert "authorization" not in upload.headers and "x-api-key" not in upload.headers
    body = upload.content
    # Storage needs the signed fields before the file.
    assert body.index(b'name="key"') < body.index(b'name="policy"') < body.index(b'name="file"')
    assert b"%PDF-1.7" in body
    assert json.loads(finish.content)["params"] == {"id": 6, "upload_token": "tok"}


def test_attach_rejects_oversized_file_before_uploading(ws, httpx_mock, tmp_path):
    path = tmp_path / "big.zip"
    path.write_bytes(b"x" * 11)
    respond(httpx_mock, started(max_bytes=10))

    with pytest.raises(ValidationError, match="at most 10 bytes"):
        ws["sale"].attach(6, path)
    assert len(httpx_mock.get_requests()) == 1


def test_attach_storage_rejection(ws, httpx_mock, tmp_path):
    path = tmp_path / "po.pdf"
    path.write_bytes(b"x")
    respond(httpx_mock, started())
    httpx_mock.add_response(url=UPLOAD_URL, method="POST", status_code=400, text="EntityTooLarge")

    with pytest.raises(ValidationError, match=r"HTTP 400.*EntityTooLarge"):
        ws["sale"].attach(6, path)
    assert len(httpx_mock.get_requests()) == 2


def test_attachments_download_and_detach(ws, httpx_mock, tmp_path):
    attachment = {"id": 9, "name": "po.pdf", "url": FILE_URL}
    respond(httpx_mock, [attachment])
    httpx_mock.add_response(url=FILE_URL, content=b"%PDF")
    httpx_mock.add_response(url=FILE_URL, content=b"%PDF")
    respond(httpx_mock, None)

    assert ws["sale"].attachments(6) == [attachment]
    assert ws["sale"].download(attachment, tmp_path) == tmp_path / "po.pdf"
    # A name already taken falls back to <id>-<name> instead of overwriting.
    assert ws["sale"].download(attachment, tmp_path) == tmp_path / "9-po.pdf"
    assert (tmp_path / "9-po.pdf").read_bytes() == b"%PDF"
    ws["sale"].detach(6, 9)

    calls = [json.loads(r.content) for r in httpx_mock.get_requests() if r.url == URL]
    assert [(c["method"], c["params"]) for c in calls] == [
        ("model.sale.get_attachments", {"id": 6}),
        ("model.sale.delete_attachment", {"id": 6, "attachment_id": 9}),
    ]


def test_download_never_overwrites(ws, tmp_path):
    (tmp_path / "po.pdf").write_bytes(b"mine")
    with pytest.raises(ValidationError, match="already exists"):
        ws["sale"].download({"id": 9, "name": "po.pdf", "url": FILE_URL}, tmp_path / "po.pdf")
    assert (tmp_path / "po.pdf").read_bytes() == b"mine"
