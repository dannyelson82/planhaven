"""Note documents: checkbox text as the editor shows it (ADR 0016)."""

from app.services import note_content


def _para(text: str) -> dict[str, object]:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


# Backspace at the start of a checkbox line joins it onto the one above: one checkbox, two
# paragraphs. The card must show both lines, not run them together.
JOINED = {
    "type": "doc",
    "content": [
        {
            "type": "taskList",
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"checked": False},
                    "content": [_para("keep the title link as well."), _para("edit list titles.")],
                },
                {"type": "taskItem", "attrs": {"checked": False}, "content": [_para("costs")]},
            ],
        }
    ],
}


def test_a_checkbox_with_two_paragraphs_keeps_them_apart() -> None:
    assert note_content.checklist(JOINED) == [
        (0, "keep the title link as well.\nedit list titles.", False),
        (1, "costs", False),
    ]
    ticked = note_content.with_checked(
        JOINED, 0, "keep the title link as well.\nedit list titles.", True
    )
    assert note_content.checklist(ticked)[0][2] is True


def test_line_breaks_inside_a_checkbox_are_kept() -> None:
    item = {
        "type": "taskItem",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "one"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "two"},
                ],
            }
        ],
    }
    doc = {"type": "doc", "content": [{"type": "taskList", "content": [item]}]}
    assert note_content.checklist(doc) == [(0, "one\ntwo", False)]
