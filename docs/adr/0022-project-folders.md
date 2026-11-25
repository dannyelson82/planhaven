# ADR 0022: Folders for the projects list, each person's own

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

The maintainer: "I want folders for projects; the list is too long and disorganized." The
projects page is one grid of every project you can see, newest first. Stages already sort work
by progress, but not by subject (cars, house, games). This was asked for during phase 0.5 and
is built alongside it as a small web feature; it doesn't change the roadmap.

## Options considered

1. **Shared folders**: one arrangement for everyone a project is shared with. Moving a shared
   project would move it for others too, and two people who think about the house differently
   would fight over it.
2. **Each person's own folders**: like the per-person page arrangement (ADR 0017). Nobody
   else's list changes.
3. **Tags** (a project in several groups) instead of folders: flexible, but the list gets
   longer rather than shorter.

## Decision

Option 2, with folders inside folders, and one folder per project (maintainer, 2026-11-25).

- `project_folders`: a person's folders, each optionally inside another of their folders, at
  most 5 levels deep and never inside itself (trigger). `project_folder_items`: which folder a
  project is in, for that person. Both are own-rows only (RLS); an admin can't read them.
- A project can be filed only if the person can read it. Losing access hides it from the list
  as before; its stale filing row does nothing.
- Deleting a folder moves its projects and folders up a level; it never deletes a project.
- The projects list (`GET /api/v1/projects`, and one project) carries the person's `folder_id`.
  The web app opens a folder at `/projects/folders/<id>`, with a path back to the top, "New
  folder", "Move to folder" on each project, and Rename / Move folder / Delete folder.
- Not yet: folders in the AI tools and the iPhone app's change feed (each person's own rows,
  not project content), drag and drop, and sorting inside a folder.

## Consequences

- Folders only organize; they never change who can see a project (sharing does that).
- Two new user-content tables with RLS enabled and forced, in the authz matrix and RLS tests.
- Security: folder names are personal like notes; nobody else can read them (S§7.4).
