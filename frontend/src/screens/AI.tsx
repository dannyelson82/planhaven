// AI apps (ADR 0019): the sign-in approval page an AI app sends you to, your connected apps
// (Account), and the AI page: changes waiting for your approval, and recent AI changes to undo.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { useStepUp } from '../stepupContext.ts'
import { AuthPage, Button, Card, ErrorText, Link } from '../ui.tsx'

type Access = 'read' | 'approve' | 'apply'
type Consent = { client_name: string; redirect_host: string; scope: 'read' | 'write' }
type Connection = { id: string; client_name: string; scope: 'read' | 'write'; write_mode: 'approve' | 'apply'; created_at: string; last_used_at: string | null }
type Suggestion = { id: string; client_name: string; project_id: string | null; tool: string; summary: string; created_at: string }
type Change = { id: string; client_name: string; project_id: string | null; kind: string; summary: string; created_at: string; undone_at: string | null }

const ACCESS: Record<Access, { label: string; help: string }> = {
  read: { label: 'Read only', help: 'It can read and search your projects. It can\'t change anything.' },
  approve: { label: 'Suggest changes', help: 'It can also suggest changes. Nothing happens until you approve each one on the AI page.' },
  apply: { label: 'Make changes', help: 'It can add and change things straight away. You can undo each change on the AI page. Nothing can be deleted.' },
}
const accessOf = (c: { scope: string; write_mode: string }): Access => (c.scope === 'read' ? 'read' : c.write_mode === 'apply' ? 'apply' : 'approve')
const body = (a: Access) => ({ scope: a === 'read' ? 'read' : 'write', write_mode: a === 'apply' ? 'apply' : 'approve' })
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'never')

function AccessChoice({ value, onChange, allowWrite, name }: { value: Access; onChange: (a: Access) => void; allowWrite: boolean; name: string }) {
  const options = (allowWrite ? ['read', 'approve', 'apply'] : ['read']) as Access[]
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">What it may do</legend>
      {options.map((a) => (
        <label key={a} className="flex min-h-11 items-start gap-3 rounded-xl border border-stone-200 p-3 dark:border-stone-700">
          <input type="radio" name={name} className="mt-1 size-5 accent-brand-600" checked={value === a} onChange={() => onChange(a)} />
          <span>
            <span className="block font-medium">{ACCESS[a].label}</span>
            <span className="block text-sm text-stone-600 dark:text-stone-400">{ACCESS[a].help}</span>
          </span>
        </label>
      ))}
    </fieldset>
  )
}

/** /connect?request=…: an AI app asks to connect. Approving needs a fresh second factor. */
export function ConnectScreen() {
  const params = new URLSearchParams(window.location.search)
  const requestId = params.get('request') ?? ''
  const stepUp = useStepUp()
  const consent = useQuery({
    queryKey: ['oauth-request', requestId],
    queryFn: () => api<Consent>('GET', `/api/v1/oauth/requests/${requestId}`),
    enabled: /^[0-9a-f-]{36}$/i.test(requestId),
    retry: false,
  })
  const [access, setAccess] = useState<Access>('approve')
  const go = (to: { redirect: string }) => window.location.assign(to.redirect)
  const approve = useMutation({
    mutationFn: (a: Access) => stepUp(() => api<{ redirect: string }>('POST', `/api/v1/oauth/requests/${requestId}/approve`, body(a))),
    onSuccess: go,
  })
  const deny = useMutation({
    mutationFn: () => api<{ redirect: string }>('POST', `/api/v1/oauth/requests/${requestId}/deny`),
    onSuccess: go,
  })
  if (params.get('problem') || consent.isError || !requestId)
    return (
      <AuthPage title="Can't connect">
        <p>This connection request isn't valid or has expired (they last 15 minutes). Start again from the AI app.</p>
        <p className="mt-4"><Link to="/projects" className="text-brand-700 underline dark:text-brand-100">Go to projects</Link></p>
      </AuthPage>
    )
  if (!consent.data) return <AuthPage title="Connect an AI app"><p className="text-stone-500">Loading…</p></AuthPage>
  const c = consent.data
  const chosen = c.scope === 'read' ? 'read' : access
  const busy = approve.isPending || deny.isPending || approve.isSuccess || deny.isSuccess
  return (
    <AuthPage title="Connect an AI app">
      <div className="space-y-4">
        <p><strong>{c.client_name}</strong> wants to use your PlanHaven projects. After you choose, you go back to <strong>{c.redirect_host}</strong>.</p>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          It sees every project you can see, except ones marked "Local AI only". Only connect apps you trust.
        </p>
        <AccessChoice value={chosen} onChange={setAccess} allowWrite={c.scope === 'write'} name="connect-access" />
        <ErrorText error={approve.error ?? deny.error} />
        <div className="flex flex-wrap gap-2">
          <Button onPress={() => approve.mutate(chosen)} isDisabled={busy}>Allow</Button>
          <Button variant="ghost" onPress={() => deny.mutate()} isDisabled={busy}>Don't allow</Button>
        </div>
        <p className="text-sm text-stone-500">You can change this or disconnect any time in Account, Connected AI apps.</p>
      </div>
    </AuthPage>
  )
}

