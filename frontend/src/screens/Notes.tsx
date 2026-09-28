import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import { api } from '../api.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Link } from '../ui.tsx'

const NoteEditor = lazy(() => import('./NoteEditor.tsx'))

type ChecklistItem = { index: number; text: string; checked: boolean }
type NoteChecklist = { note_id: string; title: string; items: ChecklistItem[] }

type Note = {
  id: string
  project_id: string
  title: string
  text_content: string
  updated_at: string
  version: number
  can_edit: boolean
}

/** Notes section on a project page. */
export function ProjectNotes({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const client = useQueryClient()
  const notes = useQuery({ queryKey: ['notes', projectId], queryFn: () => api<Note[]>('GET', `/api/v1/projects/${projectId}/notes`) })
  const create = useMutation({
    mutationFn: () => api<Note>('POST', `/api/v1/projects/${projectId}/notes`, { title: 'Untitled note' }),
    onSuccess: async (note) => { await client.invalidateQueries({ queryKey: ['notes', projectId] }); navigate(`/notes/${note.id}`) },
  })
  // Checkboxes inside notes can be ticked right here, without opening the note.
  const checklists = useQuery({
    queryKey: ['note-checklists', projectId],
    queryFn: () => api<NoteChecklist[]>('GET', `/api/v1/projects/${projectId}/note-checklists`),
  })
  const tick = useMutation({
    mutationFn: ({ noteId, item }: { noteId: string; item: ChecklistItem }) =>
      api('POST', `/api/v1/notes/${noteId}/checklist`, { index: item.index, text: item.text, checked: !item.checked }),
    onSettled: () => Promise.all([
      client.invalidateQueries({ queryKey: ['note-checklists', projectId] }),
      client.invalidateQueries({ queryKey: ['notes', projectId] }),
    ]),
  })
  const itemsOf = (noteId: string) => checklists.data?.find((c) => c.note_id === noteId)?.items ?? []
  return (
    <section aria-label="Notes" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Notes</h2>
        {canEdit && <Button variant="secondary" onPress={() => create.mutate()} isDisabled={create.isPending}>New note</Button>}
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        {(notes.data ?? []).map((n) => (
          <li key={n.id}>
            <Card>
              <Link to={`/notes/${n.id}`} className="block font-semibold">{n.title}</Link>
              {itemsOf(n.id).length > 0 ? (
                <>
                  <p className="line-clamp-1 text-sm text-stone-500">{n.text_content}</p>
                  <NoteChecklistItems items={itemsOf(n.id)} canEdit={canEdit} noteId={n.id} onTick={(item) => tick.mutate({ noteId: n.id, item })} />
                </>
              ) : (
                <p className="line-clamp-2 text-sm text-stone-500">{n.text_content || 'Empty note'}</p>
              )}
            </Card>
          </li>
        ))}
      </ul>
      {notes.data?.length === 0 && <p className="text-sm text-stone-500">No notes yet.</p>}
      <ErrorText error={create.error ?? tick.error ?? notes.error} />
    </section>
  )
}

/** One note: title, toolbar and the shared editor. */
export function NoteScreen({ id, me }: { id: string; me: { id: string; name: string } }) {
  const client = useQueryClient()
  const note = useQuery({ queryKey: ['note', id], queryFn: () => api<Note>('GET', `/api/v1/notes/${id}`) })
  const [title, setTitle] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const rename = useMutation({
    mutationFn: (value: string) => api('PATCH', `/api/v1/notes/${id}`, { title: value }, { 'If-Match': `"${note.data?.version}"` }),
    onSettled: async () => {
      setTitle(null)
      await Promise.all([client.invalidateQueries({ queryKey: ['note', id] }), client.invalidateQueries({ queryKey: ['notes'] })])
    },
  })
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/notes/${id}`),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['notes'] })
      navigate(`/projects/${note.data?.project_id}`)
    },
  })
  if (note.isPending) return <p className="text-stone-500">Loading…</p>
  if (!note.data) return <ErrorText error={note.error} />
  const n = note.data
  const saveTitle = () => {
    const value = (title ?? '').trim()
    if (title !== null && value && value !== n.title) rename.mutate(value)
    else setTitle(null)
  }
  return (
    <div className="space-y-4">
      <Link to={`/projects/${n.project_id}`} className="text-sm text-brand-700 dark:text-brand-100">← Back to project</Link>
      {n.can_edit ? (
        <input
          aria-label="Note title"
          maxLength={200}
          value={title ?? n.title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
          className="block w-full rounded-xl bg-transparent px-1 text-2xl font-bold focus:outline-2 focus:outline-brand-600"
        />
      ) : (
        <h1 className="text-2xl font-bold">{n.title}</h1>
      )}
      {/* key: a fresh document and connection per note. */}
      <Suspense fallback={<p className="text-stone-500">Loading editor…</p>}>
        <NoteEditor key={n.id} noteId={n.id} canEdit={n.can_edit} me={me} />
      </Suspense>
      {n.can_edit && (
        <div className="flex justify-end">
          <Button variant="danger-ghost" onPress={() => (confirmDelete ? remove.mutate() : setConfirmDelete(true))} isDisabled={remove.isPending}>
            {confirmDelete ? 'Tap again to delete this note' : 'Delete note'}
          </Button>
        </div>
      )}
      <ErrorText error={rename.error ?? remove.error} />
    </div>
  )
}

const SHOWN_ITEMS = 8

function NoteChecklistItems({ items, canEdit, noteId, onTick }: {
  items: ChecklistItem[]; canEdit: boolean; noteId: string; onTick: (item: ChecklistItem) => void
}) {
  return (
    <div className="mt-1">
      <ul>
        {items.slice(0, SHOWN_ITEMS).map((item) => (
          // key: start over whenever the saved state changes.
          <TickRow key={`${item.index}-${item.checked}-${item.text}`} item={item} canEdit={canEdit} onTick={onTick} />
        ))}
      </ul>
      {items.length > SHOWN_ITEMS && <Link to={`/notes/${noteId}`} className="text-sm text-brand-700 dark:text-brand-100">+{items.length - SHOWN_ITEMS} more in the note</Link>}
    </div>
  )
}

/** One checkbox; it shows the new state in the same tap, then the save catches up. */
function TickRow({ item, canEdit, onTick }: { item: ChecklistItem; canEdit: boolean; onTick: (item: ChecklistItem) => void }) {
  const [checked, setChecked] = useState(item.checked)
  return (
    <li>
      <label className="flex min-h-11 items-center gap-3">
        <input type="checkbox" checked={checked} disabled={!canEdit} className="size-5 shrink-0 accent-brand-600"
          onChange={() => { setChecked(!checked); onTick(item) }} />
        <span className={`min-w-0 ${checked ? 'text-stone-500 line-through' : ''}`}>{item.text || '(empty)'}</span>
      </label>
    </li>
  )
}
