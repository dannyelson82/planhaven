# ADR 0017: Project pages arranged as tiles, per person

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The maintainer wants to arrange a project page freely: for example, one note at the top with
a photo beside or below it. Some things should stay together (tasks, quotes and costs, a
list's items). Each project is arranged on its own. Each person has their own arrangement,
and people a project is shared with start from the arrangement of the person who shared it.

## Options considered

1. **Section order only.** Simple, but can't put a single note or photo at the top.
2. **Tiles in a packed grid, arranged with drag and drop.** The groups (tasks, lists, notes,
   files, quotes and costs) are tiles; any single note, list or file can be given its own
   tile; each tile is narrow, wide or full width. Uses React Aria's drag and drop (touch,
   mouse and keyboard), already a dependency.
3. **Free placement with resizing (dashboard grid library).** Most flexible, but a new
   dependency, weaker on phones and keyboards, and more to maintain.

## Decision

Option 2.

- Stored per project and person in `project_layouts` (migration 0022): an ordered list of
  tiles, each `{kind, id?, width}`. The API allows only known kinds and widths, requires an
  id exactly for single items, and at most 100 tiles; the server drops repeats and adds any
  missing group.
- Someone who hasn't arranged a project sees the owner's arrangement (only owners share
  projects), or the default; "Go back to the shared arrangement" deletes their own.
- Viewers can arrange their own view. Tiles for things since deleted, or not visible to the
  person, aren't shown.
- On a computer the grid has six columns (narrow 2, wide 4, full 6, packed densely); on a
  phone tiles stack in order.

## Consequences

- One more table under RLS (forced), writable only by its owner; members of a project can
  read each other's arrangements for it (kinds, widths, and ids of things they can already
  see). No new dependency. No new threats.
- New tile kinds (e.g. purchases) need adding to the API's list and the page.
