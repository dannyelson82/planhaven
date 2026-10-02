// The calendar feed and iPhone Reminders sync (A§13.1, A§13.2): links and keys are made here
// (after a fresh second factor), shown once, and can be turned off any time.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api.ts'
import { navigate } from '../router.ts'
import { useStepUp } from '../stepupContext.ts'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'

type Key = { id: string; kind: 'ics' | 'sync'; label: string; details: boolean; created_at: string; last_used_at: string | null }
type NewKey = Key & { key: string; url: string | null }
type SyncList = { list_id: string; title: string; reminders_name: string }

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'never')

function Secret({ label, value, onDone }: { label: string; value: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="space-y-2 rounded-xl bg-brand-50 p-3 dark:bg-stone-800">
      <p className="text-sm font-medium">{label}</p>
      <input readOnly value={value} aria-label={label} onFocus={(e) => e.currentTarget.select()}
        className="block w-full min-w-0 rounded-lg border border-stone-300 bg-white px-2 py-2 font-mono text-xs dark:border-stone-700 dark:bg-stone-900" />
      <p className="text-xs text-stone-500">Shown only now. Anyone with it can read what it gives, so keep it to yourself; turn it off below if it leaks.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onPress={() => void navigator.clipboard.writeText(value).then(() => setCopied(true))}>{copied ? 'Copied' : 'Copy'}</Button>
        <Button variant="ghost" onPress={onDone}>Done</Button>
      </div>
    </div>
  )
}

export function FeedsCard() {
  const client = useQueryClient()
  const stepUp = useStepUp()
  const keys = useQuery({ queryKey: ['keys'], queryFn: () => api<Key[]>('GET', '/api/v1/keys') })
  const synced = useQuery({ queryKey: ['sync-lists'], queryFn: () => api<SyncList[]>('GET', '/api/v1/sync/lists') })
  const refresh = () => client.invalidateQueries({ queryKey: ['keys'] })
  const [shown, setShown] = useState<NewKey | null>(null)
  const [label, setLabel] = useState('')
  const make = useMutation({
    mutationFn: (body: { kind: 'ics' | 'sync'; label: string }) => stepUp(() => api<NewKey>('POST', '/api/v1/keys', body)),
    onSuccess: async (k) => { setShown(k); setLabel(''); await refresh() },
  })
  const revoke = useMutation({ mutationFn: (id: string) => api('DELETE', `/api/v1/keys/${id}`), onSettled: refresh })
  const details = useMutation({ mutationFn: (d: boolean) => api('PUT', '/api/v1/keys/feed-details', { details: d }), onSettled: refresh })
  const feed = keys.data?.find((k) => k.kind === 'ics')
  const syncKeys = (keys.data ?? []).filter((k) => k.kind === 'sync')
  const [detailsBox, setDetailsBox] = useState<{ saved: boolean; on: boolean } | null>(null)
  const detailsOn = feed && detailsBox && detailsBox.saved === feed.details ? detailsBox.on : Boolean(feed?.details)
  return (
    <section aria-label="Calendar and Reminders">
      <Card className="space-y-4">
        <h2 className="font-semibold">Calendar and iPhone Reminders</h2>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">Calendar</h3>
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Your tasks with due dates, your chores and asset services coming due, in your phone's calendar. Read-only.
          </p>
          {shown?.kind === 'ics' && shown.url && <Secret label="Calendar link" value={shown.url} onDone={() => setShown(null)} />}
          {feed ? (
            <>
              <p className="text-sm">Link made {when(feed.created_at)} · last read {when(feed.last_used_at)}</p>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input type="checkbox" className="size-5 accent-brand-600" checked={detailsOn}
                  onChange={(e) => { setDetailsBox({ saved: feed.details, on: e.target.checked }); details.mutate(e.target.checked) }} />
                Include notes (titles only otherwise)
              </label>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onPress={() => make.mutate({ kind: 'ics', label: 'Calendar' })} isDisabled={make.isPending}>Make a new link</Button>
                <Button variant="danger-ghost" onPress={() => revoke.mutate(feed.id)}>Turn off</Button>
              </div>
            </>
          ) : (
            <Button onPress={() => make.mutate({ kind: 'ics', label: 'Calendar' })} isDisabled={make.isPending}>Make my calendar link</Button>
          )}
          <p className="text-sm"><Link to="/help/calendar-and-reminders" className="text-brand-700 underline dark:text-brand-100">How to add it to your phone</Link></p>
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">iPhone Reminders</h3>
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Lists you choose (in a list's Edit) appear in Reminders on your iPhone, through a Shortcut; ticking one there ticks it here.
          </p>
          {(synced.data ?? []).length > 0 ? (
            <ul aria-label="Lists sent to Reminders" className="text-sm">
              {(synced.data ?? []).map((l) => <li key={l.list_id}><Link to={`/lists/${l.list_id}`} className="underline">{l.title}</Link> → {l.reminders_name}</li>)}
            </ul>
          ) : <p className="text-sm text-stone-500">No lists chosen yet.</p>}
          {shown?.kind === 'sync' && <Secret label="Sync key" value={shown.key} onDone={() => setShown(null)} />}
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); make.mutate({ kind: 'sync', label: label.trim() || 'iPhone' }) }}>
            <div className="min-w-0 flex-1"><Field label="Name of this key" maxLength={80} value={label} onChange={setLabel} description="For example: My iPhone" /></div>
            <Button type="submit" variant="secondary" isDisabled={make.isPending}>Make a sync key</Button>
          </form>
          {syncKeys.length > 0 && (
            <ul aria-label="Sync keys" className="space-y-1 text-sm">
              {syncKeys.map((k) => (
                <li key={k.id} className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate">{k.label || 'Sync key'} · last used {when(k.last_used_at)}</span>
                  <Button variant="ghost" aria-label={`Remove ${k.label || 'sync key'}`} onPress={() => revoke.mutate(k.id)}>✕</Button>
                </li>
              ))}
            </ul>
          )}
          <p className="text-sm"><Link to="/help/calendar-and-reminders#iphone-reminders" className="text-brand-700 underline dark:text-brand-100">How to set up the Shortcut</Link></p>
        </div>
        <ErrorText error={keys.error ?? make.error ?? revoke.error ?? details.error} />
      </Card>
    </section>
  )
}

