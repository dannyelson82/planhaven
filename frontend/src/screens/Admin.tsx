import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { useStepUp } from '../stepupContext.ts'
import { Button, Card, ErrorText, Field } from '../ui.tsx'
import { AdminExperiments } from './Experiments.tsx'

type Invite = { id: string; email: string | null; created_at: string; expires_at: string; status: string }
type User = {
  id: string
  email: string
  display_name: string
  is_admin: boolean
  disabled: boolean
  has_second_factor: boolean
  last_seen_at: string | null
}
type Link = { url: string; expires_at: string }

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** A one-time link to hand over (text message, in person): copy, or share on a phone. */
function LinkBox({ label, link, onClose }: { label: string; link: Link; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const canShare = typeof navigator !== 'undefined' && 'share' in navigator
  return (
    <div className="space-y-2 rounded-xl bg-brand-50 p-3 dark:bg-stone-800">
      <p className="text-sm font-medium">{label}</p>
      <input readOnly value={link.url} aria-label={label} onFocus={(e) => e.currentTarget.select()}
        className="block w-full min-w-0 rounded-lg border border-stone-300 bg-white px-2 py-2 font-mono text-xs dark:border-stone-700 dark:bg-stone-900" />
      <p className="text-xs text-stone-500">Works once, until {when(link.expires_at)}. Anyone with the link can use it, so send it only to that person.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onPress={() => void navigator.clipboard.writeText(link.url).then(() => setCopied(true))}>
          {copied ? 'Copied' : 'Copy link'}
        </Button>
        {canShare && <Button variant="secondary" onPress={() => void navigator.share({ url: link.url }).catch(() => undefined)}>Share…</Button>}
        <Button variant="ghost" onPress={onClose}>Done</Button>
      </div>
    </div>
  )
}

/** Admin: invite people, and help them when they're locked out. Never shows anyone's projects. */
export function AdminScreen({ myId }: { myId: string }) {
  const client = useQueryClient()
  const stepUp = useStepUp()
  const invites = useQuery({ queryKey: ['admin', 'invites'], queryFn: () => stepUp(() => api<Invite[]>('GET', '/api/v1/admin/invites')) })
  const users = useQuery({ queryKey: ['admin', 'users'], queryFn: () => stepUp(() => api<User[]>('GET', '/api/v1/admin/users')) })
  const refresh = () => client.invalidateQueries({ queryKey: ['admin'] })
  const [email, setEmail] = useState('')
  const [invite, setInvite] = useState<Link | null>(null)
  const createInvite = useMutation({
    mutationFn: () => stepUp(() => api<Link>('POST', '/api/v1/admin/invites', email.trim() ? { email: email.trim() } : {})),
    onSuccess: async (link) => { setInvite(link); setEmail(''); await refresh() },
  })
  const cancelInvite = useMutation({ mutationFn: (id: string) => stepUp(() => api('DELETE', `/api/v1/admin/invites/${id}`)), onSettled: refresh })
  const pending = (invites.data ?? []).filter((i) => i.status === 'pending')

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Admin</h1>

      <Card className="space-y-3">
        <h2 className="font-semibold">Invite someone</h2>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Make a link and send it to them. They choose their own name and password, then set up an authenticator app or passkey.
        </p>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); createInvite.mutate() }}>
          <div className="min-w-0 flex-1">
            <Field label="Their email (optional)" type="email" maxLength={254} value={email} onChange={setEmail}
              description="If given, only this email can use the link." />
          </div>
          <Button type="submit" isDisabled={createInvite.isPending}>Make invite link</Button>
        </form>
        {invite && <LinkBox label="Invite link" link={invite} onClose={() => setInvite(null)} />}
        {pending.length > 0 && (
          <ul className="space-y-1 text-sm">
            {pending.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">{i.email ?? 'Anyone with the link'} · until {when(i.expires_at)}</span>
                <Button variant="danger-ghost" aria-label={`Cancel invite ${i.email ?? ''}`.trim()} onPress={() => cancelInvite.mutate(i.id)}>Cancel</Button>
              </li>
            ))}
          </ul>
        )}
        <ErrorText error={createInvite.error ?? cancelInvite.error ?? invites.error} />
      </Card>

      <section aria-label="People" className="space-y-2">
        <h2 className="text-lg font-semibold">People</h2>
        {(users.data ?? []).map((u) => <UserCard key={u.id} user={u} isMe={u.id === myId} onChanged={refresh} />)}
        <ErrorText error={users.error} />
        {users.error && <Button variant="secondary" onPress={() => void refresh()}>Try again</Button>}
      </section>
      <AdminExperiments />
    </div>
  )
}

function UserCard({ user, isMe, onChanged }: { user: User; isMe: boolean; onChanged: () => Promise<unknown> }) {
  const stepUp = useStepUp()
  const [reset, setReset] = useState<Link | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const act = useMutation({
    mutationFn: (action: string) => stepUp(async () => {
      if (action === 'password') {
        setReset(await api<Link>('POST', `/api/v1/admin/users/${user.id}/password-reset`))
      } else if (action === 'second-factor') {
        await api('POST', `/api/v1/admin/users/${user.id}/reset-second-factor`)
      } else if (action === 'disable' || action === 'enable') {
        await api('POST', `/api/v1/admin/users/${user.id}/disabled`, { value: action === 'disable' })
      } else if (action === 'admin' || action === 'not-admin') {
        await api('POST', `/api/v1/admin/users/${user.id}/admin`, { value: action === 'admin' })
      }
    }),
    onSettled: async () => { setConfirm(null); await onChanged() },
  })
  // Risky actions take a second tap.
  const twice = (action: string) => (confirm === action ? act.mutate(action) : setConfirm(action))
  const badges = [user.is_admin && 'admin', user.disabled && 'disabled', !user.has_second_factor && 'no second factor yet'].filter(Boolean)
  return (
    <article aria-label={user.display_name}>
    <Card className="space-y-2">
      <div>
        <p className="font-semibold">{user.display_name}{isMe && ' (you)'}</p>
        <p className="text-sm text-stone-500">{user.email}{badges.length > 0 && ` · ${badges.join(' · ')}`}</p>
        <p className="text-xs text-stone-500">{user.last_seen_at ? `Last active ${when(user.last_seen_at)}` : 'Never signed in'}</p>
      </div>
      {!isMe && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onPress={() => act.mutate('password')} isDisabled={act.isPending || user.disabled}>Password reset link</Button>
          {user.has_second_factor && (
            <Button variant="secondary" onPress={() => twice('second-factor')} isDisabled={act.isPending}>
              {confirm === 'second-factor' ? 'Tap again: remove their second factor' : 'Reset second factor'}
            </Button>
          )}
          <Button variant={user.disabled ? 'secondary' : 'danger-ghost'} onPress={() => (user.disabled ? act.mutate('enable') : twice('disable'))} isDisabled={act.isPending}>
            {user.disabled ? 'Enable account' : confirm === 'disable' ? 'Tap again to disable' : 'Disable account'}
          </Button>
          <Button variant="ghost" onPress={() => twice(user.is_admin ? 'not-admin' : 'admin')} isDisabled={act.isPending}>
            {confirm === 'admin' ? 'Tap again: make admin' : confirm === 'not-admin' ? 'Tap again: remove admin' : user.is_admin ? 'Remove admin' : 'Make admin'}
          </Button>
        </div>
      )}
      {reset && <LinkBox label={`Password reset link for ${user.display_name}`} link={reset} onClose={() => setReset(null)} />}
      <ErrorText error={act.error} />
    </Card>
    </article>
  )
}