function ConnectionRow({ c }: { c: Connection }) {
  const client = useQueryClient()
  const stepUp = useStepUp()
  const refresh = () => client.invalidateQueries({ queryKey: ['ai-connections'] })
  const saved = accessOf(c)
  const [choice, setChoice] = useState<{ saved: Access; on: Access } | null>(null)
  const value = choice && choice.saved === saved ? choice.on : saved
  const change = useMutation({
    mutationFn: (a: Access) => stepUp(() => api('PATCH', `/api/v1/ai/connections/${c.id}`, body(a))),
    onSettled: refresh,
  })
  const remove = useMutation({ mutationFn: () => api('DELETE', `/api/v1/ai/connections/${c.id}`), onSettled: refresh })
  return (
    <li className="space-y-3 rounded-xl border border-stone-200 p-3 dark:border-stone-700">
      <div>
        <p className="font-medium">{c.client_name}</p>
        <p className="text-sm text-stone-500">Connected {when(c.created_at)} · last used {when(c.last_used_at)}</p>
      </div>
      <AccessChoice value={value} name={`access-${c.id}`} allowWrite
        onChange={(a) => { setChoice({ saved, on: a }); change.mutate(a) }} />
      <ErrorText error={change.error ?? remove.error} />
      <Button variant="danger-ghost" onPress={() => remove.mutate()} isDisabled={remove.isPending}>Disconnect</Button>
    </li>
  )
}

/** Account: the AI apps connected to this account. */
export function ConnectedAppsCard() {
  const apps = useQuery({ queryKey: ['ai-connections'], queryFn: () => api<Connection[]>('GET', '/api/v1/ai/connections') })
  return (
    <section aria-label="Connected AI apps">
      <Card className="space-y-3">
        <h2 className="font-semibold">Connected AI apps</h2>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          AI apps like Claude can read your projects and help plan them. Connect one from the app itself.
        </p>
        {apps.data?.length === 0 && <p className="text-sm text-stone-500">None yet.</p>}
        {apps.data && apps.data.length > 0 && <ul className="space-y-3">{apps.data.map((c) => <ConnectionRow key={c.id} c={c} />)}</ul>}
        <p className="text-sm">
          <Link to="/ai" className="text-brand-700 underline dark:text-brand-100">AI suggestions and changes</Link>
          {' · '}
          <Link to="/help/ai-apps" className="text-brand-700 underline dark:text-brand-100">How to connect Claude</Link>
        </p>
      </Card>
    </section>
  )
}

