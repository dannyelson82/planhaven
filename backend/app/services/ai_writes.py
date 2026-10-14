"""What an AI app's write tools do (A§12.3, ADR 0019, 0020): for each tool, `plan` checks the
arguments and that the person may do it now, without doing it; `apply` does it as the person
(the services check their rights again) and says how to undo it. `undo` reverses one change.

Deletes go to the Trash (30 days) and their Undo restores them; edits keep the values they
overwrote. Never more than the person could do: every call runs through the normal services
(authz + RLS). local_ai_only projects stay invisible (ai_base.project).
"""

import contextlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app import authz
from app.db import projects as project_store
from app.db.database import Database
from app.services import asset_service, sharing, trash
from app.services import assets as asset_svc
from app.services import attachments as attachment_service
from app.services import contacts as contact_service
from app.services import costs as cost_service
from app.services import lists as list_service
from app.services import note_content as content
from app.services import notes as note_service
from app.services import projects as project_service
from app.services.ai_base import (
    STAGES,
    Done,
    Plan,
    ToolError,
    bool_arg,
    choice_arg,
    date_arg,
    editable,
    id_arg,
    money_arg,
    names,
    number_arg,
    optional_id,
    project,
    text_arg,
)
from app.services.auth import CurrentSession

LIST_KINDS = ("shopping", "parts", "checklist")
QUOTE_STATUSES = ("requested", "received", "accepted", "declined")
CONTACT_KINDS = ("contractor", "supplier", "other")
ASSET_KINDS = ("vehicle", "boat", "house", "property", "equipment", "tool", "other")
MEMBER_ROLES = ("editor", "viewer", "none")
DELETABLE = (
    "project",
    "task",
    "note",
    "list",
    "list_item",
    "file",
    "quote",
    "cost",
    "contact",
    "asset",
    "reading",
    "service_schedule",
    "service_record",
)
# Kinds the Trash restores (app.services.trash), by the name the tool uses.
_TRASH_KIND: dict[str, trash.Kind] = {
    "project": "project",
    "task": "task",
    "note": "note",
    "list": "list",
    "file": "attachment",
    "quote": "quote",
    "cost": "cost",
    "contact": "contact",
    "asset": "asset",
}
_WEBSITE = re.compile(r"^(https?://\S*)?$")
_UNDO_LIMIT = 60_000  # ai_changes.undo holds at most 64 KiB

Planner = Callable[[Database, CurrentSession, dict[str, Any]], Awaitable[Plan]]
Applier = Callable[[Database, CurrentSession, Plan, str], Awaitable[Done]]
Undoer = Callable[[Database, CurrentSession, dict[str, Any]], Awaitable[None]]
PLANNERS: dict[str, Planner] = {}
APPLIERS: dict[str, Applier] = {}
UNDOERS: dict[str, Undoer] = {}
IP = None  # AI calls come from the app's servers; audit rows carry the person, not an address


class CannotUndoError(ToolError):
    """The change can't be reversed any more (the thing is gone for good, or was restored)."""


def _plans(name: str) -> Callable[[Planner], Planner]:
    def register(fn: Planner) -> Planner:
        PLANNERS[name] = fn
        return fn

    return register


def _applies(name: str) -> Callable[[Applier], Applier]:
    def register(fn: Applier) -> Applier:
        APPLIERS[name] = fn
        return fn

    return register


def _undoes(kind: str) -> Callable[[Undoer], Undoer]:
    def register(fn: Undoer) -> Undoer:
        UNDOERS[kind] = fn
        return fn

    return register


def _plain(value: Any) -> Any:
    """JSON-safe (plans and undo records are stored as JSON)."""
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _uid(value: str | None) -> uuid.UUID | None:
    return None if value is None else uuid.UUID(value)


def _changed(fields: dict[str, Any]) -> str:
    return ", ".join(k.replace("_", " ") for k in fields)


def _need_some(changes: dict[str, Any], what: str) -> None:
    if not changes:
        raise ToolError(f"Give at least one of: {what}.")


async def _task(db: Database, session: CurrentSession, task_id: uuid.UUID) -> Any:
    async with db.user_transaction(session.user.id) as conn:
        task = await project_store.get_task(conn, task_id)
    if task is None:
        raise authz.NotFoundError("Not found.")
    return task


async def _item(db: Database, session: CurrentSession, item_id: uuid.UUID) -> tuple[Any, Any]:
    """A list item and its list."""
    list_id = await list_service.list_of_item(db, session, item_id)
    lst, items = await list_service.get_list(db, session, list_id)
    for item in items:
        if item.id == item_id:
            return item, lst
    raise authz.NotFoundError("Not found.")


async def _asset(db: Database, session: CurrentSession, asset_id: uuid.UUID) -> Any:
    row, _ = await asset_svc.get_asset(db, session, asset_id)
    return row


def _asset_edit(session: CurrentSession, row: Any) -> None:
    authz.require(session.principal, authz.Action.ASSET_EDIT, authz.ProjectAccess(row.role))


async def _quietly(action: Awaitable[Any]) -> None:
    """For undoing an add: already deleted is fine."""
    with contextlib.suppress(authz.NotFoundError):
        await action


# ---------------------------------------------------------------- projects


