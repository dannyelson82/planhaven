// Experimental features (ADR 0012): the admin's switch and each feature's availability, and
// each person's opt-in. Nobody gets an experiment they didn't choose.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { useStepUp } from '../stepupContext.ts'
import { Card, ErrorText } from '../ui.tsx'

type AdminFeature = { name: string; title: string; description: string; risks: string; available: boolean }
type AdminState = { enabled: boolean; features: AdminFeature[] }
type MyFeature = { name: string; title: string; description: string; risks: string; opted_in: boolean }
type MyState = { enabled: boolean; features: MyFeature[] }

const badge = <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">Experimental</span>
const toggle = 'mt-1 size-5 shrink-0 accent-brand-600'

/** Admin → Experimental features. */
export function AdminExperiments() {
  const client = useQueryClient()
  const stepUp = useStepUp()
  const state = useQuery({ queryKey: ['admin', 'experiments'], queryFn: () => stepUp(() => api<AdminState>('GET', '/api/v1/admin/experiments')) })
  const save = useMutation({
    mutationFn: (next: { enabled: boolean; available?: Record<string, boolean> }) =>
      stepUp(() => api<AdminState>('PUT', '/api/v1/admin/experiments', next)),
    // Shown at once; the server's answer replaces it (or a refetch undoes it on error).
    onMutate: (next) => client.setQueryData<AdminState>(['admin', 'experiments'], (d) => d && {
      enabled: next.enabled,
      features: d.features.map((f) => (next.available && f.name in next.available ? { ...f, available: next.available[f.name] } : f)),
    }),
    onSuccess: (data) => { client.setQueryData(['admin', 'experiments'], data); void client.invalidateQueries({ queryKey: ['experiments'] }) },
    onError: () => client.invalidateQueries({ queryKey: ['admin', 'experiments'] }),
  })
  // What was just tapped shows at once (a checkbox must change in the same tap).
  const [shown, setShown] = useState<Record<string, boolean>>({})
  const s = state.data
  const on = (name: string, saved: boolean) => shown[name] ?? saved
  const set = (next: Record<string, boolean>, body: { enabled: boolean; available?: Record<string, boolean> }) => {
    setShown((x) => ({ ...x, ...next }))
    save.mutate(body, { onSettled: () => setShown((x) => Object.fromEntries(Object.entries(x).filter(([k]) => !(k in next)))) })
  }
  return (
    <section aria-label="Experimental features" className="space-y-2">
      <h2 className="text-lg font-semibold">Experimental features</h2>
      <Card className="space-y-3">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Features still in development. They're off until you turn them on here and make each one available; then each
          person chooses for themselves in Account. Turning this off stops them all.
        </p>
        {s && (
          <label className="flex min-h-11 items-start gap-3">
            <input type="checkbox" className={toggle} checked={on('*', s.enabled)}
              onChange={(e) => set({ '*': e.target.checked }, { enabled: e.target.checked })} />
            <span className="font-medium">Enable experimental features</span>
          </label>
        )}
        {s && s.features.length === 0 && <p className="text-sm text-stone-500">No experimental features are in development right now. New ones will appear here, off until you make them available.</p>}
        {s && s.features.map((f) => (
          <label key={f.name} className={`flex min-h-11 items-start gap-3 ${s.enabled ? '' : 'opacity-50'}`}>
            <input type="checkbox" className={toggle} checked={on(f.name, f.available)} disabled={!s.enabled}
              onChange={(e) => set({ [f.name]: e.target.checked }, { enabled: s.enabled, available: { [f.name]: e.target.checked } })} />
            <span>
              <span className="font-medium">{f.title}</span>{badge}
              <span className="block text-sm text-stone-600 dark:text-stone-400">{f.description}</span>
              <span className="block text-sm text-amber-800 dark:text-amber-300">Known risks: {f.risks}</span>
            </span>
          </label>
        ))}
        <ErrorText error={state.error ?? save.error} />
      </Card>
    </section>
  )
}

/** Account → Experimental features (only when the admin made some available). */
export function MyExperiments() {
  const client = useQueryClient()
  const state = useQuery({ queryKey: ['experiments'], queryFn: () => api<MyState>('GET', '/api/v1/experiments') })
  const choose = useMutation({
    mutationFn: ({ name, on }: { name: string; on: boolean }) => api('PUT', `/api/v1/experiments/${name}`, { opted_in: on }),
    onMutate: ({ name, on }) => client.setQueryData<MyState>(['experiments'], (d) => d && { ...d, features: d.features.map((f) => (f.name === name ? { ...f, opted_in: on } : f)) }),
    onSettled: () => client.invalidateQueries({ queryKey: ['experiments'] }),
  })
  const [shown, setShown] = useState<Record<string, boolean>>({})
  if (!state.data?.enabled || state.data.features.length === 0) return null
  return (
    <section aria-label="Experimental features" className="space-y-2">
      <h2 className="text-lg font-semibold">Experimental features</h2>
      <Card className="space-y-3">
        <p className="text-sm text-stone-600 dark:text-stone-400">Try features still in development. Only for you; turn them off any time.</p>
        {state.data.features.map((f) => (
          <label key={f.name} className="flex min-h-11 items-start gap-3">
            <input type="checkbox" className={toggle} checked={shown[f.name] ?? f.opted_in}
              onChange={(e) => {
                const next = e.target.checked
                setShown((x) => ({ ...x, [f.name]: next }))
                choose.mutate({ name: f.name, on: next }, { onSettled: () => setShown((x) => Object.fromEntries(Object.entries(x).filter(([k]) => k !== f.name))) })
              }} />
            <span>
              <span className="font-medium">{f.title}</span>{badge}
              <span className="block text-sm text-stone-600 dark:text-stone-400">{f.description}</span>
              <span className="block text-sm text-amber-800 dark:text-amber-300">Known risks: {f.risks}</span>
            </span>
          </label>
        ))}
        <ErrorText error={choose.error} />
      </Card>
    </section>
  )
}
