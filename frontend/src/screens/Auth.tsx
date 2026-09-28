import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Session } from '../api.ts'
import { navigate } from '../router.ts'
import { useRefreshSession } from '../session.ts'
import { AuthPage, Button, ErrorText, Field, Form } from '../ui.tsx'
import { createPasskey, getPasskey, passkeysSupported } from '../webauthn.ts'
import { wipeOfflineData } from '../offline.ts'

type Options = { challenge_id: string; options: Record<string, unknown> }

function useSubmit() {
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<void>) => {
    setError(null)
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return { error, busy, run }
}

export function SetupScreen() {
  const refresh = useRefreshSession()
  const { error, busy, run } = useSubmit()
  const [f, setF] = useState({ setup_token: '', email: '', display_name: '', password: '' })
  return (
    <AuthPage title="Welcome! Create the admin account">
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">
        Find the one-time setup token in the container log (it starts with <code>phv_setup_</code>).
      </p>
      <Form
        onSubmit={(e) => {
          e.preventDefault()
          void run(async () => refresh(await api<Session>('POST', '/api/v1/setup', f)))
        }}
      >
        <Field label="Setup token" isRequired value={f.setup_token} onChange={(v) => setF({ ...f, setup_token: v.trim() })} />
        <Field label="Your name" isRequired value={f.display_name} onChange={(v) => setF({ ...f, display_name: v })} autoComplete="name" />
        <Field label="Email" type="email" isRequired value={f.email} onChange={(v) => setF({ ...f, email: v })} autoComplete="email" />
        <Field label="Password" type="password" isRequired minLength={12} value={f.password} onChange={(v) => setF({ ...f, password: v })} autoComplete="new-password" description="At least 12 characters. A few random words work well." />
        <ErrorText error={error} />
        <Button type="submit" isDisabled={busy} className="w-full">Create admin account</Button>
      </Form>
    </AuthPage>
  )
}

export function LoginScreen() {
  const refresh = useRefreshSession()
  const { error, busy, run } = useSubmit()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const passkeyLogin = () =>
    run(async () => {
      const opts = await api<Options>('POST', '/api/v1/auth/passkeys/login/options')
      const credential = await getPasskey(opts.options)
      await refresh(await api<Session>('POST', '/api/v1/auth/passkeys/login', { challenge_id: opts.challenge_id, credential }))
    })
  return (
    <AuthPage title="Sign in">
      <Form
        onSubmit={(e) => {
          e.preventDefault()
          void run(async () => refresh(await api<Session>('POST', '/api/v1/auth/login', { email, password })))
        }}
      >
        <Field label="Email" type="email" isRequired value={email} onChange={setEmail} autoComplete="username webauthn" />
        <Field label="Password" type="password" isRequired value={password} onChange={setPassword} autoComplete="current-password" />
        <ErrorText error={error} />
        <Button type="submit" isDisabled={busy} className="w-full">Sign in</Button>
      </Form>
      {passkeysSupported() && (
        <>
          <div className="my-4 text-center text-sm text-stone-500">or</div>
          <Button variant="secondary" className="w-full" isDisabled={busy} onPress={() => void passkeyLogin()}>
            Sign in with a passkey
          </Button>
        </>
      )}
    </AuthPage>
  )
}

type MfaStatus = { has_totp: boolean; has_passkeys: boolean }

export function SecondFactorScreen() {
  const refresh = useRefreshSession()
  const { error, busy, run } = useSubmit()
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState(false)
  const status = useQuery({ queryKey: ['mfa-status'], queryFn: () => api<MfaStatus>('GET', '/api/v1/auth/mfa/status') })
  if (status.data && !status.data.has_totp && !status.data.has_passkeys) return <EnrollScreen />
  const hasPasskeys = !!status.data?.has_passkeys && passkeysSupported()
  const verifyWithPasskey = () =>
    run(async () => {
      const opts = await api<Options>('POST', '/api/v1/auth/passkeys/verify/options')
      const credential = await getPasskey(opts.options)
      await api('POST', '/api/v1/auth/passkeys/verify', { challenge_id: opts.challenge_id, credential })
      await refresh()
    })
  return (
    <AuthPage title="Confirm it's you">
      <Form
        onSubmit={(e) => {
          e.preventDefault()
          void run(async () => {
            const path = recovery ? '/api/v1/auth/mfa/recovery/verify' : '/api/v1/auth/mfa/totp/verify'
            await api('POST', path, { code })
            await refresh()
          })
        }}
      >
        {recovery ? (
          <Field label="Recovery code" isRequired value={code} onChange={setCode} autoComplete="off" />
        ) : (
          <Field label="6-digit code from your authenticator app" isRequired inputMode="numeric" autoComplete="one-time-code" value={code} onChange={setCode} autoFocus />
        )}
        <ErrorText error={error} />
        <Button type="submit" isDisabled={busy} className="w-full">Continue</Button>
      </Form>
      <div className="mt-4 flex flex-col gap-2">
        {hasPasskeys && (
          <Button variant="secondary" isDisabled={busy} onPress={() => void verifyWithPasskey()}>Use a passkey instead</Button>
        )}
        <Button variant="ghost" onPress={() => { setRecovery(!recovery); setCode('') }}>
          {recovery ? 'Use my authenticator app' : 'Use a recovery code'}
        </Button>
        <SignOutButton />
      </div>
    </AuthPage>
  )
}

