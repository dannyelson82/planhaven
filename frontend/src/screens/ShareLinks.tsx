// Share links for people without an account (ADR 0015): make one by ticking exactly what it
// allows, see when it was used and by whom, turn it off. Project owners and editors.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Task } from '../api.ts'
import { cachedGet } from '../offline.ts'
import { useStepUp } from '../stepupContext.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'

type ShareLink = {
  id: string; name: string; has_pin: boolean; tasks_view: 'none' | 'all' | 'chosen'; task_ids: string[]; tasks_tick: boolean
  note_ids: string[]; append_note_id: string | null; list_ids: string[]; lists_tick: boolean; files_view: boolean; files_add: boolean
  created_at: string; expires_at: string; revoked: boolean; last_used_at: string | null
}
type NewLink = ShareLink & { url: string; pin: string | null }
type Named = { id: string; title: string }
type LinkEvent = { at: string; guest_name: string; action: string; detail: string }

const ACTION: Record<string, string> = {
  opened: 'opened the link', 'task.done': 'ticked off', 'task.undone': 'unticked', 'item.checked': 'ticked off',
  'item.unchecked': 'unticked', 'note.added': 'added to the note', 'photo.added': 'added a photo',
}
const day = (iso: string) => new Date(iso).toLocaleDateString()
const box = 'mt-1 size-5 shrink-0 accent-brand-600'

function summary(l: ShareLink): string {
  const parts = [
    l.tasks_view === 'all' ? 'all tasks' : l.tasks_view === 'chosen' ? `${l.task_ids.length} task${l.task_ids.length === 1 ? '' : 's'}` : '',
    l.tasks_tick ? 'can tick them off' : '',
    l.note_ids.length ? `${l.note_ids.length} note${l.note_ids.length === 1 ? '' : 's'} to read` : '',
    l.append_note_id ? 'can add to a note' : '',
    l.list_ids.length ? `${l.list_ids.length} list${l.list_ids.length === 1 ? '' : 's'}${l.lists_tick ? ' (can tick items)' : ''}` : '',
    l.files_view ? 'photos and files' : '',
    l.files_add ? 'can add photos' : '',
  ]
  return parts.filter(Boolean).join(' · ')
}

export function ShareLinksScreen({ projectId }: { projectId: string }) {
  const links = useQuery({ queryKey: ['share-links', projectId], queryFn: () => api<ShareLink[]>('GET', `/api/v1/projects/${projectId}/share-links`) })
  const [made, setMade] = useState<NewLink | null>(null)
  return (
    <div className="space-y-4">
      <Link to={`/projects/${projectId}`} className="text-sm text-brand-700 dark:text-brand-100">← Back to project</Link>
      <h1 className="text-2xl font-bold">Share links</h1>
      <p className="text-stone-600 dark:text-stone-400">
        A link lets someone without an account (a mechanic, a contractor) see and do exactly what you tick, until it
        expires or you turn it off. Anyone who has the link can use it, so send it only to them.
      </p>
      {made ? <Made link={made} onDone={() => setMade(null)} /> : <NewLinkForm projectId={projectId} onMade={setMade} />}
      <section aria-label="Links" className="space-y-2">
        <h2 className="text-lg font-semibold">Links</h2>
        {links.data?.length === 0 && <p className="text-sm text-stone-500">No links yet.</p>}
        {(links.data ?? []).map((l) => <LinkCard key={l.id} link={l} projectId={projectId} />)}
        <ErrorText error={links.error} />
      </section>
    </div>
  )
}

function Made({ link, onDone }: { link: NewLink; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <Card className="space-y-3 ring-2 ring-brand-600">
      <h2 className="text-lg font-semibold">Link ready: “{link.name}”</h2>
      <p className="text-sm">Copy it now: it's shown only once.{link.pin && ' Send the PIN separately (a text message, say).'}</p>
      <input readOnly aria-label="Share link" value={link.url} onFocus={(e) => e.currentTarget.select()}
        className="min-h-11 w-full rounded-xl border border-stone-300 bg-white px-3 font-mono text-sm dark:border-stone-700 dark:bg-stone-900" />
      {link.pin && <p>PIN: <span className="font-mono text-lg font-semibold tracking-widest" aria-label="PIN">{link.pin}</span></p>}
      <div className="flex flex-wrap gap-2">
        <Button onPress={() => void navigator.clipboard.writeText(link.url).then(() => setCopied(true))}>{copied ? 'Copied' : 'Copy link'}</Button>
        {'share' in navigator && <Button variant="secondary" onPress={() => void navigator.share({ title: link.name, url: link.url }).catch(() => undefined)}>Share…</Button>}
        <Button variant="ghost" onPress={onDone}>Done</Button>
      </div>
    </Card>
  )
}

