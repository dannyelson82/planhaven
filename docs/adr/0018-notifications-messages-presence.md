# ADR 0018: Notifications screen, messages between users, and online status

- **Status:** Accepted
- **Date:** 2026-10-02

## Context

After testing 0.2, the maintainer asked for a notifications screen with an icon and unread
indicator, messages between users, and a way to see who's online (testing notes, 2026-10-02).
Phase 0.3 already planned Web Push and notification preferences (A§13.3, A§15) and chores
with reminders (ADR 0013), which need the same notification service. Messages are a new kind of
private content: they are between people, not inside a project, so project RLS doesn't cover
them.

PlanHaven is invite-only: every account was created through an admin's invite.

## Options considered

1. **Who can message whom**
   - Anyone with an account: one people list, no setup; everyone was invited by the admin.
   - Only people who share a project: tighter, but someone new can't be reached until a
     project is shared.
2. **Message privacy**
   - Like notes: stored in PostgreSQL under RLS; only the conversation's members see them in
     the app, admins can't; whoever runs the server can read the database. Previews and
     search work.
   - End-to-end encrypted: the server can't read them, but keys live on devices (lose every
     device, lose the history), no previews in notifications, no search, much more code to
     get right.
3. **Online status**
   - Online now and "last seen" for everyone, each person can hide theirs.
   - Online now only, or no status at all.

## Decision

Chosen by the maintainer on 2026-10-02:

- **Messages:** anyone with an account can message anyone (one-to-one and named group
  conversations). Stored like notes: RLS on conversations, members and messages allows only
  the conversation's members; admins have no access (A§7.2). Not end-to-end encrypted.
  Text first; photos through the existing upload pipeline. A person can delete their own
  message (it shows as deleted) and leave a conversation. Messages are kept until deleted.
- **Online status:** a green dot while someone is online (an open app session, from the
  existing live-updates connection), and "last seen" otherwise. Each person can hide theirs
  in Account; hidden means neither is shown.
- **Notifications:** the existing in-app notifications table becomes the notifications screen
  (bell with an unread count). A notification service turns events into notifications per
  person, respecting their preferences and quiet hours, and sends them in the app and by
  Web Push. Message notifications show the sender and a short preview by default; each
  person can turn previews off (lock screens).
- **Order:** notifications, then messages and online status, then chores (ADR 0013), the
  calendar feed and Reminders sync (ADR 0006), then the phase security review.

## Consequences

- New tables with RLS enabled and forced (conversations, conversation members, messages,
  push subscriptions, notification preferences), each in the `pg_class` test and the authz
  matrix.
- The server owner can read messages in the database; the user guide says so plainly.
- Web Push needs VAPID keys (generated at first boot, kept in `/config`) and outbound requests
  to the browser's push service only: an allowlist of push-service hosts (S§7.8). Push
  payloads carry minimal text and a link, never note or attachment contents.
- Online status reveals when someone uses the app; hiding it is one switch in Account, and
  "last seen" is rounded (to the minute) and only shown to signed-in members.
- Rate limits on sending messages and creating conversations; message length limits; no
  links are fetched or previewed by the server.
- New threat-model rows: messages (disclosure between users, spam, deleted-message
  remnants), presence (activity tracking), push (payload leakage, endpoint abuse).
