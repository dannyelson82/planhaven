import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { JSONContent } from '@tiptap/react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Dialog, Heading, Modal } from 'react-aria-components'
import { api, ApiError } from '../api.ts'
import { notePreview } from '../preview.ts'
import { navigate, setNavigationGuard } from '../router.ts'
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
  content?: JSONContent | null
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
    staleTime: 0, // notes change in the editor; always refetch when the page opens
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
      {/* Two stacked columns: short cards don't leave gaps next to tall ones. */}
      <ul className="gap-2 sm:columns-2">
        {(notes.data ?? []).map((n) => (
          <li key={n.id} className="mb-2 break-inside-avoid">
            <Card>
              <Link to={`/notes/${n.id}`} className="block font-semibold">{n.title}</Link>
              {itemsOf(n.id).length > 0 ? (
                <>
                  {notePreview(n.text_content, true) && <p className="line-clamp-1 text-sm text-stone-500">{notePreview(n.text_content, true)}</p>}
                  <NoteChecklistItems items={itemsOf(n.id)} canEdit={canEdit} noteId={n.id} onTick={(item) => tick.mutate({ noteId: n.id, item })} />
                </>
              ) : (
                <p className="line-clamp-2 text-sm text-stone-500">{notePreview(n.text_content, false) || 'Empty note'}</p>
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

/** A note's plain text (for "Copy my text" after a conflict). */
function plainText(node: JSONContent): string {
  if (node.type === 'text') return node.text ?? ''
  if (node.type === 'hardBreak') return '\n'
  const inner = (node.content ?? []).map(plainText)
  return node.type === 'doc' || node.type?.endsWith('List') ? inner.join('\n') : inner.join('')
}

const EMPTY_DOC: JSONContent = { type: 'doc', content: [{ type: 'paragraph' }] }

/** One note. Edit, then tap Done to save and go back; nothing is saved before that
 * (owner decision 2026-09-28, docs/adr/0016). Leaving with unsaved changes asks first. */
export function NoteScreen({ id }: { id: string }) {
  const note = useQuery({
    queryKey: ['note', id],
    queryFn: () => api<Note>('GET', `/api/v1/notes/${id}`),
    // The page holds its own copy while editing; don't swap it underneath the person.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  if (note.isPending) return <p className="text-stone-500">Loading…</p>
  if (!note.data) return <ErrorText error={note.error} />
  return <NoteForm key={`${note.data.id}-${note.data.version}`} note={note.data} />
}

function NoteForm({ note }: { note: Note }) {
  const client = useQueryClient()
  const backTo = `/projects/${note.project_id}`
  const [title, setTitle] = useState(note.title)
  const [doc, setDoc] = useState<JSONContent>(note.content ?? EMPTY_DOC)
  const [edited, setEdited] = useState(false)
  const [leavingTo, setLeavingTo] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const dirty = note.can_edit && (edited || title !== note.title)
  const dirtyRef = useRef(dirty)
  useEffect(() => { dirtyRef.current = dirty }, [dirty])

  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['notes'] }),
    client.invalidateQueries({ queryKey: ['note-checklists'] }),
  ])
  const save = useMutation({
    mutationFn: () => api<Note>('PUT', `/api/v1/notes/${note.id}`,
      { title: title.trim() || 'Untitled note', content: doc }, { 'If-Match': `"${note.version}"` }),
    onSuccess: refresh,
  })
  const conflict = save.error instanceof ApiError && save.error.status === 409
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/notes/${note.id}`),
    onSuccess: async () => { await refresh(); navigate(backTo, { force: true }) },
  })

  // Hold any navigation (links, menu, the browser's back button) while there are unsaved
  // changes, and ask. Closing or reloading the tab gets the browser's own warning.
  useEffect(() => {
    setNavigationGuard((to) => {
      if (!dirtyRef.current) return true
      setLeavingTo(to)
      return false
    })
    const warn = (event: BeforeUnloadEvent) => { if (dirtyRef.current) event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => {
      setNavigationGuard(null)
      window.removeEventListener('beforeunload', warn)
    }
  }, [])

  const saveAndGo = async (to: string) => {
    if (dirty) {
      try {
        await save.mutateAsync()
      } catch {
        setLeavingTo(null)
        return // stay: the error (offline, conflict, ...) is shown
      }
    }
    await client.invalidateQueries({ queryKey: ['note', note.id] })
    navigate(to, { force: true })
  }

  return (
    <div className="space-y-4">
      <Link to={backTo} className="text-sm text-brand-700 dark:text-brand-100">← Back to project</Link>
      {note.can_edit ? (
        <input aria-label="Note title" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)}
          className="block w-full rounded-xl bg-transparent px-1 text-2xl font-bold focus:outline-2 focus:outline-brand-600" />
      ) : (
        <h1 className="text-2xl font-bold">{note.title}</h1>
      )}
      <Suspense fallback={<p className="text-stone-500">Loading editor…</p>}>
        <NoteEditor initial={note.content ?? EMPTY_DOC} canEdit={note.can_edit}
          onChange={(next) => { setDoc(next); setEdited(true) }} />
      </Suspense>

      {conflict ? (
        <div role="alert" className="space-y-2 rounded-xl bg-red-50 p-3 text-sm text-red-900 dark:bg-red-950 dark:text-red-200">
          <p className="font-medium">Someone else saved this note since you opened it, so your changes weren't saved.</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onPress={() => void navigator.clipboard.writeText(plainText(doc))}>Copy my text</Button>
            <Button variant="danger-ghost" onPress={() => void client.invalidateQueries({ queryKey: ['note', note.id] })}>
              Load their version (discard mine)
            </Button>
          </div>
        </div>
      ) : (
        <ErrorText error={save.error ?? remove.error} />
      )}

      {/* Done stays in reach at the bottom of the screen (above the phone's tab bar). */}
      <div className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-10 flex items-center gap-2 rounded-2xl bg-white/95 p-2 shadow-sm ring-1 ring-stone-200 backdrop-blur md:bottom-4 dark:bg-stone-900/95 dark:ring-stone-800">
        <Button className="flex-1" onPress={() => void saveAndGo(backTo)} isDisabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Done'}
        </Button>
        {dirty && <span role="status" className="text-xs text-amber-700 dark:text-amber-400">Not saved yet</span>}
        {note.can_edit && (
          <Button variant="danger-ghost" onPress={() => (confirmDelete ? remove.mutate() : setConfirmDelete(true))} isDisabled={remove.isPending}>
            {confirmDelete ? 'Tap again to delete' : 'Delete'}
          </Button>
        )}
      </div>

      <Modal isOpen={leavingTo !== null} onOpenChange={(open) => { if (!open) setLeavingTo(null) }} isDismissable
        className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
        <Dialog className="w-full max-w-sm space-y-4 rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
          <Heading slot="title" className="text-lg font-semibold">Save your changes?</Heading>
          <p>This note has changes that aren't saved yet.</p>
          <div className="flex flex-col gap-2">
            <Button onPress={() => void saveAndGo(leavingTo ?? backTo)}>Save and leave</Button>
            <Button variant="danger-ghost" onPress={() => navigate(leavingTo ?? backTo, { force: true })}>Leave without saving</Button>
            <Button variant="ghost" onPress={() => setLeavingTo(null)}>Keep editing</Button>
          </div>
        </Dialog>
      </Modal>
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
