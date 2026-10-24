---
name: fulfil
description: Read and change data in a Fulfil ERP workspace with the fulfil CLI. Use when the user asks about Fulfil records such as sales orders, products, shipments, customers or inventory, or mentions the fulfil command.
license: MIT
---

# Fulfil

Use the `fulfil` CLI to work with a Fulfil workspace. Pass `--format json` for output you parse.
Data goes to stdout and errors go to stderr.

## Before anything else

1. `fulfil whoami --format json` checks the login. If it fails, ask the user to run
   `fulfil auth login`, or to set `FULFIL_API_KEY` and `FULFIL_WORKSPACE`.
2. Never guess a model name, even a common one. Run `fulfil models --search <term> --format json`
   and use the exact `model_name` from the result. Run `fulfil models --format json` if the
   search finds nothing.
3. `fulfil <model> describe --format json` lists the model's fields and methods. Take field
   names from it. `fulfil <model> describe <method>` shows a method's parameters.

## Reading

- `fulfil <model> list --where '<json>' --fields <a,b> --order <field:desc>`
- `--where` is MongoDB-style: `{"state": "confirmed"}`, `{"sale_date": {"gte": "2025-01-01"}}`,
  `{"or": [{...}, {...}]}`. Operators: gt, gte, lt, lte, ne, in, not_in, contains,
  startswith, endswith. `--fields` accepts dotted paths such as `party.name`.
- `list` returns one page: `{"data": [...], "pagination": {"has_more": true, "next_cursor": "..."}}`.
  While `has_more` is true, get the next page by passing the `next_cursor` token:
  `--cursor <next_cursor>` with the same `--where`, `--fields` and `--order`.
- Page only with the cursor token. Don't page with offsets, and don't raise `--limit` to
  fetch everything at once. `--limit` is only the page size (20 by default, at most 500).
- `fulfil <model> count --where '<json>'` gives totals. Don't count by listing.
- `fulfil <model> get <id,id>` returns records by id. Add `--fields` for specific fields.

## Before you change anything

Run `fulfil <model> describe` first. It lists the required fields and the methods you can call.

Confirm destructive changes first: deleting, cancelling, processing or posting anything,
changing many records at once, or touching settings, users or accounting.

1. Read the records involved and work out exactly what will change.
2. Tell the user: the records (by number or name, not only id), each field's value before
   and after, and what follows from it (emails sent, stock moved, entries posted).
3. Make the change only after they confirm, and only that change. A confirmation covers
   what you described, nothing more.

A small, clearly requested change, such as fixing a typo in a name, can go ahead without
asking. Say what you changed. When unsure, ask.

After any change, read the records back and report what is there now.

## Writing

- `create` and `update` read JSON from stdin or a file:
  `echo '<json>' | fulfil <model> create`, `echo '<json>' | fulfil <model> update <id,id>`.
- Create many records with one JSON array in a single `create`. Never loop single creates.
- Never change a state field with `update`. Call the workflow method from `describe` instead:
  `fulfil <model> call <method> --ids <id,id> --data '<json of other parameters>'`.
- `delete` needs `--yes` when there is no terminal: `fulfil <model> delete <id,id> --yes`.

### Fields that hold lists of records

`describe` shows them with type `Record IDs`, and `relation_model` names the model of the
records in the list (an order's `lines`, a contact's `categories`). Despite the type name,
write them with an object of actions, never a list of ids. A list of ids fails with a server error
("'int' object is not subscriptable"), not a validation error.

```bash
echo '{"<field>": {"add": [94, 16]}}' | fulfil <model> update <id>
echo '{"<field>": {"remove": [34]}}' | fulfil <model> update <id>
echo '{"<field>": {"create": [{"product": 7, "quantity": 2}]}}' | fulfil <model> update <id>
echo '{"<field>": {"update": [{"ids": [881], "values": {"quantity": 3}}]}}' | fulfil <model> update <id>
```

- `add` and `remove` link and unlink existing records. The records themselves stay as
  they were.
- `create` makes new records in the field. `update` changes some of them.
- `delete` deletes the records themselves, not only the link. On a list of users it
  would try to delete the users. To take a record off a list, use `remove`.
- One object can hold several actions: `{"add": [...], "remove": [...]}`.

## Files

- `fulfil <model> attachments <id>` lists a record's files. Add `--download <dir>` to save
  them. Download links expire within an hour, so download right away and never keep a link.
- `fulfil <model> attach <id> <file> [<file>...]` uploads files and attaches them. Use it
  instead of calling `start_attachment_upload` and `finish_attachment_upload` yourself.
  Files are limited to 25 MB unless the model sets its own limit, and some types, such as
  `.exe`, are refused.
- `fulfil <model> detach <id> <attachment_id> --yes` deletes a file for good. Confirm first.

## Errors

Exit codes: 2 bad arguments, 3 config, 4 auth, 5 not found, 6 forbidden, 7 validation,
8 rate limited, 9 server, 10 network. A validation error names the field at fault.

Read the error and fix what you can. Don't retry the same failing call. If you can't
make the change, say plainly what you couldn't do and why.

## Python

For multi-step work, use the library instead of many CLI calls. `find()` follows the cursor
for you:

```python
from fulfil_cli import Workspace

with Workspace("<workspace>.fulfil.io") as ws:
    rows = ws["<model>"].find({"state": "draft"}, fields="id,party.name")
```
