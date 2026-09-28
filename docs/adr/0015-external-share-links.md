# ADR 0015: External share links for people without an account

- **Status:** Accepted; built in v0.2.16 (migration 0026, SECURITY.md §7.16)
- **Date:** 2026-09-28

## Context

The maintainer wants to share part of a project with someone outside the household, without
giving them an account. Example: a car service project with tasks ("Change oil", "Flush
coolant") that carry instructions. The mechanic opens one link, reads the tasks, checks them
off, adds photos, and writes in a "Service notes" note.

PlanHaven is on the internet and every account has a mandatory second factor (S§7.1). A share
link is the opposite: whoever holds the link gets in. It is a **capability URL**, so it must
be narrow, visible, revocable and short-lived.

## Options considered

1. **Guest accounts** (invite the mechanic as a limited user). Strongest identity, but a
   mechanic won't set up a password and an authenticator app for one oil change.
2. **Read-only public page.** Simple, but the mechanic can't check anything off.
3. **Share links with per-component permissions.** One link, the owner ticks exactly what the
   person may see and do, in plain language.

## Decision

Option 3.

**Creating a link** (project owners and editors, with step-up like other sharing). The form
asks for a name for the link ("Dave's Garage, spring service"), how long it lasts, and a list
of plain-language tick boxes, for example:

- Tasks: "See these tasks and their instructions" (all, or chosen tasks) · "Tick tasks off"
- Notes: "Read these notes" (chosen notes) · "Add to the note 'Service notes'" (append only:
  a guest can add text but never change or delete what's there)
- Photos and files: "See photos and files" · "Add photos"
- Lists: "See these lists" · "Tick items off"

Never available through a link: deleting anything, sharing, members' names or emails,
contacts, quotes and costs (unless a later version adds a box for them), other projects,
anything in the admin console.

**Using a link.** `https://<host>/s/#phv_shr_<token>`. The token sits after `#`, so it never
reaches server logs, proxies or `Referer` headers. The guest types their name once ("Dave");
every change they make is recorded as "Dave (via link 'Dave's Garage')". The guest sees a
simple page with only what was ticked. No account, no access to the rest of the app.

**Controls:**
- Token: 256 random bits, stored only as a hash; `phv_shr_` prefix, so secret scanning and
  log redaction catch it (docs/repo-setup.md, `.gitleaks.toml`).
- Expiry required: default 30 days, longest 1 year. Revoke at any time from the project.
- Optional 6-digit PIN sent separately (text it to the mechanic), rate limited per link.
  **Off by default**; the owner ticks it on per link.
- Every link has an activity log; the owner can see when it was used.
- Authorization: a new **link principal** checked by `authz.require` against the link's ticked
  permissions, and enforced again by RLS via the link's ID (same two layers as users,
  S§7.4, A§8.3). New authz matrix column for link principals.
- Rate limits per link and per IP; uploads use the normal pipeline (location removed, type
  checks, size limits).
- Links stop working when the project is deleted, when the creator loses access to it, or when
  the creator's account is disabled.

## Maintainer's answers (2026-09-28)

1. PIN: optional, **off by default**.
2. Expiry: default 30 days, maximum 1 year.
3. Timing: whenever it fits best; planned right after the admin/invite screens, before
   phase 0.3.

## As built (v0.2.16)

- The database check is item by item (maintainer's choice, 2026-09-28): guest transactions
  set `app.share_link` and have no user; `app.link_allows` answers for each row; column
  guards limit guests to ticks and adding to the one note.
- Opening a link gives a guest session cookie (12 hours at most); the token itself is used
  once and never stored in the browser.
- Guests' photos are recorded as uploaded by the link's creator (the account behind the
  link), with the guest's name in the link's activity.
- Quotes, costs and asset details stay out of links for now.

## Consequences

The first way into PlanHaven without a second factor, limited to what one link allows. Needs
threat-model entries (link forwarded or leaked, brute force, guest uploads, a guest writing
into a note), a new authz principal and matrix column, and tests that a link can never reach
anything it wasn't given.
