# ADR 0016: Notes are saved when the person taps Done (live co-editing paused)

- **Status:** Accepted
- **Date:** 2026-09-28
- **Changes:** ADR 0011 for notes. Live updates for lists, tasks and note cards stay.

## Context

With live co-editing (ADR 0011) in daily use, the maintainer kept finding stray or doubled
text in notes after moving between the note and the project page on desktop. Several fixes
(bundled messages, server-written previews, opting out of grammar extensions) didn't make
it go away, and it couldn't be reproduced in tests. The maintainer asked to remove the live
editor and automatic saving, and to start again with a plain editor and a Done button.

## Options considered

1. **Keep hunting the bug in the live editor.** It keeps the feature, but the notes stay
   unreliable in the meantime, and trust in notes matters more than live editing.
2. **Plain editor, save on Done, refuse conflicting saves.** Simple: one request per save,
   nothing in the background that can change the text. Two people can't edit the same note
   at once. The second one to save is told, and their text isn't lost.

## Decision

Option 2.

- The note is edited in the browser. Nothing is sent until **Done**, which saves the title
  and the whole document and goes back to the project.
- A save carries the version it started from (`If-Match`). If someone saved in between, the
  save is refused (409). The person can copy their text or load the other version.
- Leaving with unsaved changes (the back link, another menu item, or the browser's back
  button) asks: save and leave, leave without saving, or keep editing. Closing the tab uses
  the browser's own warning.
- The document is stored as TipTap JSON. The server rebuilds it from an allowlist (node
  types, marks, attributes, http(s)/mailto links only) with size and depth limits, and
  writes the Markdown copy from it.
- Notes saved by the live editor are converted when read. Once saved, the new document is
  used and the old update rows are no longer read (they go when the note is deleted).
- The WebSocket stays for live updates of lists, tasks and note cards (read-only; nothing is
  accepted from the browser).

## Consequences

- Fewer moving parts: no Yjs in the browser, no note rooms, no compaction job, no
  per-keystroke messages.
- Co-editing a note at the same time isn't possible for now. It can come back later as its
  own change, with tests that reproduce the earlier bug first.
- Security: the note document is untrusted input, cleaned on the server (SECURITY.md §7.15).
  Saves go through the same authz, RLS, CSRF and audit as other writes.