export function EnrollScreen() {
  const refresh = useRefreshSession()
  const { error, busy, run } = useSubmit()
  const [enrollment, setEnrollment] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)

  if (codes) {
    return (
      <AuthPage title="Save your recovery codes">
        <p className="mb-3 text-sm">Each code works once if you lose your phone. Store them somewhere safe, like a password manager. They won't be shown again.</p>
        <ul className="mb-4 grid grid-cols-2 gap-2 font-mono text-sm">
          {codes.map((c) => <li key={c} className="rounded-lg bg-stone-100 p-2 text-center dark:bg-stone-800">{c}</li>)}
        </ul>
        <Button className="w-full" onPress={() => void refresh()}>I've saved them</Button>
      </AuthPage>
    )
  }
  const addPasskey = () =>
    run(async () => {
      const opts = await api<Options>('POST', '/api/v1/auth/passkeys/register/options')
      const credential = await createPasskey(opts.options)
      const result = await api<{ recovery_codes: string[] }>('POST', '/api/v1/auth/passkeys/register', { challenge_id: opts.challenge_id, credential, name: 'This device' })
      if (result.recovery_codes.length) setCodes(result.recovery_codes)
      else await refresh()
    })
  return (
    <AuthPage title="Protect your account">
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">Every account needs a second step when signing in. Pick one:</p>
      {passkeysSupported() && (
        <Button className="mb-4 w-full" isDisabled={busy} onPress={() => void addPasskey()}>
          Use Face ID, fingerprint or device PIN (passkey)
        </Button>
      )}
      {!enrollment ? (
        <Button variant="secondary" className="w-full" isDisabled={busy} onPress={() => void run(async () => setEnrollment(await api('POST', '/api/v1/auth/mfa/totp/enroll')))}>
          Use an authenticator app
        </Button>
      ) : (
        <Form
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () => {
              const r = await api<{ recovery_codes: string[] }>('POST', '/api/v1/auth/mfa/totp/confirm', { code })
              setCodes(r.recovery_codes)
            })
          }}
        >
          <p className="text-sm">
            On this phone, <a className="font-medium text-brand-700 underline" href={enrollment.otpauth_uri}>open your authenticator app</a>. On another device, add this key manually:
          </p>
          <p className="break-all rounded-lg bg-stone-100 p-2 font-mono text-sm dark:bg-stone-800">{enrollment.secret}</p>
          <Field label="Enter the 6-digit code it shows" isRequired inputMode="numeric" autoComplete="one-time-code" value={code} onChange={setCode} />
          <Button type="submit" isDisabled={busy} className="w-full">Confirm</Button>
        </Form>
      )}
      <div className="mt-4"><ErrorText error={error} /></div>
      <div className="mt-2"><SignOutButton /></div>
    </AuthPage>
  )
}

export function InviteScreen() {
  const refresh = useRefreshSession()
  const { error, busy, run } = useSubmit()
  const token = typeof window === 'undefined' ? '' : window.location.hash.slice(1)
  const check = useQuery({
    queryKey: ['invite', token],
    queryFn: () => api<{ valid: boolean; email: string | null }>('POST', '/api/v1/invites/check', { token }),
    enabled: !!token,
  })
  const [f, setF] = useState({ email: '', display_name: '', password: '' })
  if (!token || check.data?.valid === false) {
    return <AuthPage title="Invite not valid"><p>This invite link is invalid, used or expired. Ask for a new one.</p></AuthPage>
  }
  const email = check.data?.email ?? f.email
  return (
    <AuthPage title="Join Planhaven">
      <Form
        onSubmit={(e) => {
          e.preventDefault()
          void run(async () => {
            const session = await api<Session>('POST', '/api/v1/invites/accept', { token, ...f, email })
            window.history.replaceState(null, '', '/')
            await refresh(session)
          })
        }}
      >
        <Field label="Your name" isRequired value={f.display_name} onChange={(v) => setF({ ...f, display_name: v })} autoComplete="name" />
        <Field label="Email" type="email" isRequired value={email} onChange={(v) => setF({ ...f, email: v })} autoComplete="email" />
        <Field label="Choose a password" type="password" isRequired minLength={12} value={f.password} onChange={(v) => setF({ ...f, password: v })} autoComplete="new-password" description="At least 12 characters." />
        <ErrorText error={error} />
        <Button type="submit" isDisabled={busy || check.isLoading} className="w-full">Create my account</Button>
      </Form>
    </AuthPage>
  )
}

/** Sign out: end the session on the server and remove this device's offline copies. */
function useSignOut(): () => void {
  const refresh = useRefreshSession()
  return () =>
    void api('POST', '/api/v1/auth/logout').finally(async () => {
      await wipeOfflineData()
      navigate('/')
      void refresh()
    })
}

export function SignOutButton({ className = 'w-full' }: { className?: string }) {
  const signOut = useSignOut()
  return <Button variant="ghost" className={className} onPress={signOut}>Sign out</Button>
}