@_plans("planhaven_create_project")
async def _plan_create_project(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    title = text_arg(args, "title", 200)
    description = text_arg(args, "description", 20000, required=False)
    return Plan(
        "planhaven_create_project",
        None,
        {"title": title, "description": description},
        f"New project “{title}”",
    )


@_applies("planhaven_create_project")
async def _create_project(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    row = await project_service.create_project(
        db, s, title=a["title"], description=a["description"], stage="idea", ip=IP
    )
    return Done({"project_id": str(row.id)}, "project_created", {"project_id": str(row.id)})


@_undoes("project_created")
async def _undo_create_project(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(project_service.delete_project(db, s, uuid.UUID(u["project_id"]), IP))


@_plans("planhaven_update_project")
async def _plan_update_project(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    pid = id_arg(args, "project_id")
    p = await editable(db, s, pid)
    change: dict[str, Any] = {}
    if args.get("title") is not None:
        change["title"] = text_arg(args, "title", 200)
    if args.get("description") is not None:
        change["description"] = text_arg(args, "description", 20000, required=False)
    if args.get("stage") is not None:
        change["stage"] = choice_arg(args, "stage", STAGES)
    _need_some(change, "title, description, stage")
    return Plan(
        "planhaven_update_project",
        pid,
        {"project_id": str(pid), **change},
        f"Change {_changed(change)} of “{p.title}”",
    )


@_applies("planhaven_update_project")
async def _update_project(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    pid = uuid.UUID(a["project_id"])
    before = await project(db, s, pid)
    await project_service.update_project(
        db,
        s,
        pid,
        expected_version=before.version,
        title=a.get("title"),
        description=a.get("description"),
        stage=a.get("stage"),
        local_ai_only=None,
        ip=IP,
    )
    previous = {k: getattr(before, k) for k in ("title", "description", "stage") if k in a}
    return Done(
        {"project_id": str(pid)}, "project_updated", {"project_id": str(pid), "before": previous}
    )


@_undoes("project_updated")
async def _undo_update_project(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    pid = uuid.UUID(u["project_id"])
    now = await project_service.get_project(db, s, pid)
    before = u["before"]
    await project_service.update_project(
        db,
        s,
        pid,
        expected_version=now.version,
        title=before.get("title"),
        description=before.get("description"),
        stage=before.get("stage"),
        local_ai_only=None,
        ip=IP,
    )


# ---------------------------------------------------------------- notes


@_plans("planhaven_add_note")
async def _plan_add_note(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    pid = id_arg(args, "project_id")
    p = await editable(db, s, pid)
    title = text_arg(args, "title", 200)
    body = text_arg(args, "text", 20000)
    return Plan(
        "planhaven_add_note",
        pid,
        {"project_id": str(pid), "title": title, "text": body},
        f"Add the note “{title}” to “{p.title}”",
    )


@_applies("planhaven_add_note")
async def _add_note(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    pid = uuid.UUID(a["project_id"])
    await project(db, s, pid)
    note = await note_service.create_note(db, s, pid, a["title"], IP, source=f"mcp:{client}")
    saved = await note_service.save(
        db,
        s,
        note.id,
        expected_version=note.version,
        title=a["title"],
        document=content.from_text(a["text"]),
        ip=IP,
    )
    return Done({"note_id": str(saved.id)}, "note_added", {"note_id": str(saved.id)})


@_undoes("note_added")
async def _undo_add_note(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(note_service.delete_note(db, s, uuid.UUID(u["note_id"]), IP))


@_plans("planhaven_update_note")
async def _plan_update_note(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    nid = id_arg(args, "note_id")
    note, _, _ = await note_service.get_note(db, s, nid)
    p = await editable(db, s, note.project_id)
    change: dict[str, Any] = {}
    if args.get("title") is not None:
        change["title"] = text_arg(args, "title", 200)
    if args.get("text") is not None:
        change["text"] = text_arg(args, "text", 20000, required=False)
    if args.get("archived") is not None:
        change["archived"] = bool_arg(args, "archived")
    _need_some(change, "title, text, archived")
    return Plan(
        "planhaven_update_note",
        p.id,
        {"note_id": str(nid), **change},
        f"Change {_changed(change)} of the note “{note.title}” in “{p.title}”",
    )


@_applies("planhaven_update_note")
async def _update_note(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    nid = uuid.UUID(a["note_id"])
    note, _, document = await note_service.get_note(db, s, nid)
    await project(db, s, note.project_id)
    before: dict[str, Any] = {}
    if "archived" in a:
        before["archived"] = note.archived_at is not None
    if "title" in a or "text" in a:
        before["title"] = note.title
        before["document"] = document
        if len(json.dumps(document, default=str)) > _UNDO_LIMIT:
            raise ToolError("This note is too long to change here (it couldn't be undone).")
        await note_service.save(
            db,
            s,
            nid,
            expected_version=note.version,
            title=a.get("title", note.title),
            document=content.from_text(a["text"]) if "text" in a else document,
            ip=IP,
        )
    if "archived" in a:
        await note_service.set_archived(db, s, nid, a["archived"], IP)
    return Done({"note_id": str(nid)}, "note_updated", {"note_id": str(nid), "before": before})


@_undoes("note_updated")
async def _undo_update_note(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    nid = uuid.UUID(u["note_id"])
    before = u["before"]
    if "document" in before:
        note, _, _ = await note_service.get_note(db, s, nid)
        await note_service.save(
            db,
            s,
            nid,
            expected_version=note.version,
            title=before["title"],
            document=before["document"],
            ip=IP,
        )
    if "archived" in before:
        await note_service.set_archived(db, s, nid, before["archived"], IP)


# ---------------------------------------------------------------- tasks


def _task_fields(t: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(t, dict):
        raise ToolError("Each task has a 'title'.")
    return {
        "title": text_arg(t, "title", 300),
        "notes": text_arg(t, "notes", 5000, required=False),
        "due_date": date_arg(t, "due_date") if t.get("due_date") else "",
    }


def _due(day: str | None) -> datetime | None:
    if not day:
        return None
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC)


@_plans("planhaven_add_tasks")
async def _plan_add_tasks(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    pid = id_arg(args, "project_id")
    p = await editable(db, s, pid)
    raw = args.get("tasks")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ToolError("'tasks' is a list of 1 to 50 tasks.")
    tasks = [_task_fields(t) for t in raw]
    n = len(tasks)
    return Plan(
        "planhaven_add_tasks",
        pid,
        {"project_id": str(pid), "tasks": tasks},
        f"Add {n} task{'s' if n != 1 else ''} to “{p.title}”: {names([t['title'] for t in tasks])}",
    )


@_applies("planhaven_add_tasks")
async def _add_tasks(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    pid = uuid.UUID(a["project_id"])
    await project(db, s, pid)
    ids = []
    for t in a["tasks"]:
        due = _due(t["due_date"])
        row = await project_service.create_task(
            db,
            s,
            pid,
            title=t["title"],
            notes=t["notes"],
            due_at=due,
            due_all_day=due is not None,
            ip=IP,
        )
        ids.append(str(row.id))
    return Done({"task_ids": ids}, "tasks_added", {"task_ids": ids})


@_undoes("tasks_added")
async def _undo_add_tasks(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    for tid in u["task_ids"]:
        await _quietly(project_service.delete_task(db, s, uuid.UUID(tid), IP))


async def _set_task(
    db: Database, s: CurrentSession, task_id: uuid.UUID, change: dict[str, Any]
) -> Any:
    """Change some of a task's fields (title, notes, due_at + due_all_day, done)."""
    task = await _task(db, s, task_id)
    await project(db, s, task.project_id)
    return await project_service.update_task(
        db,
        s,
        task_id,
        expected_version=task.version,
        title=change.get("title"),
        notes=change.get("notes"),
        set_due="due_at" in change,
        due_at=_parse_due(change.get("due_at")),
        due_all_day=change.get("due_all_day"),
        done=change.get("done"),
        ip=IP,
        base={"done": task.done_at is not None},
    )


def _parse_due(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


@_plans("planhaven_complete_task")
async def _plan_complete_task(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    tid = id_arg(args, "task_id")
    task = await _task(db, s, tid)
    p = await editable(db, s, task.project_id)
    return Plan(
        "planhaven_complete_task",
        p.id,
        {"task_id": str(tid)},
        f"Mark “{task.title}” done in “{p.title}”",
    )


@_applies("planhaven_complete_task")
async def _complete_task(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    tid = uuid.UUID(p.arguments["task_id"])
    await _set_task(db, s, tid, {"done": True})
    return Done({"task_id": str(tid), "done": True}, "task_completed", {"task_id": str(tid)})


@_undoes("task_completed")
async def _undo_complete_task(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_task(db, s, uuid.UUID(u["task_id"]), {"done": False})


@_plans("planhaven_update_task")
async def _plan_update_task(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    tid = id_arg(args, "task_id")
    task = await _task(db, s, tid)
    p = await editable(db, s, task.project_id)
    change: dict[str, Any] = {}
    if args.get("title") is not None:
        change["title"] = text_arg(args, "title", 300)
    if args.get("notes") is not None:
        change["notes"] = text_arg(args, "notes", 5000, required=False)
    if "due_date" in args:
        change["due_date"] = date_arg(args, "due_date") if args["due_date"] else None
    if args.get("done") is not None:
        change["done"] = bool_arg(args, "done")
    _need_some(change, "title, notes, due_date, done")
    return Plan(
        "planhaven_update_task",
        p.id,
        {"task_id": str(tid), **change},
        f"Change {_changed(change)} of the task “{task.title}” in “{p.title}”",
    )


@_applies("planhaven_update_task")
async def _update_task(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    tid = uuid.UUID(a["task_id"])
    task = await _task(db, s, tid)
    change: dict[str, Any] = {k: a[k] for k in ("title", "notes", "done") if k in a}
    before: dict[str, Any] = {k: getattr(task, k) for k in ("title", "notes") if k in a}
    if "done" in a:
        before["done"] = task.done_at is not None
    if "due_date" in a:
        due = _due(a["due_date"])
        change["due_at"] = _plain(due)
        change["due_all_day"] = due is not None
        before["due_at"] = _plain(task.due_at)
        before["due_all_day"] = task.due_all_day
    await _set_task(db, s, tid, change)
    return Done({"task_id": str(tid)}, "task_updated", {"task_id": str(tid), "before": before})


@_undoes("task_updated")
async def _undo_update_task(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_task(db, s, uuid.UUID(u["task_id"]), u["before"])


# ---------------------------------------------------------------- lists and items


@_plans("planhaven_add_list")
async def _plan_add_list(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    pid = id_arg(args, "project_id")
    p = await editable(db, s, pid)
    title = text_arg(args, "title", 200)
    kind = choice_arg(args, "kind", LIST_KINDS) if "kind" in args else "checklist"
    return Plan(
        "planhaven_add_list",
        pid,
        {"project_id": str(pid), "title": title, "kind": kind},
        f"Add the {kind} list “{title}” to “{p.title}”",
    )


@_applies("planhaven_add_list")
async def _add_list(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    pid = uuid.UUID(a["project_id"])
    await project(db, s, pid)
    row = await list_service.create_list(db, s, pid, title=a["title"], kind=a["kind"], ip=IP)
    return Done({"list_id": str(row.id)}, "list_added", {"list_id": str(row.id)})


@_undoes("list_added")
async def _undo_add_list(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(list_service.delete_list(db, s, uuid.UUID(u["list_id"]), IP))


@_plans("planhaven_update_list")
async def _plan_update_list(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    lid = id_arg(args, "list_id")
    lst, _ = await list_service.get_list(db, s, lid)
    p = await editable(db, s, lst.project_id)
    change: dict[str, Any] = {}
    if args.get("title") is not None:
        change["title"] = text_arg(args, "title", 200)
    if args.get("kind") is not None:
        change["kind"] = choice_arg(args, "kind", LIST_KINDS)
    _need_some(change, "title, kind")
    return Plan(
        "planhaven_update_list",
        p.id,
        {"list_id": str(lid), **change},
        f"Change {_changed(change)} of the list “{lst.title}” in “{p.title}”",
    )


async def _set_list(db: Database, s: CurrentSession, lid: uuid.UUID, change: dict[str, Any]) -> Any:
    lst, _ = await list_service.get_list(db, s, lid)
    await project(db, s, lst.project_id)
    await list_service.update_list(
        db,
        s,
        lid,
        expected_version=lst.version,
        title=change.get("title"),
        kind=change.get("kind"),
        ip=IP,
    )
    return lst


@_applies("planhaven_update_list")
async def _update_list(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    lid = uuid.UUID(a["list_id"])
    change: dict[str, Any] = {k: a[k] for k in ("title", "kind") if k in a}
    lst = await _set_list(db, s, lid, change)
    before = {k: getattr(lst, k) for k in change}
    return Done({"list_id": str(lid)}, "list_updated", {"list_id": str(lid), "before": before})


@_undoes("list_updated")
async def _undo_update_list(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_list(db, s, uuid.UUID(u["list_id"]), u["before"])


def _item_fields(i: Any) -> dict[str, Any]:
    if not isinstance(i, dict):
        raise ToolError("Each item has a 'text'.")
    qty = None
    if i.get("quantity") is not None:
        qty = number_arg(i, "quantity", low=Decimal(0), high=Decimal(999999999), places=3)
    return {"text": text_arg(i, "text", 500), "quantity": qty}


@_plans("planhaven_add_list_items")
async def _plan_add_items(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    lid = id_arg(args, "list_id")
    lst, _ = await list_service.get_list(db, s, lid)
    p = await editable(db, s, lst.project_id)
    raw = args.get("items")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
        raise ToolError("'items' is a list of 1 to 100 items.")
    items = [_item_fields(i) for i in raw]
    n = len(items)
    return Plan(
        "planhaven_add_list_items",
        p.id,
        {"list_id": str(lid), "items": items},
        f"Add {n} item{'s' if n != 1 else ''} to the list “{lst.title}” in “{p.title}”: "
        f"{names([str(i['text']) for i in items])}",
    )


@_applies("planhaven_add_list_items")
async def _add_items(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    lid = uuid.UUID(a["list_id"])
    lst, _ = await list_service.get_list(db, s, lid)
    await project(db, s, lst.project_id)
    ids = []
    for i in a["items"]:
        row = await list_service.add_item(
            db,
            s,
            lid,
            text=i["text"],
            quantity=_dec(i["quantity"]),
            unit=None,
            price_cents=None,
            idempotency_key=None,
            ip=IP,
        )
        ids.append(str(row.id))
    return Done({"item_ids": ids}, "items_added", {"item_ids": ids})


@_undoes("items_added")
async def _undo_add_items(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    for iid in u["item_ids"]:
        await _quietly(list_service.delete_item(db, s, uuid.UUID(iid), IP))


@_plans("planhaven_update_list_item")
async def _plan_update_item(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    iid = id_arg(args, "item_id")
    item, lst = await _item(db, s, iid)
    p = await editable(db, s, lst.project_id)
    change: dict[str, Any] = {}
    if args.get("text") is not None:
        change["text"] = text_arg(args, "text", 500)
    if "quantity" in args:
        change["quantity"] = _item_fields({"text": "-", "quantity": args["quantity"]})["quantity"]
    if args.get("notes") is not None:
        change["notes"] = text_arg(args, "notes", 5000, required=False)
    if args.get("done") is not None:
        change["checked"] = bool_arg(args, "done")
    _need_some(change, "text, quantity, notes, done")
    return Plan(
        "planhaven_update_list_item",
        p.id,
        {"item_id": str(iid), **change},
        f"Change {_changed(change)} of “{item.text}” on the list “{lst.title}” in “{p.title}”",
    )


async def _set_item(db: Database, s: CurrentSession, iid: uuid.UUID, change: dict[str, Any]) -> Any:
    item, lst = await _item(db, s, iid)
    await project(db, s, lst.project_id)
    fields = {k: _dec(v) if k == "quantity" else v for k, v in change.items()}
    await list_service.update_item(db, s, iid, expected_version=item.version, fields=fields, ip=IP)
    return item


@_applies("planhaven_update_list_item")
async def _update_item(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    iid = uuid.UUID(a["item_id"])
    change: dict[str, Any] = {k: a[k] for k in ("text", "quantity", "notes", "checked") if k in a}
    item = await _set_item(db, s, iid, change)
    before = {
        k: (item.checked_at is not None if k == "checked" else _plain(getattr(item, k)))
        for k in change
    }
    return Done({"item_id": str(iid)}, "item_updated", {"item_id": str(iid), "before": before})


@_undoes("item_updated")
async def _undo_update_item(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_item(db, s, uuid.UUID(u["item_id"]), u["before"])


@_plans("planhaven_move_list_items")
async def _plan_move_items(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    lid = id_arg(args, "list_id")
    to = id_arg(args, "to_list_id")
    lst, items = await list_service.get_list(db, s, lid)
    target, _ = await list_service.get_list(db, s, to)
    p = await editable(db, s, lst.project_id)
    await editable(db, s, target.project_id)
    raw = args.get("item_ids")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 200:
        raise ToolError("'item_ids' is a list of 1 to 200 item ids.")
    ids = [id_arg({"id": i}, "id") for i in raw]
    on_list = {i.id: i for i in items}
    if any(i not in on_list for i in ids):
        raise ToolError("Every item in 'item_ids' must be on the list 'list_id'.")
    texts = [on_list[i].text for i in ids]
    return Plan(
        "planhaven_move_list_items",
        p.id,
        {"list_id": str(lid), "to_list_id": str(to), "item_ids": [str(i) for i in ids]},
        f"Move {names(texts)} from “{lst.title}” to “{target.title}”",
    )


@_applies("planhaven_move_list_items")
async def _move_items(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    lid, to = uuid.UUID(a["list_id"]), uuid.UUID(a["to_list_id"])
    for list_id in (lid, to):
        lst, _ = await list_service.get_list(db, s, list_id)
        await project(db, s, lst.project_id)
    ids = [uuid.UUID(i) for i in a["item_ids"]]
    moved = await list_service.move_items(db, s, lid, ids, to_list_id=to, ip=IP)
    return Done(
        {"moved": moved},
        "items_moved",
        {"from_list_id": a["list_id"], "to_list_id": a["to_list_id"], "item_ids": a["item_ids"]},
    )


@_undoes("items_moved")
async def _undo_move_items(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    ids = [uuid.UUID(i) for i in u["item_ids"]]
    await list_service.move_items(
        db, s, uuid.UUID(u["to_list_id"]), ids, to_list_id=uuid.UUID(u["from_list_id"]), ip=IP
    )


# ---------------------------------------------------------------- quotes and costs


def _quote_values(args: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    v: dict[str, Any] = {}
    if not partial or args.get("title") is not None:
        v["title"] = text_arg(args, "title", 200)
    if "contact_id" in args:
        v["contact_id"] = _plain(optional_id(args, "contact_id"))
    if "amount" in args:
        v["amount_cents"] = None if args["amount"] is None else money_arg(args, "amount")
    if args.get("status") is not None:
        v["status"] = choice_arg(args, "status", QUOTE_STATUSES)
    if args.get("notes") is not None:
        v["notes"] = text_arg(args, "notes", 20000, required=False)
    return v


def _quote_service_values(v: dict[str, Any]) -> dict[str, Any]:
    return {k: _uid(x) if k == "contact_id" else x for k, x in v.items()}


@_plans("planhaven_add_quote")
async def _plan_add_quote(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    pid = id_arg(args, "project_id")
    p = await editable(db, s, pid)
    v = _quote_values(args, partial=False)
    return Plan(
        "planhaven_add_quote",
        pid,
        {"project_id": str(pid), **v},
        f"Add the quote “{v['title']}” to “{p.title}”",
    )


@_applies("planhaven_add_quote")
async def _add_quote(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = dict(p.arguments)
    pid = uuid.UUID(a.pop("project_id"))
    await project(db, s, pid)
    values = {
        "contact_id": None,
        "amount_cents": None,
        "status": "requested",
        "attachment_id": None,
        "notes": "",
        **_quote_service_values(a),
    }
    row = await cost_service.create_quote(db, s, pid, values, IP)
    return Done({"quote_id": str(row.id)}, "quote_added", {"quote_id": str(row.id)})


@_undoes("quote_added")
async def _undo_add_quote(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(cost_service.delete_quote(db, s, uuid.UUID(u["quote_id"]), IP))


@_plans("planhaven_update_quote")
async def _plan_update_quote(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    qid = id_arg(args, "quote_id")
    quote = await cost_service.get_quote(db, s, qid)
    p = await editable(db, s, quote.project_id)
    v = _quote_values(args, partial=True)
    _need_some(v, "title, contact_id, amount, status, notes")
    return Plan(
        "planhaven_update_quote",
        p.id,
        {"quote_id": str(qid), **v},
        f"Change {_changed(v)} of the quote “{quote.title}” in “{p.title}”",
    )


async def _set_quote(db: Database, s: CurrentSession, qid: uuid.UUID, v: dict[str, Any]) -> Any:
    quote = await cost_service.get_quote(db, s, qid)
    await project(db, s, quote.project_id)
    await cost_service.update_quote(db, s, qid, quote.version, _quote_service_values(v))
    return quote


@_applies("planhaven_update_quote")
async def _update_quote(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = dict(p.arguments)
    qid = uuid.UUID(a.pop("quote_id"))
    quote = await _set_quote(db, s, qid, a)
    before = {k: _plain(getattr(quote, k)) for k in a}
    return Done({"quote_id": str(qid)}, "quote_updated", {"quote_id": str(qid), "before": before})


@_undoes("quote_updated")
async def _undo_update_quote(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_quote(db, s, uuid.UUID(u["quote_id"]), u["before"])


def _cost_values(args: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    v: dict[str, Any] = {}
    if not partial or args.get("description") is not None:
        v["description"] = text_arg(args, "description", 300)
    if not partial or args.get("amount") is not None:
        v["amount_cents"] = money_arg(args, "amount", negative=True)
    if args.get("spent_on") is not None:
        v["spent_on"] = date_arg(args, "spent_on")
    if "quote_id" in args:
        v["quote_id"] = _plain(optional_id(args, "quote_id"))
    if partial and args.get("store") is not None:
        v["store"] = text_arg(args, "store", 200, required=False)
    return v


def _cost_service_values(v: dict[str, Any]) -> dict[str, Any]:
    out = dict(v)
    if "quote_id" in out:
        out["quote_id"] = _uid(out["quote_id"])
    if out.get("spent_on") is not None:
        out["spent_on"] = date.fromisoformat(out["spent_on"])
    return out


@_plans("planhaven_add_cost")
async def _plan_add_cost(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    pid = id_arg(args, "project_id")
    p = await editable(db, s, pid)
    v = _cost_values(args, partial=False)
    return Plan(
        "planhaven_add_cost",
        pid,
        {"project_id": str(pid), **v},
        f"Add the cost “{v['description']}” ({v['amount_cents'] / 100:.2f}) to “{p.title}”",
    )


@_applies("planhaven_add_cost")
async def _add_cost(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = dict(p.arguments)
    pid = uuid.UUID(a.pop("project_id"))
    await project(db, s, pid)
    values = {"spent_on": None, "quote_id": None, **_cost_service_values(a)}
    row = await cost_service.create_cost(db, s, pid, values, IP)
    return Done({"cost_id": str(row.id)}, "cost_added", {"cost_id": str(row.id)})


@_undoes("cost_added")
async def _undo_add_cost(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(cost_service.delete_cost(db, s, uuid.UUID(u["cost_id"]), IP))


@_plans("planhaven_update_cost")
async def _plan_update_cost(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    cid = id_arg(args, "cost_id")
    cost, _, _ = await cost_service.get_purchase(db, s, cid)
    p = await editable(db, s, cost.project_id)
    v = _cost_values(args, partial=True)
    _need_some(v, "description, amount, spent_on, quote_id, store")
    return Plan(
        "planhaven_update_cost",
        p.id,
        {"cost_id": str(cid), **v},
        f"Change {_changed(v)} of the cost “{cost.description}” in “{p.title}”",
    )


async def _set_cost(db: Database, s: CurrentSession, cid: uuid.UUID, v: dict[str, Any]) -> Any:
    cost, _, _ = await cost_service.get_purchase(db, s, cid)
    await project(db, s, cost.project_id)
    await cost_service.update_cost(db, s, cid, cost.version, _cost_service_values(v), IP)
    return cost


@_applies("planhaven_update_cost")
async def _update_cost(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = dict(p.arguments)
    cid = uuid.UUID(a.pop("cost_id"))
    cost = await _set_cost(db, s, cid, a)
    before = {k: _plain(getattr(cost, k)) for k in a}
    return Done({"cost_id": str(cid)}, "cost_updated", {"cost_id": str(cid), "before": before})


@_undoes("cost_updated")
async def _undo_update_cost(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_cost(db, s, uuid.UUID(u["cost_id"]), u["before"])


# ---------------------------------------------------------------- contacts

_CONTACT_LIMITS = {"company": 200, "phone": 50, "email": 254, "website": 500, "notes": 20000}


def _contact_values(args: dict[str, Any], *, partial: bool) -> dict[str, str]:
    v: dict[str, str] = {}
    if not partial or args.get("name") is not None:
        v["name"] = text_arg(args, "name", 200)
    if args.get("kind") is not None:
        v["kind"] = choice_arg(args, "kind", CONTACT_KINDS)
    for key, limit in _CONTACT_LIMITS.items():
        if args.get(key) is not None:
            v[key] = text_arg(args, key, limit, required=False)
    if not _WEBSITE.match(v.get("website", "")):
        raise ToolError("'website' starts with http:// or https://.", field="website")
    return v


@_plans("planhaven_add_contact")
async def _plan_add_contact(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    v = _contact_values(args, partial=False)
    return Plan("planhaven_add_contact", None, v, f"Add the contact “{v['name']}”")


@_applies("planhaven_add_contact")
async def _add_contact(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    values = {k: "" for k in _CONTACT_LIMITS} | {"kind": "contractor"} | p.arguments
    row = await contact_service.create_contact(db, s, values, IP)
    return Done({"contact_id": str(row.id)}, "contact_added", {"contact_id": str(row.id)})


@_undoes("contact_added")
async def _undo_add_contact(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(contact_service.delete_contact(db, s, uuid.UUID(u["contact_id"]), IP))


@_plans("planhaven_update_contact")
async def _plan_update_contact(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    cid = id_arg(args, "contact_id")
    row, _ = await contact_service.get_contact(db, s, cid)
    authz.require(s.principal, authz.Action.CONTACT_EDIT, authz.ProjectAccess(row.role))
    v = _contact_values(args, partial=True)
    _need_some(v, "name, company, kind, phone, email, website, notes")
    return Plan(
        "planhaven_update_contact",
        None,
        {"contact_id": str(cid), **v},
        f"Change {_changed(v)} of the contact “{row.name}”",
    )


async def _set_contact(db: Database, s: CurrentSession, cid: uuid.UUID, v: dict[str, str]) -> Any:
    row, _ = await contact_service.get_contact(db, s, cid)
    values = {k: getattr(row, k) for k in ("name", "kind", *_CONTACT_LIMITS)} | v
    await contact_service.update_contact(db, s, cid, row.version, values)
    return row


@_applies("planhaven_update_contact")
async def _update_contact(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = dict(p.arguments)
    cid = uuid.UUID(a.pop("contact_id"))
    row = await _set_contact(db, s, cid, a)
    before = {k: getattr(row, k) for k in a}
    return Done(
        {"contact_id": str(cid)}, "contact_updated", {"contact_id": str(cid), "before": before}
    )


@_undoes("contact_updated")
async def _undo_update_contact(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_contact(db, s, uuid.UUID(u["contact_id"]), u["before"])


# ---------------------------------------------------------------- assets


def _details(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or len(raw) > 40:
        raise ToolError("'details' is a list of up to 40 {label, value} pairs.")
    out = []
    for d in raw:
        if not isinstance(d, dict):
            raise ToolError("Each detail has a 'label' and a 'value'.")
        out.append(
            {"label": text_arg(d, "label", 60), "value": text_arg(d, "value", 500, required=False)}
        )
    return out


def _asset_values(args: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    v: dict[str, Any] = {}
    if not partial or args.get("name") is not None:
        v["name"] = text_arg(args, "name", 200)
    if args.get("kind") is not None:
        v["kind"] = choice_arg(args, "kind", ASSET_KINDS)
    if args.get("notes") is not None:
        v["notes"] = text_arg(args, "notes", 20000, required=False)
    if args.get("details") is not None:
        v["details"] = _details(args["details"])
    return v


@_plans("planhaven_add_asset")
async def _plan_add_asset(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    v = _asset_values(args, partial=False)
    return Plan("planhaven_add_asset", None, v, f"Add the asset “{v['name']}”")


@_applies("planhaven_add_asset")
async def _add_asset(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = {"kind": "other", "notes": "", "details": []} | p.arguments
    row = await asset_svc.create_asset(
        db, s, name=a["name"], kind=a["kind"], details=a["details"], notes=a["notes"], ip=IP
    )
    return Done({"asset_id": str(row.id)}, "asset_added", {"asset_id": str(row.id)})


@_undoes("asset_added")
async def _undo_add_asset(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(asset_svc.delete_asset(db, s, uuid.UUID(u["asset_id"]), IP))


@_plans("planhaven_update_asset")
async def _plan_update_asset(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    aid = id_arg(args, "asset_id")
    row = await _asset(db, s, aid)
    _asset_edit(s, row)
    v = _asset_values(args, partial=True)
    _need_some(v, "name, kind, notes, details")
    return Plan(
        "planhaven_update_asset",
        None,
        {"asset_id": str(aid), **v},
        f"Change {_changed(v)} of the asset “{row.name}”",
    )


async def _set_asset(db: Database, s: CurrentSession, aid: uuid.UUID, v: dict[str, Any]) -> Any:
    row = await _asset(db, s, aid)
    a = {k: getattr(row, k) for k in ("name", "kind", "notes", "details")} | v
    await asset_svc.update_asset(
        db,
        s,
        aid,
        row.version,
        name=a["name"],
        kind=a["kind"],
        details=a["details"],
        notes=a["notes"],
    )
    return row


@_applies("planhaven_update_asset")
async def _update_asset(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = dict(p.arguments)
    aid = uuid.UUID(a.pop("asset_id"))
    row = await _set_asset(db, s, aid, a)
    before = {k: getattr(row, k) for k in a}
    return Done({"asset_id": str(aid)}, "asset_updated", {"asset_id": str(aid), "before": before})


@_undoes("asset_updated")
async def _undo_update_asset(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_asset(db, s, uuid.UUID(u["asset_id"]), u["before"])


def _distance(args: dict[str, Any], key: str) -> str | None:
    if args.get(key) is None:
        return None
    return number_arg(args, key, low=Decimal(0), high=Decimal(9999999), places=1)


@_plans("planhaven_add_asset_reading")
async def _plan_add_reading(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    aid = id_arg(args, "asset_id")
    row = await _asset(db, s, aid)
    _asset_edit(s, row)
    v = {
        "asset_id": str(aid),
        "read_on": date_arg(args, "read_on"),
        "distance": _distance(args, "distance"),
        "hours": _distance(args, "hours"),
    }
    if v["distance"] is None and v["hours"] is None:
        raise ToolError("Give a 'distance' or 'hours'.")
    return Plan("planhaven_add_asset_reading", None, v, f"Add a reading to “{row.name}”")


async def _reading(db: Database, s: CurrentSession, v: dict[str, Any]) -> uuid.UUID:
    return await asset_service.add_reading(
        db,
        s,
        uuid.UUID(v["asset_id"]),
        read_on=date.fromisoformat(v["read_on"]),
        distance=_dec(v["distance"]),
        hours=_dec(v["hours"]),
        ip=IP,
    )


@_applies("planhaven_add_asset_reading")
async def _add_reading(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    rid = await _reading(db, s, p.arguments)
    return Done({"reading_id": str(rid)}, "reading_added", {"reading_id": str(rid)})


@_undoes("reading_added")
async def _undo_add_reading(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(asset_service.delete_reading(db, s, uuid.UUID(u["reading_id"]), IP))


def _schedule_values(args: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    v: dict[str, Any] = {}
    if not partial or args.get("name") is not None:
        v["name"] = text_arg(args, "name", 200)
    for key, high in (("every_distance", 9999999), ("every_hours", 999999)):
        if key in args:
            v[key] = (
                None
                if args[key] is None
                else number_arg(args, key, low=Decimal(0), high=Decimal(high), places=1, above=True)
            )
    if "every_months" in args:
        months = args["every_months"]
        if months is not None and (not isinstance(months, int) or not 1 <= months <= 240):
            raise ToolError("'every_months' is a whole number from 1 to 240.")
        v["every_months"] = months
    if args.get("notes") is not None:
        v["notes"] = text_arg(args, "notes", 4000, required=False)
    return v


@_plans("planhaven_add_service_schedule")
async def _plan_add_schedule(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    aid = id_arg(args, "asset_id")
    row = await _asset(db, s, aid)
    _asset_edit(s, row)
    v = _schedule_values(args, partial=False)
    return Plan(
        "planhaven_add_service_schedule",
        None,
        {"asset_id": str(aid), **v},
        f"Add the service “{v['name']}” to “{row.name}”",
    )


@_applies("planhaven_add_service_schedule")
async def _add_schedule(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a: dict[str, Any] = {
        "every_distance": None,
        "every_hours": None,
        "every_months": None,
        "notes": "",
    }
    a |= p.arguments
    row = await asset_service.create_schedule(
        db,
        s,
        uuid.UUID(a["asset_id"]),
        name=a["name"],
        every_distance=_dec(a["every_distance"]),
        every_hours=_dec(a["every_hours"]),
        every_months=a["every_months"],
        notes=a["notes"],
        ip=IP,
    )
    return Done({"schedule_id": str(row.id)}, "schedule_added", {"schedule_id": str(row.id)})


@_undoes("schedule_added")
async def _undo_add_schedule(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(asset_service.delete_schedule(db, s, uuid.UUID(u["schedule_id"]), IP))


@_plans("planhaven_update_service_schedule")
async def _plan_update_schedule(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    sid = id_arg(args, "schedule_id")
    schedule = await asset_service.get_schedule(db, s, sid)
    _asset_edit(s, await _asset(db, s, schedule.asset_id))
    v = _schedule_values(args, partial=True)
    _need_some(v, "name, every_distance, every_hours, every_months, notes")
    return Plan(
        "planhaven_update_service_schedule",
        None,
        {"schedule_id": str(sid), **v},
        f"Change {_changed(v)} of the service “{schedule.name}”",
    )


async def _set_schedule(db: Database, s: CurrentSession, sid: uuid.UUID, v: dict[str, Any]) -> Any:
    row = await asset_service.get_schedule(db, s, sid)
    keys = ("name", "every_distance", "every_hours", "every_months", "notes")
    a = {k: _plain(getattr(row, k)) for k in keys} | v
    await asset_service.update_schedule(
        db,
        s,
        sid,
        expected_version=row.version,
        name=a["name"],
        every_distance=_dec(a["every_distance"]),
        every_hours=_dec(a["every_hours"]),
        every_months=a["every_months"],
        notes=a["notes"],
        ip=IP,
    )
    return row


@_applies("planhaven_update_service_schedule")
async def _update_schedule(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = dict(p.arguments)
    sid = uuid.UUID(a.pop("schedule_id"))
    row = await _set_schedule(db, s, sid, a)
    before = {k: _plain(getattr(row, k)) for k in a}
    return Done(
        {"schedule_id": str(sid)}, "schedule_updated", {"schedule_id": str(sid), "before": before}
    )


@_undoes("schedule_updated")
async def _undo_update_schedule(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _set_schedule(db, s, uuid.UUID(u["schedule_id"]), u["before"])


@_plans("planhaven_add_service_record")
async def _plan_add_record(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    aid = id_arg(args, "asset_id")
    row = await _asset(db, s, aid)
    _asset_edit(s, row)
    schedule_id = optional_id(args, "schedule_id")
    title = text_arg(args, "title", 200, required=False) or None
    if schedule_id is None and title is None:
        raise ToolError("Give a 'schedule_id' or a 'title'.")
    v = {
        "asset_id": str(aid),
        "schedule_id": _plain(schedule_id),
        "title": title,
        "done_on": date_arg(args, "done_on"),
        "distance": _distance(args, "distance"),
        "hours": _distance(args, "hours"),
        "cost_cents": None if args.get("cost") is None else money_arg(args, "cost"),
        "notes": text_arg(args, "notes", 4000, required=False),
    }
    return Plan(
        "planhaven_add_service_record",
        None,
        v,
        f"Record “{title or 'a scheduled service'}” done on {v['done_on']} for “{row.name}”",
    )


@_applies("planhaven_add_service_record")
async def _add_record(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    row = await asset_service.add_record(
        db,
        s,
        uuid.UUID(a["asset_id"]),
        schedule_id=_uid(a["schedule_id"]),
        title=a["title"],
        done_on=date.fromisoformat(a["done_on"]),
        distance=_dec(a["distance"]),
        hours=_dec(a["hours"]),
        cost_cents=a["cost_cents"],
        notes=a["notes"],
        ip=IP,
    )
    return Done({"record_id": str(row.id)}, "record_added", {"record_id": str(row.id)})


@_undoes("record_added")
async def _undo_add_record(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    await _quietly(asset_service.delete_record(db, s, uuid.UUID(u["record_id"]), IP))


# ---------------------------------------------------------------- household members


async def _member_role(
    db: Database, s: CurrentSession, kind: sharing.Kind, rid: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    for m in await sharing.list_members(db, s, rid, kind):
        if m.user_id == user_id:
            return m.role
    return None


async def _set_role(
    db: Database,
    s: CurrentSession,
    kind: sharing.Kind,
    rid: uuid.UUID,
    user_id: uuid.UUID,
    old: str | None,
    new: str | None,
) -> None:
    if old == new:
        return
    if new is None:
        await sharing.remove_member(db, s, rid, user_id, IP, kind)
    elif old is None:
        await sharing.add_member(db, s, rid, user_id, new, IP, kind)
    else:
        await sharing.change_role(db, s, rid, user_id, new, IP, kind)


@_plans("planhaven_set_member")
async def _plan_set_member(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    kind: sharing.Kind = (
        "asset" if choice_arg(args, "kind", ("project", "asset")) == "asset" else "project"
    )
    rid = id_arg(args, "id")
    user_id = id_arg(args, "user_id")
    role = choice_arg(args, "role", MEMBER_ROLES)
    if kind == "project":
        title = (await project(db, s, rid)).title
    else:
        title = (await _asset(db, s, rid)).name
    current = await _member_role(db, s, kind, rid, user_id)
    new = None if role == "none" else role
    authz.require_ai_member_change(s.principal, user_id, current, new)
    if current == new:
        raise ToolError("That person already has that access.")
    who = next((d.display_name for d in await sharing.directory(db, s) if d.id == user_id), None)
    if who is None:
        raise authz.NotFoundError("Not found.")
    what = f"Remove {who} from" if new is None else f"Make {who} {new} of"
    return Plan(
        "planhaven_set_member",
        rid if kind == "project" else None,
        {"kind": kind, "id": str(rid), "user_id": str(user_id), "role": new},
        f"{what} “{title}”",
    )


@_applies("planhaven_set_member")
async def _set_member(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    a = p.arguments
    kind: sharing.Kind = a["kind"]
    rid, user_id = uuid.UUID(a["id"]), uuid.UUID(a["user_id"])
    if kind == "project":
        await project(db, s, rid)
    current = await _member_role(db, s, kind, rid, user_id)
    authz.require_ai_member_change(s.principal, user_id, current, a["role"])
    await _set_role(db, s, kind, rid, user_id, current, a["role"])
    return Done(
        {"user_id": a["user_id"], "role": a["role"] or "none"},
        "member_changed",
        {
            "kind": kind,
            "id": a["id"],
            "user_id": a["user_id"],
            "before": current,
            "after": a["role"],
        },
    )


@_undoes("member_changed")
async def _undo_set_member(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    kind: sharing.Kind = u["kind"]
    rid, user_id = uuid.UUID(u["id"]), uuid.UUID(u["user_id"])
    now = await _member_role(db, s, kind, rid, user_id)
    await _set_role(db, s, kind, rid, user_id, now, u["before"])


# ---------------------------------------------------------------- deleting (to the Trash)


async def _describe(
    db: Database, s: CurrentSession, kind: str, item_id: uuid.UUID
) -> tuple[str, uuid.UUID | None, dict[str, Any]]:
    """What is about to be deleted (for the summary), its project, and anything Undo needs
    that the Trash doesn't keep. Checks the person may delete it."""
    principal = s.principal
    if kind == "project":
        p = await project(db, s, item_id)
        authz.require(principal, authz.Action.PROJECT_MANAGE, authz.ProjectAccess(p.role))
        return f"the project “{p.title}” and everything in it", p.id, {}
    if kind == "task":
        task = await _task(db, s, item_id)
        p = await editable(db, s, task.project_id)
        return f"the task “{task.title}” from “{p.title}”", p.id, {}
    if kind == "note":
        note, _, _ = await note_service.get_note(db, s, item_id)
        p = await editable(db, s, note.project_id)
        return f"the note “{note.title}” from “{p.title}”", p.id, {}
    if kind == "list":
        lst, _ = await list_service.get_list(db, s, item_id)
        p = await editable(db, s, lst.project_id)
        return f"the list “{lst.title}” from “{p.title}”", p.id, {}
    if kind == "list_item":
        item, lst = await _item(db, s, item_id)
        p = await editable(db, s, lst.project_id)
        return f"“{item.text}” from the list “{lst.title}”", p.id, {}
    if kind == "file":
        f, _ = await attachment_service.get_attachment(db, s, item_id)
        p = await editable(db, s, f.project_id)
        return f"the file “{f.filename}” from “{p.title}”", p.id, {}
    if kind == "quote":
        quote = await cost_service.get_quote(db, s, item_id)
        p = await editable(db, s, quote.project_id)
        return f"the quote “{quote.title}” from “{p.title}”", p.id, {}
    if kind == "cost":
        cost, _, _ = await cost_service.get_purchase(db, s, item_id)
        p = await editable(db, s, cost.project_id)
        return f"the cost “{cost.description}” from “{p.title}”", p.id, {}
    if kind == "contact":
        contact, _ = await contact_service.get_contact(db, s, item_id)
        authz.require(principal, authz.Action.CONTACT_MANAGE, authz.ProjectAccess(contact.role))
        return f"the contact “{contact.name}”", None, {}
    if kind == "asset":
        asset = await _asset(db, s, item_id)
        authz.require(principal, authz.Action.ASSET_MANAGE, authz.ProjectAccess(asset.role))
        return f"the asset “{asset.name}”", None, {}
    if kind == "reading":
        reading = await asset_service.get_reading(db, s, item_id)
        asset = await _asset(db, s, reading.asset_id)
        _asset_edit(s, asset)
        keep = {
            "asset_id": str(reading.asset_id),
            "read_on": _plain(reading.read_on),
            "distance": _plain(reading.distance),
            "hours": _plain(reading.hours),
        }
        return f"the reading of {reading.read_on} from “{asset.name}”", None, keep
    if kind == "service_schedule":
        schedule = await asset_service.get_schedule(db, s, item_id)
        asset = await _asset(db, s, schedule.asset_id)
        _asset_edit(s, asset)
        return f"the service “{schedule.name}” from “{asset.name}”", None, {}
    record = await asset_service.get_record(db, s, item_id)
    asset = await _asset(db, s, record.asset_id)
    _asset_edit(s, asset)
    return f"the service record “{record.title}” from “{asset.name}”", None, {}


@_plans("planhaven_delete")
async def _plan_delete(db: Database, s: CurrentSession, args: dict[str, Any]) -> Plan:
    kind = choice_arg(args, "kind", DELETABLE)
    item_id = id_arg(args, "id")
    what, project_id, _ = await _describe(db, s, kind, item_id)
    return Plan(
        "planhaven_delete",
        project_id,
        {"kind": kind, "id": str(item_id)},
        f"Delete {what} (to the Trash)",
    )


_DELETE: dict[str, Callable[[Database, CurrentSession, uuid.UUID], Awaitable[None]]] = {
    "project": lambda db, s, i: project_service.delete_project(db, s, i, IP),
    "task": lambda db, s, i: project_service.delete_task(db, s, i, IP),
    "note": lambda db, s, i: note_service.delete_note(db, s, i, IP),
    "list": lambda db, s, i: list_service.delete_list(db, s, i, IP),
    "list_item": lambda db, s, i: list_service.delete_item(db, s, i, IP),
    "file": lambda db, s, i: attachment_service.delete_attachment(db, s, i, IP),
    "quote": lambda db, s, i: cost_service.delete_quote(db, s, i, IP),
    "cost": lambda db, s, i: cost_service.delete_cost(db, s, i, IP),
    "contact": lambda db, s, i: contact_service.delete_contact(db, s, i, IP),
    "asset": lambda db, s, i: asset_svc.delete_asset(db, s, i, IP),
    "reading": lambda db, s, i: asset_service.delete_reading(db, s, i, IP),
    "service_schedule": lambda db, s, i: asset_service.delete_schedule(db, s, i, IP),
    "service_record": lambda db, s, i: asset_service.delete_record(db, s, i, IP),
}


@_applies("planhaven_delete")
async def _delete(db: Database, s: CurrentSession, p: Plan, client: str) -> Done:
    kind, item_id = p.arguments["kind"], uuid.UUID(p.arguments["id"])
    _, _, keep = await _describe(db, s, kind, item_id)  # checked again, as of now
    await _DELETE[kind](db, s, item_id)
    return Done(
        {"deleted": kind, "id": str(item_id), "in_trash": kind != "reading"},
        "deleted",
        {"kind": kind, "id": str(item_id), **keep},
    )


@_undoes("deleted")
async def _undo_delete(db: Database, s: CurrentSession, u: dict[str, Any]) -> None:
    kind, item_id = u["kind"], uuid.UUID(u["id"])
    try:
        if kind in _TRASH_KIND:
            await trash.restore(db, s, _TRASH_KIND[kind], item_id, IP)
        elif kind == "list_item":
            await list_service.restore_item(db, s, item_id, IP)
        elif kind in ("service_schedule", "service_record"):
            await asset_service.restore(
                db, s, "schedule" if kind == "service_schedule" else "record", item_id, IP
            )
        else:  # a reading isn't kept: add it again
            await _reading(db, s, u)
    except authz.NotFoundError:
        raise CannotUndoError(
            "It can't be brought back any more: it was already restored, or removed for good.",
            code="cannot_undo",
        ) from None


WRITE_TOOLS = tuple(PLANNERS)
