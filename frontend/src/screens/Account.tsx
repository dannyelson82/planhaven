import { useQuery } from '@tanstack/react-query'
import { api, type Session } from '../api.ts'
import { Card } from '../ui.tsx'
import { SignOutButton } from './Auth.tsx'

type SessionInfo = { id: string; last_seen_at: string; ip: string | null; user_agent: string | null; current: boolean }

export function AccountScreen({ session }: { session: Session }) {
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionInfo[]>('GET', '/api/v1/auth/sessions') })
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Account</h1>
      <Card>
        <p className="font-semibold">{session.user.display_name}</p>
        <p className="text-sm text-stone-500">{session.user.email}{session.user.is_admin && ' · admin'}</p>
      </Card>
      <Card>
        <h2 className="mb-2 font-semibold">Signed-in devices</h2>
        <ul className="space-y-2 text-sm">
          {(sessions.data ?? []).map((s) => (
            <li key={s.id}>
              {s.user_agent ?? 'Unknown device'} {s.ip && `· ${s.ip}`} {s.current && <strong>· this device</strong>}
            </li>
          ))}
        </ul>
      </Card>
      <SignOutButton />
    </div>
  )
}
