import { useQuery } from '@tanstack/react-query'
import { api, type Session } from '../api.ts'
import { Card, Link } from '../ui.tsx'
import { DevicesCard, PasswordCard, SecondFactorCard } from './Security.tsx'

export function AccountScreen({ session }: { session: Session }) {
  const about = useQuery({ queryKey: ['about'], queryFn: () => api<{ version: string }>('GET', '/api/v1/about') })
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
        <Link to="/trash" className="font-medium text-brand-700 dark:text-brand-100">Trash</Link>
        <p className="text-sm text-stone-500">Bring back something deleted in the last 30 days.</p>
      </Card>
      <PasswordCard />
      <SecondFactorCard />
      <DevicesCard />
      {about.data && <p className="text-center text-xs text-stone-500">Planhaven {about.data.version}</p>}
    </div>
  )
}
