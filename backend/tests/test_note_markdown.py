"""The server's Markdown copy of a note matches what the editor used to produce."""

from pathlib import Path
from typing import Any

import pycrdt

from app.services.note_markdown import to_markdown

NOTE = (Path(__file__).parent / "fixtures" / "tiptap-checklist-note.bin").read_bytes()


def test_markdown_from_a_real_editor_note() -> None:
    doc: pycrdt.Doc[Any] = pycrdt.Doc()
    doc.apply_update(NOTE)
    assert to_markdown(doc) == "Before launch\n\n- [ ] Check oil\n- [x] Charge **battery**"


def test_empty_note() -> None:
    assert to_markdown(pycrdt.Doc()) == ""