/** In a list's Edit: send it to a Reminders list on your iPhone. */
export function SendToReminders({ listId, title }: { listId: string; title: string }) {
  const client = useQueryClient()
  const synced = useQuery({ queryKey: ['sync-lists'], queryFn: () => api<SyncList[]>('GET', '/api/v1/sync/lists') })
  const current = synced.data?.find((l) => l.list_id === listId)
  const [name, setName] = useState<string | null>(null)
  const shown = name ?? current?.reminders_name ?? title.slice(0, 60)
  const save = useMutation({
    mutationFn: (reminders: string | null) => api('PUT', `/api/v1/lists/${listId}/sync`, { reminders_name: reminders }),
    onSuccess: async () => { setName(null); await client.invalidateQueries({ queryKey: ['sync-lists'] }) },
  })
  return (
    <section aria-label="iPhone Reminders" className="space-y-2">
      <h2 className="font-semibold">iPhone Reminders</h2>
      <p className="text-sm text-stone-500">{current ? `Sent to the Reminders list “${current.reminders_name}”.` : 'Not sent to Reminders.'}</p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1"><Field label="Reminders list" maxLength={60} value={shown} onChange={setName} /></div>
        <Button variant="secondary" onPress={() => save.mutate(shown.trim())} isDisabled={!shown.trim() || save.isPending}>{current ? 'Save' : 'Send to Reminders'}</Button>
        {current && <Button variant="ghost" onPress={() => save.mutate(null)} isDisabled={save.isPending}>Stop</Button>}
      </div>
      <ErrorText error={save.error} />
    </section>
  )
}

/** /i/<item>: a link from a reminder opens the item's list. */
export function ItemLinkScreen({ id }: { id: string }) {
  const found = useQuery({ queryKey: ['item-list', id], queryFn: () => api<{ list_id: string }>('GET', `/api/v1/list-items/${id}/list`) })
  const listId = found.data?.list_id
  useEffect(() => { if (listId) navigate(`/lists/${listId}`, { force: true }) }, [listId])
  return found.error ? <ErrorText error={found.error} /> : <p className="text-stone-500">Opening…</p>
}
