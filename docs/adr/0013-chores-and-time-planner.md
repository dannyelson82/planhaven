# ADR 0013: Household chores with proof of completion, and a personal time planner

- **Status:** Accepted
- **Date:** 2026-09-27
- **Changes:** roadmap (ARCHITECTURE.md §18): chores join phase 0.3, a new phase 0.4 "Time
  planner", and the cut-list plugin moves from 0.4 to 0.7.

## Context

The maintainer asked for two things:

1. **Chores and assigned tasks:** give scheduled tasks to other household members (e.g. a
   child: take out the trash and recycling every Tuesday, cut the lawn), notify them on their
   phone when it's time, and ask for proof, such as a photo, when they mark it done.
2. **Personal time management:** the maintainer works a two-weeks-on, two-weeks-off rotation
   far from home and has ADHD. Balancing rest with home projects is hard, and many projects
   end up half finished. Planhaven should help plan and pace the time at home.

## Decision

### Chores and assignments (phase 0.3)

- A task can be **assigned** to any household member, once or on a **schedule** (RRULE
  subset: daily, weekly on given days, every N weeks, monthly; with a time of day), with
  reminders if it isn't done.
- A task may **require proof**: none, a photo, or a short note. Completing it then creates a
  submission (`pending_approval`) that the assigner **approves or sends back** with a comment.
- **Household members with limited access:** an assignee sees and completes the tasks
  assigned to them (with the task's title, instructions and due time) without becoming a
  member of the project. RLS: a task is visible to project members **or its assignee**.
  Proof photos are visible to the assignee, the assigner and project members only.
- Children get normal accounts. The second factor stays mandatory: a **passkey on their own
  phone** (Face ID / fingerprint) gives passwordless, phishing-resistant sign-in that's easy
  for kids. No weaker PIN or shared-device mode.
- Notifications use Web Push (A§13.3): "Chore due: Take out the trash" (title only, never
  notes or photos), a reminder, then "Done? Add a photo". Quiet hours respected.
- Photos use the upload pipeline (A§10): type-checked, EXIF GPS stripped, stored as blobs.

### Time planner (phase 0.4)

- **Availability:** each user can define a **work rotation** (e.g. 14 days on, 14 off, from an
  anchor date) plus one-off away periods. Planhaven knows which days are "home days".
- **Capacity, rest first:** per home day, the user sets how much time is available for
  projects and chores; rest days are protected and planned first. The planner never fills
  more than the capacity.
- **Home-stretch plan:** before each home period, Planhaven proposes a realistic plan from
  due dates, priorities and capacity. The user adjusts and accepts it; planned blocks appear in
  the ICS calendar feed (A§13.2) and as reminders.
- **Finishing over starting (ADHD-friendly):**
  - a limit on projects "In progress" at once (default 3);
  - one visible **"next small step"** per project;
  - a gentle **stalled projects** view (no activity in N days) where each can be finished,
    parked or dropped;
  - a short weekly review prompt.
- **Away periods:** tasks that don't need the user at home (calls, ordering parts, booking a
  contractor) are marked "can do remotely" and surfaced while away, so home time goes to
  hands-on work.
- The first version is rule-based and predictable. The AI assistant (ADR 0012) may later
  *suggest* plans, as an experimental feature, never applying them without approval.

### Roadmap

0.3 iPhone **and chores** → **0.4 Time planner (new)** → 0.5 Local AI → 0.6 MCP connector →
**0.7 Cut-list plugin (moved from 0.4)**. The plugin host skeleton and SDK boundary stay in
phase 0.1 (ADR 0008), since they are cheap now and costly to retrofit.

## Consequences

- New entities: task schedule and assignment fields, completion submissions with proof,
  work rotations and away periods, capacity settings, plans and planned blocks.
- Push notifications become central (phase 0.3), including scheduled sends by the worker.
- Security: a limited assignee view is a new access path, added to the authorization matrix
  and RLS tests; proof photos are user content under RLS; notification text is title only.
