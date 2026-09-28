"""Note content: a TipTap/ProseMirror JSON document, saved when the person taps Done.

(Owner decision 2026-09-28: no live co-editing and no automatic saving for now; see
docs/adr/0016-notes-save-on-done.md.)

Everything here treats the document as untrusted input:
- `clean()` rebuilds it from an allowlist of node types, marks and attributes, with limits on
  size and depth; anything unknown is refused, links may only be http(s) or mailto.
- `to_markdown()` makes the text copy for previews, search, AI and export.
- `checklist()` / `with_checked()` read and tick checkboxes (the project page).
- `from_legacy()` converts notes saved by the earlier live editor (Yjs documents).
"""

import re
from typing import Any

import pycrdt

MAX_NODES = 50_000
MAX_DEPTH = 30
MAX_TEXT = 200_000

BLOCKS = {
    "paragraph", "heading", "blockquote", "bulletList", "orderedList", "listItem",
    "taskList", "taskItem", "codeBlock", "horizontalRule",
}  # fmt: skip
INLINE = {"text", "hardBreak"}
MARKS = {"bold", "italic", "strike", "code", "underline", "link"}
_SAFE_HREF = re.compile(r"^(https?://|mailto:)[^\s<>\"']{1,2000}$", re.IGNORECASE)

EMPTY: dict[str, Any] = {"type": "doc", "content": [{"type": "paragraph"}]}


class ContentError(ValueError):
    """The document isn't one PlanHaven accepts (message is safe to show)."""


class _Budget:
    def __init__(self) -> None:
        self.nodes = 0
        self.text = 0


def _attrs(kind: str, attrs: Any) -> dict[str, Any] | None:
    attrs = attrs if isinstance(attrs, dict) else {}
    if kind == "heading":
        level = attrs.get("level")
        return {"level": level if isinstance(level, int) and 1 <= level <= 6 else 2}
    if kind == "orderedList":
        start = attrs.get("start")
        return {"start": start if isinstance(start, int) and 0 <= start <= 100_000 else 1}
    if kind == "taskItem":
        return {"checked": attrs.get("checked") is True}
    if kind == "codeBlock":
        language = attrs.get("language")
        if isinstance(language, str) and re.fullmatch(r"[A-Za-z0-9_+-]{1,30}", language):
            return {"language": language}
        return None
    return None


