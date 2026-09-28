"""The Markdown copy of a note, made on the server from the note's CRDT document.

Used for previews, search, AI and export. Computed from what is actually stored, so it can't
be stale or out of order (browsers used to send it, which could).
"""

from typing import Any

import pycrdt

_MARKS = (("code", "`", "`"), ("strike", "~~", "~~"), ("italic", "*", "*"), ("bold", "**", "**"))
_LISTS = ("bulletList", "orderedList", "taskList")


def _inline(node: Any) -> str:
    out: list[str] = []
    for child in node.children:
        if isinstance(child, pycrdt.XmlText):
            for text, attrs in child.diff():
                piece = str(text)
                for name, before, after in _MARKS:
                    if attrs and name in attrs:
                        piece = f"{before}{piece}{after}"
                out.append(piece)
        elif isinstance(child, pycrdt.XmlElement):
            out.append("\n" if child.tag == "hardBreak" else _inline(child))
    return "".join(out)


def _block(node: Any, depth: int) -> str:
    tag = node.tag
    blocks = [_block(c, depth) for c in node.children if isinstance(c, pycrdt.XmlElement)]
    if tag == "paragraph":
        return _inline(node)
    if tag == "heading":
        level = int(node.attributes.get("level") or 2)
        return f"{'#' * max(1, min(level, 6))} {_inline(node)}"
    if tag == "blockquote":
        return "\n".join(f"> {b}" for b in blocks)
    if tag == "codeBlock":
        return f"```\n{_inline(node)}\n```"
    if tag == "horizontalRule":
        return "---"
    if tag in _LISTS:
        lines = []
        items = [c for c in node.children if isinstance(c, pycrdt.XmlElement)]
        for i, item in enumerate(items):
            if tag == "orderedList":
                marker = f"{i + 1}."
            elif tag == "taskList":
                marker = f"- [{'x' if item.attributes.get('checked') is True else ' '}]"
            else:
                marker = "-"
            parts = [
                _block(c, depth + 1) for c in item.children if isinstance(c, pycrdt.XmlElement)
            ]
            first, rest = (parts[0], parts[1:]) if parts else ("", [])
            lines.append("\n".join([f"{'  ' * depth}{marker} {first}", *rest]))
        return "\n".join(lines)
    return _inline(node)


def to_markdown(doc: pycrdt.Doc[Any]) -> str:
    fragment = doc.get("default", type=pycrdt.XmlFragment)
    blocks = [_block(c, 0) for c in fragment.children if isinstance(c, pycrdt.XmlElement)]
    return "\n\n".join(blocks).strip()
