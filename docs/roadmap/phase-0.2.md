# Phase 0.2: Daily use

> **Status:** In progress · **Started:** 2026-09-27
> Scope: ARCHITECTURE.md §18 (0.2) and ADR 0011. Every release meets SECURITY.md §11.

**Goal:** Planhaven becomes useful every day: share projects with the household, keep lists,
write notes together in real time, attach photos and documents, track assets, contractors
and quotes, and use lists offline on the phone.

**Decided (2026-09-27):** rich-text notes with TipTap (Apple Notes style); libraries
pre-approved (yjs, y-protocols, y-indexeddb, pycrdt, TipTap, Pillow, vite-plugin-pwa);
a small signed release after each milestone, published only with the maintainer's OK.

Every milestone: RLS on new tables (and the `pg_class` test), authz matrix entries, audit
events, browser tests at phone and desktop widths, threat-model check.

## Milestone 1: Sharing (v0.1.1)

- [x] Household directory: signed-in users can look up other household members by name
      (display name + email only) to share with; admins unchanged
- [x] Project members API: list, add, change role, remove (owner only; step-up for sharing
      changes, S§7.1); last owner can't leave or be removed; notifications to people added
- [x] Sharing screen on the project page; role shown on project cards
- [x] Task details: edit title, notes and due date; friendlier "signed-in devices" names

## Milestone 2: Lists (v0.1.2)

- [x] Lists and list items (shopping, parts, checklist) per project, with quantity and
      optional price; reorder; check off
- [x] API with pagination, `If-Match`, `Idempotency-Key` on writes (for offline replay)
- [x] Lists screen, phone-first; check-off with one tap

## Milestone 3: Notes and real-time collaboration (v0.1.3)

- [x] ADR 0011 implemented: authenticated WebSocket (`/api/v1/collab/notes/{note_id}`) with
      Origin check, authz at connect and re-checked every 15 s, viewer updates rejected,
      size, rate and per-user connection limits, no content in logs (S§7.15)
- [x] Notes as Yjs documents (pycrdt server side): updates stored under RLS with
      attribution, compacted by a worker job; derived Markdown for search and export
- [x] TipTap editor with collaboration cursors; works under the CSP (no injected styles)
- [x] Live updates for projects, tasks, lists and notes on a separate per-project socket
      (`/api/v1/live/projects/{project_id}`); it carries only the kind of change

## Milestone 4: Attachments and photos (v0.1.4)

- [x] Upload pipeline (A§10): streamed size limit, type from bytes, allowlist, SHA-256
      content-addressed blobs in `/data`; unreferenced blobs purged by the maintenance job
- [x] Images: EXIF GPS stripped by default (Pillow, in a separate resource-limited process),
      thumbnails; take a photo from the phone
- [x] Downloads always `Content-Disposition: attachment` + `nosniff` + a sandboxing CSP;
      inline previews only for images we re-encoded (PDF previews wait for the extraction
      sandbox in 0.5); upload rate limits

## Milestone 5: Assets, contacts and quotes (v0.1.5)

- [x] Assets (vehicle, boat, house, …) with metadata, shareable; projects link to an asset;
      an asset's projects form its service history
- [x] Contacts (contractors, suppliers), shared one by one like assets; quotes (requested /
      received / accepted / declined, with a document), cost entries per project; amounts in
      Canadian dollars by default

## Milestone 6: Phone and offline (v0.2.0)

- [x] Installable PWA (`vite-plugin-pwa`): icons, standalone display; the app opens offline
      and says when the server can't be reached
- [x] Offline lists and open tasks in IndexedDB; check-offs queued and replayed with
      idempotency keys; conflicts shown; caches cleared on sign-out (A§13.4). Tasks are
      read-only offline for now; list items can be added and checked off.
- [x] Trash: soft-deleted items restorable for 30 days, then purged by a worker job
- [x] Phase security review against S§11 (`docs/releases/v0.2.0-security-review.md`);
      release v0.2.0 once the maintainer approves
