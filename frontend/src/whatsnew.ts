// "What's new" after an update (maintainer request, 2026-10-02): one entry per release with
// something people will notice, newest first. Every release that adds or changes a feature
// adds an entry here, with the user guide (CLAUDE.md). Shown once per person: the app remembers
// the newest version they've seen.
import { useSyncExternalStore } from 'react'

/** Things a tour step or a "What's new" item can set up right there. */
export type Action = 'chores' | 'home-screen' | 'push' | 'notification-settings' | 'presence' | 'projects' | 'messages' | 'invite' | 'suppliers' | 'assets'

export type Item = {
  title: string
  text: string
  steps?: string[] // the short tutorial
  action?: Action
  guide?: string // a page of the user guide (Help)
  shot?: string // a screenshot from the guide (docs/user-guide/screens/)
}

export type Release = { version: string; date: string; items: Item[] }

export const RELEASES: Release[] = [
  {
    version: '0.3.3',
    date: '2026-10-02',
    items: [
      {
        title: 'Chores',
        text: 'Give a task to someone, once or on a repeat (bins every Tuesday at 7 pm). They get a reminder, and can be asked for a photo or a note that you approve or send back.',
        steps: ['Open a task on a project.', 'Tap Chore, choose who, when it is due and how often.', 'Choose the proof: none, a photo or a note.', 'Approve it under Chores when it is done.'],
        action: 'chores',
        guide: 'chores',
        shot: 'chore-form',
      },
      {
        title: 'Chores for people outside the project',
        text: 'Someone with a chore sees only that chore, not the rest of the project. Their chores are on Projects, under Chores.',
        guide: 'chores',
        shot: 'chores',
      },
    ],
  },
  {
    version: '0.3.2',
    date: '2026-10-02',
    items: [
      {
        title: 'A welcome tour, and this',
        text: 'New people get a short tour when they first sign in, and everyone sees what changed after an update. Both stay in Help.',
        guide: 'README',
      },
    ],
  },
  {
    version: '0.3.1',
    date: '2026-10-02',
    items: [
      {
        title: 'Messages',
        text: 'Write to anyone on your PlanHaven, one to one or in a named group.',
        steps: ['Tap Messages (on a phone, in the bottom bar).', 'Tap New message and pick someone, or New group.', 'Type, then tap Send.'],
        action: 'messages',
        guide: 'messages',
        shot: 'conversation',
      },
      {
        title: "Who's online",
        text: "A green dot shows who has PlanHaven open; otherwise it says when they were last here. You can hide yours.",
        action: 'presence',
        guide: 'messages',
      },
      {
        title: 'Contacts moved (on a phone)',
        text: 'Messages took its place in the bottom bar. Contacts and Suppliers are on Account.',
      },
    ],
  },
  {
    version: '0.3.0',
    date: '2026-10-02',
    items: [
      {
        title: 'Notifications',
        text: 'The bell tells you about things shared with you, tasks due today or overdue, asset services due and more.',
        guide: 'notifications',
        shot: 'notifications',
      },
      {
        title: 'Alerts on your phone',
        text: 'Get alerts even when PlanHaven is closed. On an iPhone, from the app added to the Home Screen.',
        steps: ['Turn on phone alerts below (or in Account).', 'Tap Allow when asked.', 'Send a test from Account to check.'],
        action: 'push',
        guide: 'notifications',
      },
      {
        title: 'Your choices and quiet hours',
        text: 'Choose what reaches your phone, what stays in the app, and hours without alerts.',
        action: 'notification-settings',
        guide: 'notifications',
        shot: 'notification-settings',
      },
    ],
  },
  {
    version: '0.2.19',
    date: '2026-10-02',
    items: [
      {
        title: 'Suppliers',
        text: 'Stores and parts suppliers have their own list, and list items can name a supplier and price.',
        action: 'suppliers',
        guide: 'contacts',
      },
      {
        title: 'Keeping assets serviced',
        text: 'Record odometer and hour readings and the maintenance schedule from the manual; PlanHaven shows what is due.',
        steps: ['Open an asset.', 'Under Service, add a reading and a schedule.', 'Tap Mark done when a service is done.'],
        action: 'assets',
        guide: 'assets',
        shot: 'asset-service',
      },
      { title: 'Archive notes', text: 'Done with a note? Archive it from its card; Restore brings it back.', guide: 'notes' },
    ],
  },
]

export const LATEST = RELEASES[0].version

function newer(a: string, b: string): boolean {
  const x = a.split('.').map(Number)
  const y = b.split('.').map(Number)
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i]
  return false
}

/**
 * Releases to show, all together (cumulative, maintainer request 2026-10-02): everything newer
 * than the last one seen; with none seen yet, everything since the account was made.
 */
export function unseen(seen: string | null, memberSince: string | null): Release[] {
  if (seen !== null) return RELEASES.filter((r) => newer(r.version, seen))
  if (memberSince === null) return RELEASES.slice(0, 1)
  const joined = memberSince.slice(0, 10)
  return RELEASES.filter((r) => r.date >= joined)
}

/** A brand-new account (made since the latest release) has no news to catch up on. */
export function isNewAccount(memberSince: string | null): boolean {
  return memberSince !== null && memberSince.slice(0, 10) >= RELEASES[0].date
}

// Opening the tour or "What's new" again from Help.
type Open = 'welcome' | 'whats-new' | null
let open: Open = null
const listeners = new Set<() => void>()
export function openTour(which: Open): void {
  open = which
  for (const l of listeners) l()
}
export function useOpenTour(): Open {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, () => open)
}
