# Phase 0.3: People and reminders

> **Status:** In progress · **Planned with the maintainer:** 2026-10-02
> Scope: ARCHITECTURE.md §13, §15, §18 (0.3), §21; ADR 0006, 0013, 0018. Every release meets
> SECURITY.md §11.

**Goal:** PlanHaven tells people what needs them, lets them talk to each other, and shares
the work: notifications in the app and on the phone, messages and who's online, chores with
proof, due dates in the phone's calendar, and lists in iPhone Reminders.

**Decided (2026-10-02, ADR 0018):** anyone with an account can message anyone; messages are
stored like notes (members only, admins can't read, not end-to-end encrypted); online status
with "last seen", which each person can hide; order: notifications, messages, chores,
calendar, Reminders sync. Testing notes moved here from 0.2: notifications screen, messages,
online users.

Every milestone: RLS on new tables (and the `pg_class` test), authz matrix entries, audit
events, browser tests at phone and desktop widths, threat-model check, user guide and
screenshots.

## Milestone 1: Notifications (v0.3.0)

- [x] Notifications screen: a bell with an unread count in the menu; mark read, mark all read
- [x] Notification service: events and schedules become notifications per person, deduplicated
      (A§15): added to a project or asset, shared with you, task due today and overdue, asset
      service due soon or overdue, share-link activity
- [x] Preferences per type (in the app / on the phone / off) and quiet hours, in Account
- [x] Web Push: VAPID keys at first boot, subscribe per device, allowlisted push hosts
      (S§7.8), minimal payloads; on iPhone after adding to the Home Screen

## Milestone 2: Messages and online status (v0.3.1)

- [x] One-to-one and named group conversations with anyone on the server; unread counts
- [x] Text messages; delete your own; leave a group (photos in messages: later)
- [x] Live delivery over the existing live-updates connection; notifications with an optional
      preview
- [x] Online now / last seen, shown in messages and the people list; "Hide my online status"
      in Account
- [x] Rate limits and length limits; threat-model rows for messages and presence

## Welcome tour and What's new (v0.3.2, maintainer request 2026-10-02, put first)

- [x] A step-by-step welcome tour on first sign-in (once per person, existing people too; admins
      get inviting and safety steps), with "set it up now" buttons and guide pictures
- [x] "What's new" after an update: cumulative since the person last looked (or since they
      joined), with a short how-to and set-up buttons per feature; both reopen from Help
- [x] Per-person state on the server (migration 0031); entries in `frontend/src/whatsnew.ts`

## Milestone 3: Chores (v0.3.3, ADR 0013)

- [x] Assign a task to anyone, once or repeating (RRULE subset with a time of day)
- [x] Reminders until done; assignees see their chores without project membership (RLS)
- [x] Proof: none, photo or note; the assigner approves or sends back

## Milestone 4: Calendar feed (v0.3.4, released together with milestone 5)

- [x] Secret, revocable ICS feed per person: tasks with due dates, chores, asset services due;
      "titles only" by default

## Milestone 5: iPhone Reminders (v0.3.4)

- [x] Personal access tokens with a `sync` scope; sync pull and push API (A§13.1)
- [x] Setup guide with a step-by-step Shortcut recipe (a signed .shortcut file needs a Mac)

## Wrap-up

- [ ] Phase security review against SECURITY.md §11