function NewLinkForm({ projectId, onMade }: { projectId: string; onMade: (l: NewLink) => void }) {
  const client = useQueryClient()
  const stepUp = useStepUp()
  const tasks = useQuery({ queryKey: ['tasks', projectId], queryFn: () => cachedGet<Task[]>(`/api/v1/projects/${projectId}/tasks`) })
  const notes = useQuery({ queryKey: ['notes', projectId], queryFn: () => api<Named[]>('GET', `/api/v1/projects/${projectId}/notes`) })
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => cachedGet<Named[]>(`/api/v1/projects/${projectId}/lists`) })
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [days, setDays] = useState('30')
  const [pin, setPin] = useState(false)
  const [tasksView, setTasksView] = useState<'none' | 'all' | 'chosen'>('chosen')
  const [taskIds, setTaskIds] = useState<string[]>([])
  const [tasksTick, setTasksTick] = useState(true)
  const [noteIds, setNoteIds] = useState<string[]>([])
  const [appendNote, setAppendNote] = useState('')
  const [listIds, setListIds] = useState<string[]>([])
  const [listsTick, setListsTick] = useState(false)
  const [filesView, setFilesView] = useState(false)
  const [filesAdd, setFilesAdd] = useState(false)
  const create = useMutation({
    mutationFn: () => stepUp(() => api<NewLink>('POST', `/api/v1/projects/${projectId}/share-links`, {
      name: name.trim(), days: Number(days), pin, tasks_view: tasksView, task_ids: tasksView === 'chosen' ? taskIds : [],
      tasks_tick: tasksView !== 'none' && tasksTick, note_ids: noteIds, append_note_id: appendNote || null,
      list_ids: listIds, lists_tick: listIds.length > 0 && listsTick, files_view: filesView, files_add: filesAdd,
    })),
    onSuccess: async (link) => { await client.invalidateQueries({ queryKey: ['share-links', projectId] }); setOpen(false); onMade(link) },
  })
  const toggle = (ids: string[], set: (x: string[]) => void, id: string, on: boolean) => set(on ? [...ids, id] : ids.filter((x) => x !== id))
  const openTasks = (tasks.data ?? []).filter((t) => !t.done)
  if (!open) return <Button onPress={() => setOpen(true)}>Make a share link</Button>
  return (
    <Card>
      <Form onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate() }}>
        <h2 className="text-lg font-semibold">New share link</h2>
        <Field label="Name of the link" isRequired maxLength={100} value={name} onChange={setName} description="For you, like “Dave's Garage, spring service”; the guest sees it too" />
        <div className="flex flex-wrap items-end gap-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Works for</span>
            <select value={days} onChange={(e) => setDays(e.target.value)} aria-label="Works for" className="block min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900">
              {[['1', '1 day'], ['7', '1 week'], ['30', '30 days'], ['90', '3 months'], ['365', '1 year']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="flex min-h-11 items-start gap-3"><input type="checkbox" className={box} checked={pin} onChange={(e) => setPin(e.target.checked)} /><span>Also ask for a PIN (you send it separately)</span></label>
        </div>

        <fieldset className="space-y-2">
          <legend className="font-semibold">Tasks</legend>
          <select value={tasksView} onChange={(e) => setTasksView(e.target.value as 'none' | 'all' | 'chosen')} aria-label="Tasks shown"
            className="block min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900">
            <option value="none">Don't show tasks</option>
            <option value="chosen">Show these tasks and their instructions</option>
            <option value="all">Show all tasks and their instructions</option>
          </select>
          {tasksView === 'chosen' && openTasks.map((t) => (
            <label key={t.id} className="flex min-h-11 items-start gap-3 pl-2"><input type="checkbox" className={box} checked={taskIds.includes(t.id)} onChange={(e) => toggle(taskIds, setTaskIds, t.id, e.target.checked)} /><span>{t.title}</span></label>
          ))}
          {tasksView !== 'none' && <label className="flex min-h-11 items-start gap-3"><input type="checkbox" className={box} checked={tasksTick} onChange={(e) => setTasksTick(e.target.checked)} /><span>Can tick tasks off</span></label>}
        </fieldset>

        {(notes.data ?? []).length > 0 && (
          <fieldset className="space-y-2">
            <legend className="font-semibold">Notes</legend>
            <p className="text-sm text-stone-600 dark:text-stone-400">Notes they can read:</p>
            {(notes.data ?? []).map((n) => (
              <label key={n.id} className="flex min-h-11 items-start gap-3 pl-2"><input type="checkbox" className={box} checked={noteIds.includes(n.id)} onChange={(e) => toggle(noteIds, setNoteIds, n.id, e.target.checked)} /><span>{n.title}</span></label>
            ))}
            <label className="block space-y-1">
              <span className="text-sm">A note they can add to (they can't change or delete what's there):</span>
              <select value={appendNote} onChange={(e) => setAppendNote(e.target.value)} aria-label="Note they can add to"
                className="block min-h-11 w-full rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900">
                <option value="">None</option>
                {(notes.data ?? []).map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}
              </select>
            </label>
          </fieldset>
        )}

        {(lists.data ?? []).length > 0 && (
          <fieldset className="space-y-2">
            <legend className="font-semibold">Lists</legend>
            {(lists.data ?? []).map((l) => (
              <label key={l.id} className="flex min-h-11 items-start gap-3 pl-2"><input type="checkbox" className={box} checked={listIds.includes(l.id)} onChange={(e) => toggle(listIds, setListIds, l.id, e.target.checked)} /><span>{l.title}</span></label>
            ))}
            {listIds.length > 0 && <label className="flex min-h-11 items-start gap-3"><input type="checkbox" className={box} checked={listsTick} onChange={(e) => setListsTick(e.target.checked)} /><span>Can tick items off</span></label>}
          </fieldset>
        )}

        <fieldset className="space-y-2">
          <legend className="font-semibold">Photos and files</legend>
          <label className="flex min-h-11 items-start gap-3"><input type="checkbox" className={box} checked={filesView} onChange={(e) => setFilesView(e.target.checked)} /><span>See the project's photos and files</span></label>
          <label className="flex min-h-11 items-start gap-3"><input type="checkbox" className={box} checked={filesAdd} onChange={(e) => setFilesAdd(e.target.checked)} /><span>Add photos (location removed)</span></label>
        </fieldset>
        <p className="text-sm text-stone-600 dark:text-stone-400">Never through a link: deleting anything, sharing, other people's names or emails, contacts, quotes and costs, other projects.</p>
        <ErrorText error={create.error} />
        <div className="flex gap-2">
          <Button type="submit" isDisabled={!name.trim() || create.isPending}>Make the link</Button>
          <Button variant="ghost" onPress={() => setOpen(false)}>Cancel</Button>
        </div>
      </Form>
    </Card>
  )
}

