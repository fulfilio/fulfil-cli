"""Python API for a Fulfil workspace, with the same models, filters and login as the CLI.

    from fulfil_cli import Workspace

    with Workspace("acme.fulfil.io") as ws:
        orders = ws["sales_order"].find({"state": "confirmed"}, fields=["reference", "party.name"])
        ws["task"].create([{"name": "A"}, {"name": "B"}])
        ws["sales_order"].call("process", ids=[42])

`ws[name]` takes any model name `fulfil <name>` accepts. Filters use the `--where` syntax,
fields accept dotted paths, and `find` follows pagination. The CLI runs on this same API.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import Any

from fulfil_cli.auth.api_key import normalize_workspace
from fulfil_cli.client.connect import connect
from fulfil_cli.client.errors import NotFoundError
from fulfil_cli.client.http import FulfilClient

MAX_PAGE_SIZE = 500

Fields = str | Iterable[str] | None
Ids = int | Iterable[int]


def parse_order(order: str | dict[str, str]) -> dict[str, str]:
    """'sale_date:desc,name' -> {"sale_date": "DESC", "name": "ASC"}. Dicts pass through."""
    if isinstance(order, dict):
        return {field: direction.upper() for field, direction in order.items()}
    result: dict[str, str] = {}
    for part in filter(None, (p.strip() for p in order.split(","))):
        field, _, direction = part.partition(":")
        result[field.strip()] = (direction.strip() or "asc").upper()
    return result


def parse_fields(fields: Fields) -> list[str] | None:
    """'name, state' or ["name", "state"] -> ["name", "state"]. Empty means no field list."""
    if fields is None:
        return None
    if isinstance(fields, str):
        fields = fields.split(",")
    return [f.strip() for f in fields if f.strip()] or None


def _ids(ids: Ids) -> list[int]:
    return [ids] if isinstance(ids, int) else list(ids)


class Model:
    """One model in a workspace. Get it from a Workspace: ``ws["sales_order"]``."""

    def __init__(self, client: FulfilClient, name: str) -> None:
        self.client = client
        self.name = name

    def __repr__(self) -> str:
        return f"<Model {self.name} @ {self.client.workspace}>"

    def _rpc(self, method: str, *args: Any, **params: Any) -> Any:
        return self.client.call(f"model.{self.name}.{method}", *args, **params)

    def page(
        self,
        where: dict | None = None,
        *,
        fields: Fields = None,
        order: str | dict[str, str] | None = None,
        page_size: int = MAX_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict:
        """One page of matches: ``{"data": [...], "pagination": {"has_more", "next_cursor"}}``."""
        params: dict[str, Any] = {"page_size": page_size}
        if where:
            params["where"] = where
        if field_list := parse_fields(fields):
            params["fields"] = field_list
        if order:
            params["ordering"] = parse_order(order)
        if cursor:
            params["cursor"] = cursor
        return self._rpc("find", **params)

    def iter(
        self,
        where: dict | None = None,
        *,
        fields: Fields = None,
        order: str | dict[str, str] | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[dict]:
        """Yield every matching record, fetching pages as needed."""
        cursor = None
        while True:
            found = self.page(where, fields=fields, order=order, page_size=page_size, cursor=cursor)
            yield from found["data"]
            pagination = found.get("pagination") or {}
            if not pagination.get("has_more") or not (cursor := pagination.get("next_cursor")):
                return

    def find(
        self,
        where: dict | None = None,
        *,
        fields: Fields = None,
        order: str | dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Return matching records: all of them, or the first ``limit``."""
        page_size = min(limit, MAX_PAGE_SIZE) if limit else MAX_PAGE_SIZE
        records = self.iter(where, fields=fields, order=order, page_size=page_size)
        if limit is None:
            return list(records)
        return list(islice(records, limit))

    def get(self, ids: Ids, *, fields: Fields = None) -> dict | list[dict]:
        """Records by id, in the order given. One id returns one dict.

        Without ``fields`` the server returns its summary of each record.
        Raises NotFoundError if any id doesn't exist.
        """
        id_list = _ids(ids)
        if not (field_list := parse_fields(fields)):
            found = self._rpc("serialize", id_list) or []
        else:
            found = self.find({"id": {"in": id_list}}, fields=field_list, limit=len(id_list))
        by_id = {record["id"]: record for record in found}
        if missing := [str(i) for i in id_list if i not in by_id]:
            raise NotFoundError(
                message=f"No {self.name} record(s) found for ID(s): {', '.join(missing)}"
            )
        records = [by_id[i] for i in id_list]
        return records[0] if isinstance(ids, int) else records

    def count(self, where: dict | None = None) -> int:
        return self._rpc("count", **({"where": where} if where else {}))

    def create(self, records: dict | list[dict]) -> Any:
        """Create one record or many in a single call. Pass a list to batch; never loop."""
        return self._rpc("create", vlist=records if isinstance(records, list) else [records])

    def update(self, ids: Ids, values: dict) -> Any:
        """Write the same values to every id."""
        return self._rpc("update", ids=_ids(ids), values=values)

    def delete(self, ids: Ids) -> Any:
        """Permanently delete records."""
        return self._rpc("delete", ids=_ids(ids))

    def call(self, method: str, ids: Ids | None = None, **params: Any) -> Any:
        """Call an endpoint, e.g. ``ws["sales_order"].call("confirm", ids=[1, 2])``."""
        if ids is not None:
            params["ids"] = _ids(ids)
        return self._rpc(method, **params)

    def describe(self) -> dict:
        """Fields, types, allowed values and endpoints of the model."""
        return self.client.call("system.describe_model", model=self.name)


class Workspace:
    """A Fulfil workspace, authenticated the same way as ``fulfil --workspace <name>``.

    The workspace is always explicit; there is no fallback to the CLI's default workspace.
    Credentials: ``token`` > ``FULFIL_API_KEY`` > the login stored by ``fulfil auth login``.
    """

    def __init__(
        self,
        workspace: str,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        debug: bool = False,
    ) -> None:
        self.name = normalize_workspace(workspace)
        self.client = connect(
            self.name, token=token, base_url=base_url, timeout=timeout, debug=debug
        )

    def __repr__(self) -> str:
        return f"<Workspace {self.name}>"

    def __getitem__(self, name: str) -> Model:
        return Model(self.client, name)

    def whoami(self) -> dict:
        """The user these credentials act as, with their scopes."""
        return self.client.call("system.whoami")

    def models(self) -> list[dict]:
        """Every model the user can access."""
        return self.client.call("system.list_models")

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
