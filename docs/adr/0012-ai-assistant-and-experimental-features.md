# ADR 0012: AI project assistant (both local and commercial models) behind experimental flags

- **Status:** Accepted
- **Date:** 2026-09-27
- **Changes:** SECURITY.md §7.7 ("no automatic actions from local AI output") and the MCP tool
  list in ARCHITECTURE.md §12.3.

> **Update 2026-09-28:** commercial assistants connect **per person**: each user links their
> own (e.g. Claude or ChatGPT) through the MCP connector's OAuth (A§12.2).

## Context

The maintainer wants both AI paths, local models (A§11) and commercial assistants via MCP
(A§12), to act as a project assistant: create and edit tasks, notes, contacts, list items
and similar items, not just answer questions. Voice chat may follow later. These
capabilities should ship as **experimental features**, off by default and enabled one by one
from an Experimental section of the admin console, until they're tested.

Main risk: prompt injection (S§4, S§7.7). A document, web page or AI response can carry hidden
instructions, and a model that can write may be tricked into changing data.

## Options considered

1. **Read-only AI** (the original design). Safe, but not an assistant.
2. **AI applies changes directly** with audit and undo. Fast; a tricked model acts before
   anyone notices.
3. **AI proposes, the user approves.** Nothing changes until a person taps Approve.
4. **Per-feature choice between 2 and 3.**

## Decision

Option 4, with approve-first as the default.

**The assistant:**
- Both local and commercial models get the same set of assistant tools: create and update
  tasks, notes, list items, contacts, quotes and cost entries; change project stage; add
  projects. **No delete tools**; no sharing, membership, account or admin tools; no raw file
  downloads.
- Every tool call runs as the signed-in user through `authz.require` and RLS: the AI can never
  do more than that user could.
- `local_ai_only` projects stay invisible to commercial models (A§11.4, A§12.4).
- Each change is recorded with its origin (`local_ai` or `mcp:<client>`), shown in the
  project activity view, and undoable.

**Execution modes, per feature:**
- **Propose and approve** (default): the model returns a change set ("add 3 tasks, update 1
  note") shown as a preview; nothing is written until the user approves all or part of it.
- **Apply directly**: changes are written immediately, then listed with one-tap undo.
- The admin chooses which modes a feature allows; each user picks among the allowed modes.

**Experimental features:**
- A registry of named features (e.g. `assistant.local`, `assistant.mcp_write`,
  `voice.chat`), each **off by default**, with a description and known risks.
- The admin makes a feature *available* in Admin → Experimental (step-up, audited); each user
  then *opts in* in their own settings. Nobody gets an experiment they didn't choose.
- Anything experimental carries an "Experimental" label in the UI.
- A feature graduates from experimental only after it has tests, a threat-model entry in
  SECURITY.md, and the maintainer's sign-off, recorded in an ADR or changelog.

**Voice chat (later, experimental):** push-to-talk in the PWA. Speech-to-text and
text-to-speech use an **admin-configured local speech server** (e.g. a Whisper/Piper server
of the kind Home Assistant uses), so audio stays in the house. Browser or cloud speech
services send audio off-site, so they're allowed only as a separate, clearly labelled opt-in.

## Consequences

- The local assistant arrives with phase 0.5, the expanded MCP tools with phase 0.6, and the
  experimental-features framework with the first of them. Voice chat is "Later".
- New components then: a tool/change-set layer shared by both AI paths, the approval UI,
  the undo view, the feature registry and admin/user settings.
- Rate limits per user and per OAuth client on assistant writes (S§7.11).
- Prompt injection remains possible; the design limits impact (user's permissions only, no
  deletes, approve-first default, attribution and undo).
