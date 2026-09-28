import type { Session } from '../api.ts'
import { Card, Link } from '../ui.tsx'
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
      <Card className="py-3">
        <Link to="/help" className="font-medium text-brand-700 dark:text-brand-100">Help and user guide</Link>
        <p className="text-sm text-stone-500">How to use every part of PlanHaven, on a phone and on a computer.</p>
      </Card>
      <Card className="py-3">
        <Link to="/trash" className="font-medium text-brand-700 dark:text-brand-100">Trash</Link>
        <p className="text-sm text-stone-500">Bring back something deleted in the last 30 days.</p>
      </Card>
      <PasswordCard />
      <SecondFactorCard />
      <DevicesCard />
    </div>
  )
}
