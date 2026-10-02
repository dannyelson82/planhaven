import type { Session } from '../api.ts'
import { Card, Link } from '../ui.tsx'
import { MyExperiments } from './Experiments.tsx'
import { NotificationSettingsCard } from './Notifications.tsx'
import { PresenceCard } from './Messages.tsx'
import { FeedsCard } from './Feeds.tsx'
import { SignOutButton } from './Auth.tsx'
import { DevicesCard, PasswordCard, SecondFactorCard } from './Security.tsx'

export function AccountScreen({ session }: { session: Session }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Account</h1>
      <Card>
        <p className="font-semibold">{session.user.display_name}</p>
        <p className="text-sm text-stone-500">{session.user.email}{session.user.is_admin && ' · admin'}</p>
      </Card>
      {session.user.is_admin && (
        <Card className="py-3">
          <Link to="/admin" className="font-medium text-brand-700 dark:text-brand-100">Admin</Link>
          <p className="text-sm text-stone-500">Invite people, reset a forgotten password or a lost second factor.</p>
        </Card>
      )}
      {/* On a phone the bottom bar has Messages instead; Contacts and Suppliers are here. */}
      <Card className="py-3 md:hidden">
        <Link to="/contacts" className="font-medium text-brand-700 dark:text-brand-100">Contacts</Link>
        <p className="text-sm text-stone-500">Contractors and other people you work with, and <Link to="/suppliers" className="underline">Suppliers</Link>.</p>
      </Card>
      <Card className="py-3">
        <Link to="/templates" className="font-medium text-brand-700 dark:text-brand-100">Templates</Link>
        <p className="text-sm text-stone-500">Lists and sets of tasks saved for later projects.</p>
      </Card>
      <Card className="py-3">
        <Link to="/help" className="font-medium text-brand-700 dark:text-brand-100">Help and user guide</Link>
        <p className="text-sm text-stone-500">How to use every part of PlanHaven, on a phone and on a computer.</p>
      </Card>
      <Card className="py-3">
        <Link to="/trash" className="font-medium text-brand-700 dark:text-brand-100">Trash</Link>
        <p className="text-sm text-stone-500">Bring back something deleted in the last 30 days.</p>
      </Card>
      <NotificationSettingsCard />
      <PresenceCard />
      <FeedsCard />
      <MyExperiments />
      <PasswordCard />
      <SecondFactorCard />
      <DevicesCard />
      {/* On a phone the bottom bar has the bell instead of Sign out. */}
      <SignOutButton className="w-full md:hidden" />
    </div>
  )
}
