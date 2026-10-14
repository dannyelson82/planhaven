# ADR 0020: AI apps can edit, delete and share project content

- **Status:** Accepted
- **Date:** 2026-10-14
- **Changes:** ADR 0019 and A§12.3–12.4 (tools); SECURITY.md §4, §7.4, §7.7 and §7.18; ADR
  0012's "no delete" rule, for the MCP connector only

## Context

v0.4.0 gave AI apps add-only writes plus project edits and completing a task; delete tools were
deliberately left out (A§12.3) as a prompt-injection control (S§7.7). The maintainer wants to
work side by side with Claude on projects through the connector: "full Claude control, delete,
modify anything in a project". An add-only AI can't tidy, correct or reorganise a project, so it
can't do that work.

Two things make deletes safer now than when A§12.3 was written: everything a project holds goes
to a 30-day Trash with Restore (phase 0.3), and every AI write is recorded on the AI page with
Undo (v0.4.0).

## Decision

**Scope (maintainer, 2026-10-14):** a write connection can do anything the person can do *inside
their projects*: create, edit and delete projects, tasks, notes, lists, list items, files
(delete only; no upload or download), quotes, costs, contacts and assets (with their readings,
schedules and records); complete and un-complete tasks; check and uncheck items; move items.

**Household members (maintainer, 2026-10-14):** a write connection may give household members
(other accounts on the same instance) editor or viewer access to a project or asset, change it,
or remove it, as its person (who must be an owner). It needs no fresh second factor, which an AI
app can't give: the person gave one when connecting the app (`authz.AI_STEP_UP_EXEMPT`, only
for `PROJECT_SHARE` and `ASSET_SHARE`, only for an AI grant's principal). Limits, in
`authz.require_ai_member_change`: never anyone's owner role (adding, changing or removing one),
and never the person's own access. When the person approves such a suggestion, or undoes such a
change, their own session's rules apply, so PlanHaven asks for their second factor. The person
added is notified as usual. People are listed to the AI by name only (no email addresses).

**Still excluded:** share links (they let anyone with the address in, with no account: the one
way an injected prompt could send content out of the instance, and an Undo can't take back what
was already seen; maintainer's choice), owners, account, passkey, notification and admin
settings, emptying the Trash or deleting for good, restoring from the Trash (the person does
that, or uses Undo), uploading or downloading files, and `local_ai_only` projects (still
invisible).

**No new consent level (maintainer's choice):** the edit and delete tools come with the existing
"read and write" scope (`projects:write`). Existing write connections gain them on upgrade;
What's new says so, and the consent and Account screens say "add, change and delete" from now
on.

**Same modes as other writes:** in "approve first" edits and deletes wait in AI suggestions like
any other change; in "apply with undo" they happen at once.

**Undo:** a delete moves the thing to the Trash, and its Undo restores it (the Trash's own
restore, with the same rights). An edit stores the fields it overwrote, and its Undo puts them
back. Deleting a project trashes the project with everything in it; Undo or Restore brings it
all back within 30 days.

**Annotations:** the delete tool (`planhaven_delete`, one tool for every kind) declares
`destructiveHint: true`, so AI apps that ask before destructive actions still ask the person in
the chat. The server instructions ask the AI to check before deleting what it wasn't asked to.

**For people building with AI apps (maintainer, 2026-10-14):** tool errors carry a stable
`code`, the `tool`, the argument at fault (`field`) and a `hint`; a read tool,
`planhaven_connection_info`, says what the connection may do, its rate limits and what no AI app
can do. Each MCP call is logged as one line (tool, outcome code, duration, connection id), never
with its arguments or any content (S§7.12).

## Consequences

- A hijacked write connection can now trash a project's content, or give a household member
  access to it. Mitigations: the person's
  rights and RLS still bound every call; approve first stays the default; deletes go to the
  Trash and are undoable for 30 days, and nothing an AI does is permanent; delete tools are
  marked destructive; per-connection write rate limits; disconnect at once. The S§4 row for
  prompt injection and S§7.7 are updated to match.
- `undo` for AI changes grows a case per new change kind, each with a test. A change whose Undo
  can no longer apply (restored meanwhile, permanently removed, or edited since) says so on the
  AI page instead of failing silently.
- The `assistant.mcp_write` experimental feature planned in ADR 0012 (never built) is no
  longer needed: its tools (contacts, quotes, costs, stages) are core under this scope.
- Shipped together as v0.4.1 (maintainer's request). The phase 0.4 security review covers it.
