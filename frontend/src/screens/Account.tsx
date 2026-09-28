import { useQuery } from '@tanstack/react-query'
import { api, type Session } from '../api.ts'
import { deviceName } from '../devices.ts'
import { Card, Link } from '../ui.tsx'
import { SignOutButton } from './Auth.tsx'

type SessionInfo = { id: string; last_seen_at: string; ip: string | null; user_agent: string | null; current: boolean }

export function AccountScreen({ session }: { session: Session }) {
  const about = useQuery({ queryKey: ['about'], queryFn: () => api<{ version: string }>('GET', '/api/v1/about') })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionInfo[]>('GET', '/api/v1/auth/sessions') })
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Account</h1>
      <Card>
        <p className="font-semibold">{session.user.display_name}</p>
        <p className="text-sm text-stone-500">{session.user.email}{session.user.is_admin && ' · admin'}</p>
      </Card>
      <Card className="py-3">
        <Link to="/trash" className="font-medium text-brand-700 dark:text-brand-100">Trash</Link>
        <p className="text-sm text-stone-500">Bring back something deleted in the last 30 days.</p>
      </Card>
      <Card>
        <h2 className="mb-2 font-semibold">Signed-in devices</h2>
        <ul className="space-y-2 text-sm">
          {(sessions.data ?? []).map((s) => (
            <li key={s.id}>
              <span className="font-medium">{deviceName(s.user_agent)}</span>
              {s.current && <strong className="text-brand-700 dark:text-brand-100"> · this device</strong>}
              <span className="block text-xs text-stone-500">{s.ip} · last active {new Date(s.last_seen_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      </Card>
      <SignOutButton />
      {about.data && <p className="text-center text-xs text-stone-500">Planhaven {about.data.version}</p>}
    </div>
  )
}