/** /ai: suggestions waiting for approval, and recent AI changes with Undo. */
export function AiScreen() {
  const client = useQueryClient()
  const suggestions = useQuery({ queryKey: ['ai-suggestions'], queryFn: () => api<Suggestion[]>('GET', '/api/v1/ai/suggestions') })
  const changes = useQuery({ queryKey: ['ai-changes'], queryFn: () => api<Change[]>('GET', '/api/v1/ai/changes') })
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ['ai-suggestions'] })
    await client.invalidateQueries({ queryKey: ['ai-changes'] })
    await client.invalidateQueries({ queryKey: ['projects'] })
  }
  const [note, setNote] = useState('')
  const decide = useMutation({
    mutationFn: ({ id, ok }: { id: string; ok: boolean }) => api<{ status: string }>('POST', `/api/v1/ai/suggestions/${id}/${ok ? 'approve' : 'decline'}`),
    onSuccess: (r) => setNote(r.status === 'failed' ? 'That change couldn\'t be made any more (something changed since). It was set aside.' : ''),
    onSettled: refresh,
  })
  const all = useMutation({
    mutationFn: () => api<{ approved: number; failed: number }>('POST', '/api/v1/ai/suggestions/approve-all'),
    onSuccess: (r) => setNote(r.failed ? `${r.approved} made; ${r.failed} couldn't be made any more.` : ''),
    onSettled: refresh,
  })
  const undo = useMutation({ mutationFn: (id: string) => api('POST', `/api/v1/ai/changes/${id}/undo`), onSettled: refresh })
  const pending = suggestions.data ?? []
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">AI</h1>
      <section aria-label="Waiting for approval">
        <Card className="space-y-3">
          <h2 className="font-semibold">Waiting for your approval</h2>
          {pending.length === 0 && <p className="text-sm text-stone-500">Nothing waiting.</p>}
          <ul className="space-y-2">
            {pending.map((s) => (
              <li key={s.id} className="space-y-2 rounded-xl border border-stone-200 p-3 dark:border-stone-700">
                <p>{s.summary}</p>
                <p className="text-sm text-stone-500">
                  From {s.client_name} · {when(s.created_at)}
                  {s.project_id && <> · <Link to={`/projects/${s.project_id}`} className="underline">Open project</Link></>}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button onPress={() => decide.mutate({ id: s.id, ok: true })} isDisabled={decide.isPending}>Approve</Button>
                  <Button variant="ghost" onPress={() => decide.mutate({ id: s.id, ok: false })} isDisabled={decide.isPending}>Decline</Button>
                </div>
              </li>
            ))}
          </ul>
          {pending.length > 1 && <Button variant="secondary" onPress={() => all.mutate()} isDisabled={all.isPending}>Approve all</Button>}
          {note && <p role="status" className="text-sm">{note}</p>}
          <ErrorText error={decide.error ?? all.error} />
        </Card>
      </section>
      <section aria-label="Recent AI changes">
        <Card className="space-y-3">
          <h2 className="font-semibold">Recent AI changes</h2>
          {changes.data?.length === 0 && <p className="text-sm text-stone-500">None yet.</p>}
          <ul className="space-y-2">
            {(changes.data ?? []).map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-stone-200 p-3 dark:border-stone-700">
                <div className="min-w-0">
                  <p className={c.undone_at ? 'text-stone-500 line-through' : ''}>{c.summary}</p>
                  <p className="text-sm text-stone-500">
                    {c.client_name} · {when(c.created_at)}
                    {c.project_id && <> · <Link to={`/projects/${c.project_id}`} className="underline">Open project</Link></>}
                  </p>
                </div>
                {c.undone_at ? <span className="text-sm text-stone-500">Undone</span> : (
                  <Button variant="secondary" onPress={() => undo.mutate(c.id)} isDisabled={undo.isPending}>Undo</Button>
                )}
              </li>
            ))}
          </ul>
          <ErrorText error={undo.error} />
        </Card>
      </section>
      <p className="text-sm"><Link to="/account" className="text-brand-700 underline dark:text-brand-100">Connected AI apps</Link> · <Link to="/help/ai-apps" className="text-brand-700 underline dark:text-brand-100">Help</Link></p>
    </div>
  )
}
