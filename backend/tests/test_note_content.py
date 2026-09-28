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


def _task(text: str, checked: bool = False, *children: dict[str, object]) -> dict[str, object]:
    return {"type": "taskItem", "attrs": {"checked": checked}, "content": [_para(text), *children]}


def test_cards_show_the_note_in_its_own_order() -> None:
    doc = {
        "type": "doc",
        "content": [
            _para("Intro"),
            {"type": "paragraph"},  # blank lines are left out
            {
                "type": "taskList",
                "content": [
                    _task("Parent", False, {"type": "taskList", "content": [_task("Child", True)]}),
                    _task("Second"),
                ],
            },
            {"type": "orderedList", "content": [{"type": "listItem", "content": [_para("Step")]}]},
            _para("After"),
        ],
    }
    lines, more = note_content.card_lines(doc)
    assert more == 0
    assert [(line["kind"], line["text"], line["depth"]) for line in lines] == [
        ("text", "Intro", 0),
        ("check", "Parent", 0),
        ("check", "Child", 1),
        ("check", "Second", 0),
        ("bullet", "Step", 0),
        ("text", "After", 0),
    ]
    # Each checkbox carries the index and text that ticking it needs.
    checks = [
        (line["index"], line["text"], line["checked"]) for line in lines if line["kind"] == "check"
    ]
    assert sorted(checks) == note_content.checklist(doc)
    assert lines[4]["marker"] == "1."


def test_long_notes_say_how_much_is_left_out() -> None:
    doc = {"type": "doc", "content": [_para(f"line {i}") for i in range(250)]}
    lines, more = note_content.card_lines(doc)
    assert (len(lines), more) == (note_content.CARD_LINES, 50)
