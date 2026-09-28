"""Notes saved on Done (docs/adr/0016): roles, conflicts, content checks, checkboxes, and
notes from the earlier live editor."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.db.database import Database
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]

# A note made by the earlier live editor (TipTap + Yjs): "Before launch", then a checklist with
# "Check oil" (not ticked) and "Charge **battery**" (ticked).
LEGACY_NOTE = (Path(__file__).parent.parent / "fixtures" / "tiptap-checklist-note.bin").read_bytes()

DOC = {
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Deck"}]},
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Use "},
                {"type": "text", "text": "cedar", "marks": [{"type": "bold"}]},
            ],
        },
        {
            "type": "taskList",
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"checked": False},
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Measure"}]}
                    ],
                }
            ],
        },
    ],
}


def _save(u: U, nid: str, version: int, content: Any, title: str = "Deck plan") -> Any:
    u._cookie()
    return u.client.put(
        f"/api/v1/notes/{nid}",
        headers={**u.h, "if-match": f'"{version}"'},
        json={"title": title, "content": content},
    )


def test_save_on_done(team: Team) -> None:
    owner, viewer, stranger, pid, nid = team
    note = owner.get(f"/api/v1/notes/{nid}").json()
    assert note["can_edit"] is True
    assert note["content"]["type"] == "doc"
    r = _save(owner, nid, note["version"], DOC)
    assert r.status_code == 200, r.text
    saved = viewer.get(f"/api/v1/notes/{nid}").json()
    assert saved["title"] == "Deck plan"
    assert saved["content"] == DOC
    assert saved["text_content"] == "## Deck\n\nUse **cedar**\n\n- [ ] Measure"
    assert saved["can_edit"] is False
    listed = viewer.get(f"/api/v1/projects/{pid}/notes").json()
    assert listed[0]["text_content"].startswith("## Deck")
    # Viewers can't save; strangers don't see it.
    assert _save(viewer, nid, saved["version"], DOC).status_code == 403
    assert _save(stranger, nid, saved["version"], DOC).status_code == 404


def test_a_save_never_overwrites_someone_elses(team: Team) -> None:
    owner, _, _, _, nid = team
    opened = owner.get(f"/api/v1/notes/{nid}").json()["version"]
    assert _save(owner, nid, opened, DOC).status_code == 200
    stale = _save(owner, nid, opened, {"type": "doc", "content": []})
    assert stale.status_code == 409
    assert "Someone else saved" in stale.json()["detail"]
    assert owner.get(f"/api/v1/notes/{nid}").json()["content"] == DOC


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "doc", "content": [{"type": "iframe", "attrs": {"src": "https://evil"}}]},
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "x", "marks": [{"type": "script"}]}],
                }
            ],
        },
        {"type": "not-a-doc"},
        {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": ""}]}],
        },
    ],
)
def test_unsupported_content_is_refused(team: Team, bad: Any) -> None:
    owner, _, _, _, nid = team
    version = owner.get(f"/api/v1/notes/{nid}").json()["version"]
    assert _save(owner, nid, version, bad).status_code == 422


def test_content_is_cleaned(team: Team) -> None:
    owner, _, _, _, nid = team
    version = owner.get(f"/api/v1/notes/{nid}").json()["version"]
    sneaky = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"onclick": "alert(1)", "style": "x"},
                "content": [
                    {
                        "type": "text",
                        "text": "bad",
                        "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                    },
                    {
                        "type": "text",
                        "text": " good",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://example.com", "target": "_self"},
                            }
                        ],
                    },
                ],
            }
        ],
    }
    assert _save(owner, nid, version, sneaky).status_code == 200
    stored = owner.get(f"/api/v1/notes/{nid}").json()["content"]
    assert stored == {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "bad"},
                    {
                        "type": "text",
                        "text": " good",
                        "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
                    },
                ],
            }
        ],
    }


def test_checkboxes_from_the_project_page(team: Team) -> None:
    owner, viewer, stranger, pid, nid = team
    version = owner.get(f"/api/v1/notes/{nid}").json()["version"]
    _save(owner, nid, version, DOC)
    cards = viewer.get(f"/api/v1/projects/{pid}/note-cards").json()
    line = {"marker": None, "index": None, "checked": None, "depth": 0}
    assert cards == [
        {
            "note_id": nid,
            "lines": [
                {**line, "kind": "heading", "text": "Deck"},
                {**line, "kind": "text", "text": "Use cedar"},
                {**line, "kind": "check", "text": "Measure", "index": 0, "checked": False},
            ],
            "more": 0,
        }
    ]
    assert stranger.get(f"/api/v1/projects/{pid}/note-cards").status_code == 404
    tick = {"index": 0, "text": "Measure", "checked": True}
    assert (
        viewer.post(f"/api/v1/notes/{nid}/checklist", headers=viewer.h, json=tick).status_code
        == 403
    )
    stale = {"index": 0, "text": "Something else", "checked": True}
    assert (
        owner.post(f"/api/v1/notes/{nid}/checklist", headers=owner.h, json=stale).status_code == 409
    )
    assert (
        owner.post(f"/api/v1/notes/{nid}/checklist", headers=owner.h, json=tick).status_code == 204
    )
    after = owner.get(f"/api/v1/notes/{nid}").json()
    assert after["text_content"].endswith("- [x] Measure")


async def _store_legacy(note_id: str, user_id: str, project_id: str) -> None:
    """Make the note look like one saved by the earlier live editor."""
    db = Database(_settings())
    try:
        async with db.user_transaction(uuid.UUID(user_id)) as conn:
            await conn.execute(
                # with a preview left garbled by the old editor's bug
                text("UPDATE notes SET content = NULL, text_content = '[' WHERE id = :n"),
                {"n": note_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO note_updates (note_id, project_id, user_id, update) "
                    "VALUES (:n, :p, :u, :b)"
                ),
                {"n": note_id, "p": project_id, "u": user_id, "b": LEGACY_NOTE},
            )
    finally:
        await db.dispose()


def test_notes_from_the_earlier_live_editor_open_and_convert(team: Team) -> None:
    owner, _, _, pid, nid = team
    asyncio.run(_store_legacy(nid, owner.id, pid))
    note = owner.get(f"/api/v1/notes/{nid}").json()
    assert note["content"] == {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Before launch"}]},
            {
                "type": "taskList",
                "content": [
                    {
                        "type": "taskItem",
                        "attrs": {"checked": False},
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Check oil"}],
                            }
                        ],
                    },
                    {
                        "type": "taskItem",
                        "attrs": {"checked": True},
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Charge "},
                                    {
                                        "type": "text",
                                        "text": "battery",
                                        "marks": [{"type": "bold"}],
                                    },
                                ],
                            }
                        ],
                    },
                ],
            },
        ],
    }
    # The project page's preview is rebuilt from the document, not the garbled copy.
    listed = owner.get(f"/api/v1/projects/{pid}/notes").json()
    assert listed[0]["text_content"] == "Before launch\n\n- [ ] Check oil\n- [x] Charge **battery**"
    # Saving it stores the converted document from then on.
    assert _save(owner, nid, note["version"], note["content"], title="Launch").status_code == 200
    assert owner.get(f"/api/v1/notes/{nid}").json()["text_content"] == (
        "Before launch\n\n- [ ] Check oil\n- [x] Charge **battery**"
    )
