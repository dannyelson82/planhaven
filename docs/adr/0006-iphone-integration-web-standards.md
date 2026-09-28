# ADR 0006: iPhone integration via Shortcuts, ICS, Web Push and PWA (no native app)

- **Status:** Accepted
- **Date:** 2026-09-26

> **Update 2026-09-28:** native iPhone and Android apps are now planned for later
> (ARCHITECTURE.md §18, §19.2). This decision still holds for phase 0.3.

## Context

Shopping lists and tasks must reach the iPhone: Reminders, Calendar and notifications (A§1.1).
Apple provides no server API for Reminders. A native app needs an Apple developer account,
App Store review, and ongoing maintenance for every self-hosted instance.

## Options considered

1. **Web standards plus Apple Shortcuts.** Reminders sync via a published Shortcut with a
   scoped token; Calendar via a subscribed ICS feed; Web Push; an installable PWA with offline
   lists. No App Store. The Shortcut runs on triggers rather than instantly, and the ICS token
   has to sit in a URL.
2. **Native iOS app.** Best integration (EventKit, background sync). High cost, App Store
   dependency, and a larger attack surface to maintain.
3. **CalDAV server.** Standards-based calendar and reminders sync. A large, complex protocol
   to implement securely; Reminders support over CalDAV is inconsistent.

## Decision

Use **Apple Shortcuts** for Reminders sync (`/api/v1/sync/*`, `phv_sync_` token), a per-user
**ICS feed** (`/ics/<token>.ics`), **Web Push** with VAPID, and an installable **PWA** with
offline lists (A§13).

## Consequences

- No native app to build, sign or review.
- Security trade-offs accepted in S§10:
  - The ICS token appears in a URL. It is read-only, "titles only" by default, and easy to
    regenerate.
  - The sync token is stored in the Shortcut. It is narrowly scoped and revocable, and its
    last use is shown.
- Push payloads contain minimal text; outbound push goes only to allowlisted hosts (S§7.8).
- The service worker caches only the offline list and task set and clears caches on logout
  (A§13.4).
- Forward-auth proxies in front of the app would break the Shortcut and the calendar feed
  (ADR 0009).