function LinkCard({ link: l, projectId }: { link: ShareLink; projectId: string }) {
  const client = useQueryClient()
  const [showEvents, setShowEvents] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const events = useQuery({ queryKey: ['share-link-events', l.id], queryFn: () => api<LinkEvent[]>('GET', `/api/v1/share-links/${l.id}/events`), enabled: showEvents })
  const revoke = useMutation({
    mutationFn: () => api('POST', `/api/v1/share-links/${l.id}/revoke`),
    onSettled: () => client.invalidateQueries({ queryKey: ['share-links', projectId] }),
  })
  const [now] = useState(() => Date.now()) // when the page was opened (render stays pure)
  const expired = new Date(l.expires_at).getTime() < now
  const status = l.revoked ? 'Turned off' : expired ? `Expired ${day(l.expires_at)}` : `Works until ${day(l.expires_at)}`
  return (
    <Card className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">{l.name}</span>
        <span className={`text-sm ${l.revoked || expired ? 'text-stone-500' : 'text-brand-700 dark:text-brand-100'}`}>{status}{l.has_pin ? ' · PIN' : ''}</span>
      </div>
      <p className="text-sm text-stone-600 dark:text-stone-400">{summary(l)}</p>
      <p className="text-sm text-stone-500">{l.last_used_at ? `Last used ${new Date(l.last_used_at).toLocaleString()}` : 'Not used yet'}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" onPress={() => setShowEvents(!showEvents)}>{showEvents ? 'Hide activity' : 'Activity'}</Button>
        {!l.revoked && !expired && (
          <Button variant="danger-ghost" isDisabled={revoke.isPending} onPress={() => (confirm ? revoke.mutate() : setConfirm(true))}>
            {confirm ? 'Tap again to turn it off' : 'Turn off'}
          </Button>
        )}
      </div>
      {showEvents && (
        <ul aria-label={`Activity of ${l.name}`} className="space-y-1 text-sm">
          {events.data?.length === 0 && <li className="text-stone-500">Nothing yet.</li>}
          {(events.data ?? []).map((e, i) => (
            <li key={i}><span className="text-stone-500">{new Date(e.at).toLocaleString()}</span> · <span className="font-medium">{e.guest_name}</span> {ACTION[e.action] ?? e.action}{e.detail && `: ${e.detail}`}</li>
          ))}
        </ul>
      )}
      <ErrorText error={revoke.error ?? events.error} />
    </Card>
  )
}
