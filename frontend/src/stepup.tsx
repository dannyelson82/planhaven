// Step-up: some actions need a second factor from the last few minutes (SECURITY.md §7.1).
// `useStepUp()(action)` (stepupContext.ts) performs the action; if the server asks to confirm identity, it
// shows a dialog (authenticator code or passkey) and then retries the action once.
import { useQuery } from '@tanstack/react-query'
import { type ReactNode, useCallback, useRef, useState } from 'react'
import { Dialog, Heading, Modal } from 'react-aria-components'
import { api, ApiError } from './api.ts'
import { type Run, StepUpContext } from './stepupContext.ts'
import { Button, ErrorText, Field, Form } from './ui.tsx'
import { getPasskey, passkeysSupported } from './webauthn.ts'

function needsStepUp(e: unknown): boolean {
  return e instanceof ApiError && e.status === 403 && e.message.startsWith("Confirm it's you")
}

export function StepUpProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  // Everything waiting on the check. Several requests can need it at once (the admin screen
  // loads invites, people and experiments together); one confirmation answers them all.
  const pending = useRef<{ resolve: () => void; reject: (e: unknown) => void }[]>([])

  const run: Run = useCallback(async (action) => {
    try {
      return await action()
    } catch (e) {
      if (!needsStepUp(e)) throw e
      await new Promise<void>((resolve, reject) => {
        pending.current.push({ resolve, reject })
        setOpen(true)
      })
      return await action()
    }
  }, [])

  const close = (ok: boolean) => {
    setOpen(false)
    const waiting = pending.current
    pending.current = []
    for (const p of waiting) {
      if (ok) p.resolve()
      else p.reject(new Error('Cancelled.'))
    }
  }

  return (
    <StepUpContext.Provider value={run}>
      {children}
      <Modal isOpen={open} onOpenChange={(o) => !o && close(false)} isDismissable
        className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
        <Dialog className="w-full max-w-sm rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
          <StepUpForm onDone={() => close(true)} onCancel={() => close(false)} />
        </Dialog>
      </Modal>
    </StepUpContext.Provider>
  )
}

type Options = { challenge_id: string; options: Record<string, unknown> }

function StepUpForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const status = useQuery({
    queryKey: ['mfa-status'],
    queryFn: () => api<{ has_totp: boolean; has_passkeys: boolean }>('GET', '/api/v1/auth/mfa/status'),
  })
  const attempt = async (fn: () => Promise<void>) => {
    setError(null)
    try {
      await fn()
      onDone()
    } catch (e) {
      setError(e)
    }
  }
  const passkey = () =>
    attempt(async () => {
      const opts = await api<Options>('POST', '/api/v1/auth/passkeys/verify/options')
      const credential = await getPasskey(opts.options)
      await api('POST', '/api/v1/auth/passkeys/verify', { challenge_id: opts.challenge_id, credential })
    })
  return (
    <div className="space-y-4">
      <Heading slot="title" className="text-lg font-semibold">Confirm it's you</Heading>
      <p className="text-sm text-stone-600 dark:text-stone-400">This change needs a quick check.</p>
      {status.data?.has_passkeys && passkeysSupported() && (
        <Button className="w-full" onPress={() => void passkey()}>Use Face ID / passkey</Button>
      )}
      {status.data?.has_totp && (
        <Form onSubmit={(e) => { e.preventDefault(); void attempt(() => api('POST', '/api/v1/auth/mfa/totp/verify', { code })) }}>
          <Field label="6-digit code from your authenticator app" inputMode="numeric" autoComplete="one-time-code" isRequired value={code} onChange={setCode} />
          <Button type="submit" variant="secondary" className="w-full">Confirm</Button>
        </Form>
      )}
      <ErrorText error={error} />
      <Button variant="ghost" className="w-full" onPress={onCancel}>Cancel</Button>
    </div>
  )
}