def _marks(marks: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for mark in marks if isinstance(marks, list) else []:
        if not isinstance(mark, dict) or mark.get("type") not in MARKS:
            raise ContentError("This note contains formatting PlanHaven doesn't support.")
        if mark["type"] == "link":
            href = (mark.get("attrs") or {}).get("href")
            if isinstance(href, str) and _SAFE_HREF.match(href):
                out.append({"type": "link", "attrs": {"href": href}})
            # other links (javascript:, data:, ...) are dropped, keeping their text
            continue
        out.append({"type": mark["type"]})
    return out


def _clean(node: Any, depth: int, budget: _Budget) -> dict[str, Any]:
    if depth > MAX_DEPTH:
        raise ContentError("This note is nested too deeply.")
    budget.nodes += 1
    if budget.nodes > MAX_NODES:
        raise ContentError("This note is too long.")
    if not isinstance(node, dict):
        raise ContentError("This note isn't in a format PlanHaven understands.")
    kind = node.get("type")
    if kind == "text":
        text = node.get("text")
        if not isinstance(text, str) or not text:
            raise ContentError("This note isn't in a format PlanHaven understands.")
        budget.text += len(text)
        if budget.text > MAX_TEXT:
            raise ContentError("This note is too long.")
        out: dict[str, Any] = {"type": "text", "text": text}
        marks = _marks(node.get("marks"))
        if marks:
            out["marks"] = marks
        return out
    if kind == "hardBreak":
        return {"type": "hardBreak"}
    if kind not in BLOCKS:
        raise ContentError("This note contains something PlanHaven doesn't support.")
    out = {"type": kind}
    attrs = _attrs(kind, node.get("attrs"))
    if attrs is not None:
        out["attrs"] = attrs
    children = node.get("content")
    if children is not None:
        if not isinstance(children, list):
            raise ContentError("This note isn't in a format PlanHaven understands.")
        cleaned = [_clean(c, depth + 1, budget) for c in children]
        if cleaned:
            out["content"] = cleaned
    return out


def clean(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("type") != "doc":
        raise ContentError("This note isn't in a format PlanHaven understands.")
    budget = _Budget()
    blocks = [_clean(b, 1, budget) for b in document.get("content") or []]
    return {"type": "doc", "content": blocks or [{"type": "paragraph"}]}


# ------------------------------------------------------------------ Markdown copy


def _inline(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("content", []):
        if child["type"] == "hardBreak":
            out.append("\n")
            continue
        if child["type"] != "text":
            out.append(_inline(child))
            continue
        piece = child["text"]
        for mark in child.get("marks", []):
            wrap = {"bold": "**", "italic": "*", "strike": "~~", "code": "`"}.get(mark["type"])
            if wrap:
                piece = f"{wrap}{piece}{wrap}"
        out.append(piece)
    return "".join(out)


def _block(node: dict[str, Any], depth: int) -> str:
    kind = node["type"]
    children = node.get("content", [])
    if kind == "paragraph":
        return _inline(node)
    if kind == "heading":
        return f"{'#' * node.get('attrs', {}).get('level', 2)} {_inline(node)}"
    if kind == "blockquote":
        return "\n".join(f"> {_block(c, depth)}" for c in children)
    if kind == "codeBlock":
        return f"```\n{_inline(node)}\n```"
    if kind == "horizontalRule":
        return "---"
    if kind in ("bulletList", "orderedList", "taskList"):
        lines = []
        for i, item in enumerate(children):
            if kind == "orderedList":
                marker = f"{i + 1}."
            elif kind == "taskList":
                marker = f"- [{'x' if item.get('attrs', {}).get('checked') else ' '}]"
            else:
                marker = "-"
            parts = [_block(c, depth + 1) for c in item.get("content", [])]
            first, rest = (parts[0], parts[1:]) if parts else ("", [])
            lines.append("\n".join([f"{'  ' * depth}{marker} {first}", *rest]))
        return "\n".join(lines)
    return _inline(node)


def to_markdown(document: dict[str, Any]) -> str:
    return "\n\n".join(_block(b, 0) for b in document.get("content", [])).strip()[:MAX_TEXT]


# ------------------------------------------------------------------ checkboxes


def _task_items(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for child in node.get("content", []):
        if child.get("type") == "taskItem":
            found.append(child)
        found.extend(_task_items(child))
    return found


def _plain(node: dict[str, Any]) -> str:
    parts = []
    for child in node.get("content", []):
        if child.get("type") == "text":
            parts.append(child["text"])
        elif child.get("type") != "taskList":
            parts.append(_plain(child))
    return "".join(parts)


def checklist(document: dict[str, Any]) -> list[tuple[int, str, bool]]:
    """(index, text, checked) for every checkbox, in reading order."""
    return [
        (i, _plain(item).strip()[:300], item.get("attrs", {}).get("checked") is True)
        for i, item in enumerate(_task_items(document))
    ]


def with_checked(document: dict[str, Any], index: int, text: str, checked: bool) -> dict[str, Any]:
    """A copy with one checkbox set; ContentError if the item there isn't `text` any more."""
    copy = clean(document)
    items = _task_items(copy)
    if index >= len(items) or _plain(items[index]).strip()[:300] != text:
        raise ContentError("This checklist changed. Reload and try again.")
    items[index]["attrs"] = {"checked": checked}
    return copy


# ------------------------------------------------------------------ earlier live-editor notes


def _from_xml(node: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"type": node.tag}
    attrs = dict(node.attributes)
    if attrs:
        out["attrs"] = attrs
    content: list[dict[str, Any]] = []
    for child in node.children:
        if isinstance(child, pycrdt.XmlElement):
            content.append(_from_xml(child))
        elif isinstance(child, pycrdt.XmlText):
            for segment, formats in child.diff():
                if not segment:
                    continue
                text: dict[str, Any] = {"type": "text", "text": str(segment)}
                if formats:
                    text["marks"] = [
                        {
                            "type": name,
                            **({"attrs": value} if isinstance(value, dict) and value else {}),
                        }
                        for name, value in formats.items()
                    ]
                content.append(text)
    if content:
        out["content"] = content
    return out


def from_legacy(snapshot: bytes | None, updates: list[bytes]) -> dict[str, Any] | None:
    """The document saved by the earlier live editor, or None if there was nothing."""
    if snapshot is None and not updates:
        return None
    doc: pycrdt.Doc[Any] = pycrdt.Doc()
    for blob in ([snapshot] if snapshot else []) + updates:
        doc.apply_update(blob)
    fragment = doc.get("default", type=pycrdt.XmlFragment)
    blocks = [_from_xml(c) for c in fragment.children if isinstance(c, pycrdt.XmlElement)]
    return clean({"type": "doc", "content": blocks})
