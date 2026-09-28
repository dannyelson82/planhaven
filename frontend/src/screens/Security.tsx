// Account security settings: password, passkeys, recovery codes, signed-in devices.
// Changes that affect how you sign in ask for a fresh second factor first (step-up).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { deviceName } from '../devices.ts'
import { useStepUp } from '../stepupContext.ts'
import { Button, Card, ErrorText, Field, Form } from '../ui.tsx'
import { createPasskey, passkeysSupported } from '../webauthn.ts'

type Passkey = { id: string; name: string; created_at: string; last_used_at: string | null }
type SessionInfo = { id: string; last_seen_at: string; ip: string | null; user_agent: string | null; current: boolean }
type Options = { challenge_id: string; options: Record<string, unknown> }

export function PasswordCard() {
  const stepUp = useStepUp()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const change = useMutation({
    mutationFn: () => stepUp(() => api('POST', '/api/v1/auth/password', { current_password: current, new_password: next })),
    onSuccess: () => { setCurrent(''); setNext(''); setAgain('') },
  })
  const mismatch = again.length > 0 && again !== next
  return (
    <Card>
      <h2 className="mb-2 font-semibold">Password</h2>
      <Form onSubmit={(e) => { e.preventDefault(); if (!mismatch) change.mutate() }}>
        <Field label="Current password" type="password" isRequired value={current} onChange={setCurrent} autoComplete="current-password" />
        <Field label="New password" type="password" isRequired minLength={12} value={next} onChange={setNext} autoComplete="new-password" description="At least 12 characters." />
        <Field label="Type it again" type="password" isRequired value={again} onChange={setAgain} autoComplete="new-password" description={mismatch ? "The two don't match." : undefined} />
        <ErrorText error={change.error} />
        {change.isSuccess && <p role="status" className="text-sm text-brand-700 dark:text-brand-100">Password changed. Your other devices were signed out.</p>}
        <Button type="submit" variant="secondary" isDisabled={change.isPending || mismatch}>Change password</Button>
      </Form>
    </Card>
  )
}

function CodesBox({ codes, onClose }: { codes: string[]; onClose: () => void }) {
  return (
    <div className="space-y-2 rounded-xl bg-amber-50 p-3 dark:bg-amber-950">
      <p className="text-sm font-medium">Save these recovery codes somewhere safe (a password manager, or on paper). Each works once if you lose your phone. The old codes no longer work.</p>
      <ul className="grid grid-cols-2 gap-1 font-mono text-sm">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
      <div className="flex gap-2">
        <Button variant="secondary" onPress={() => void navigator.clipboard.writeText(codes.join('\n'))}>Copy codes</Button>
        <Button variant="ghost" onPress={onClose}>I've saved them</Button>
      </div>
    </div>
  )
}

export function SecondFactorCard() {
  const client = useQueryClient()
  const stepUp = useStepUp()
  const passkeys = useQuery({ queryKey: ['passkeys'], queryFn: () => api<Passkey[]>('GET', '/api/v1/auth/passkeys') })
  const [codes, setCodes] = useState<string[] | null>(null)
  const [confirmCodes, setConfirmCodes] = useState(false)
  const add = useMutation({
    mutationFn: async () => {
      const opts = await stepUp(() => api<Options>('POST', '/api/v1/auth/passkeys/register/options'))
      const credential = await createPasskey(opts.options)
      return api<{ recovery_codes: string[] }>('POST', '/api/v1/auth/passkeys/register', {
        challenge_id: opts.challenge_id, credential, name: deviceName(navigator.userAgent).slice(0, 100),
      })
    },
    onSuccess: async (r) => { if (r.recovery_codes.length) setCodes(r.recovery_codes); await client.invalidateQueries({ queryKey: ['passkeys'] }) },
  })
  const remove = useMutation({
    mutationFn: (p: Passkey) => stepUp(() => api('DELETE', `/api/v1/auth/passkeys/${p.id}`)),
    onSettled: () => client.invalidateQueries({ queryKey: ['passkeys'] }),
  })
  const newCodes = useMutation({
    mutationFn: () => stepUp(() => api<{ recovery_codes: string[] }>('POST', '/api/v1/auth/mfa/recovery/regenerate')),
    onSuccess: (r) => { setCodes(r.recovery_codes); setConfirmCodes(false) },
  })
  return (
    <Card className="space-y-3">
      <h2 className="font-semibold">Passkeys and recovery codes</h2>
      <p className="text-sm text-stone-600 dark:text-stone-400">A passkey signs you in with Face ID, a fingerprint or your device PIN: nothing to type.</p>
      <ul className="space-y-1 text-sm">
        {(passkeys.data ?? []).map((p) => (
          <li key={p.id} className="flex items-center justify-between gap-2">
            <span className="min-w-0">
              <span className="block truncate font-medium">{p.name}</span>
              <span className="block text-xs text-stone-500">{p.last_used_at ? `Last used ${new Date(p.last_used_at).toLocaleDateString()}` : 'Not used yet'}</span>
            </span>
            <Button variant="danger-ghost" aria-label={`Remove passkey ${p.name}`} onPress={() => remove.mutate(p)} isDisabled={remove.isPending}>Remove</Button>
          </li>
        ))}
        {passkeys.data?.length === 0 && <li className="text-stone-500">No passkeys yet.</li>}
      </ul>
      <div className="flex flex-wrap gap-2">
        {passkeysSupported() && <Button variant="secondary" onPress={() => add.mutate()} isDisabled={add.isPending}>Add a passkey on this device</Button>}
        <Button variant="ghost" onPress={() => (confirmCodes ? newCodes.mutate() : setConfirmCodes(true))} isDisabled={newCodes.isPending}>
          {confirmCodes ? 'Tap again: replace my recovery codes' : 'New recovery codes'}
        </Button>
      </div>
      {codes && <CodesBox codes={codes} onClose={() => setCodes(null)} />}
      <ErrorText error={add.error ?? remove.error ?? newCodes.error} />
    </Card>
  )
}

export function DevicesCard() {
  const client = useQueryClient()
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionInfo[]>('GET', '/api/v1/auth/sessions') })
  const refresh = () => client.invalidateQueries({ queryKey: ['sessions'] })
  const signOut = useMutation({ mutationFn: (id: string) => api('DELETE', `/api/v1/auth/sessions/${id}`), onSettled: refresh })
  const others = useMutation({ mutationFn: () => api('POST', '/api/v1/auth/sessions/revoke-others'), onSettled: refresh })
  const hasOthers = (sessions.data ?? []).some((s) => !s.current)
  return (
    <Card className="space-y-2">
      <h2 className="font-semibold">Signed-in devices</h2>
      <ul className="space-y-2 text-sm">
        {(sessions.data ?? []).map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2">
            <span className="min-w-0">
              <span className="font-medium">{deviceName(s.user_agent)}</span>
              {s.current && <strong className="text-brand-700 dark:text-brand-100"> · this device</strong>}
              <span className="block text-xs text-stone-500">{s.ip} · last active {new Date(s.last_seen_at).toLocaleString()}</span>
            </span>
            {!s.current && <Button variant="danger-ghost" aria-label={`Sign out ${deviceName(s.user_agent)}`} onPress={() => signOut.mutate(s.id)}>Sign out</Button>}
          </li>
        ))}
      </ul>
      {hasOthers && <Button variant="secondary" onPress={() => others.mutate()} isDisabled={others.isPending}>Sign out all other devices</Button>}
      <ErrorText error={signOut.error ?? others.error} />
    </Card>
  )
}
