import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { JSONContent } from '@tiptap/react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Dialog, Heading, Modal } from 'react-aria-components'
import { api, ApiError } from '../api.ts'
import { notePreview } from '../preview.ts'
import { navigate, setNavigationGuard } from '../router.ts'
import { ArchiveIcon, CheckIcon, CopyIcon, PencilIcon } from '../icons.tsx'
import { useRemembered } from '../remember.ts'
import { Movable } from './Movable.tsx'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'

const NoteEditor = lazy(() => import('./NoteEditor.tsx'))

type CardLine = { kind: 'text' | 'heading' | 'bullet' | 'check'; text: string; depth: number; marker: string | null; index: number | null; checked: boolean | null }
type NoteCard = { note_id: string; lines: CardLine[]; more: number }

type Note = {
  id: string
  project_id: string
  title: string
  text_content: string
  updated_at: string
  version: number
  archived: boolean
  can_edit: boolean
  content?: JSONContent | null
}

/** The project's notes and their cards (shared by the Notes group and single-note tiles). */
function useNoteCards(projectId: string) {
  const client = useQueryClient()
  const notes = useQuery({ queryKey: ['notes', projectId], queryFn: () => api<Note[]>('GET', `/api/v1/projects/${projectId}/notes`) })
  // What each card shows: the note's lines in order, with checkboxes that can be ticked here.
  // Keyed by the versions of the notes shown, so the cards are never older than the list.
  const shown = notes.data?.map((n) => `${n.id}:${n.version}`).join(',')
  const cards = useQuery({
    queryKey: ['note-cards', projectId, shown],
    queryFn: () => api<NoteCard[]>('GET', `/api/v1/projects/${projectId}/note-cards`),
    enabled: shown !== undefined,
    placeholderData: keepPreviousData,
    staleTime: 0, // notes change in the editor; always refetch when the page opens
  })
  const tick = useMutation({
    mutationFn: ({ noteId, line }: { noteId: string; line: CardLine }) =>
      api('POST', `/api/v1/notes/${noteId}/checklist`, { index: line.index, text: line.text, checked: !line.checked }),
    onSettled: (_data, _error, { noteId }) => Promise.all([
      client.invalidateQueries({ queryKey: ['notes', projectId] }),
      client.removeQueries({ queryKey: ['note', noteId] }),
    ]),
  })
  // Archive: off the project page, into "Archived" (and back with Restore).
  const archive = useMutation({
    mutationFn: ({ noteId, archived }: { noteId: string; archived: boolean }) =>
      api('POST', `/api/v1/notes/${noteId}/archive`, { archived }),
    onSettled: () => client.invalidateQueries({ queryKey: ['notes', projectId] }),
  })
  const cardOf = (noteId: string) => cards.data?.find((c) => c.note_id === noteId)
  return { notes, tick, archive, cardOf }
}

/** Notes group on a project page (notes given their own tile are left out). */
export function ProjectNotes({ projectId, canEdit, exclude = [] }: { projectId: string; canEdit: boolean; exclude?: string[] }) {
  const { notes, tick, archive, cardOf } = useNoteCards(projectId)
  const listed = (notes.data ?? []).filter((n) => !exclude.includes(n.id))
  return (
    <section aria-label="Notes" className="space-y-3">
      <h2 className="text-lg font-semibold">Notes</h2>
      {/* Two stacked columns (on a wide tile): short cards don't leave gaps next to tall ones.
          Newest note first; the order doesn't change when a note is edited or ticked. */}
      <ul className="gap-2 @xl:columns-2">
        {listed.map((n) => (
          <li key={n.id} className="mb-2 break-inside-avoid">
            <Movable dragKey={`note:${n.id}`} label={`Note: ${n.title}`}>
              <NoteCardView note={n} card={cardOf(n.id)} canEdit={canEdit} onTick={(line) => tick.mutate({ noteId: n.id, line })}
                onArchive={() => archive.mutate({ noteId: n.id, archived: true })} />
            </Movable>
          </li>
        ))}
      </ul>
      {notes.data?.length === 0 && <p className="text-sm text-stone-500">No notes yet.</p>}
      <ArchivedNotes projectId={projectId} canEdit={canEdit} onRestore={(noteId) => archive.mutate({ noteId, archived: false })} />
      <ErrorText error={tick.error ?? archive.error ?? notes.error} />
    </section>
  )
}

/** Archived notes, folded away under the project's notes; Restore puts one back. */
function ArchivedNotes({ projectId, canEdit, onRestore }: { projectId: string; canEdit: boolean; onRestore: (noteId: string) => void }) {
  const archived = useQuery({
    queryKey: ['notes', projectId, 'archived'],
    queryFn: () => api<Note[]>('GET', `/api/v1/projects/${projectId}/notes?archived=true`),
  })
  const list = archived.data ?? []
  if (list.length === 0) return null
  return (
    <details className="rounded-2xl">
      <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium text-stone-500">Archived ({list.length})</summary>
      <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
        {list.map((n) => (
          <li key={n.id} className="flex items-center gap-2 px-3">
            <Link to={`/notes/${n.id}`} className="min-h-11 min-w-0 flex-1 truncate py-2.5">{n.title}</Link>
            {canEdit && <Button variant="ghost" onPress={() => onRestore(n.id)}>Restore</Button>}
          </li>
        ))}
      </ul>
    </details>
  )
}

/** New note (in the project's add bar): give it a title, then write it in the editor. */
export function NewNoteForm({ projectId }: { projectId: string }) {
  const client = useQueryClient()
  const [title, setTitle] = useState('')
  const create = useMutation({
    mutationFn: () => api<Note>('POST', `/api/v1/projects/${projectId}/notes`, { title: title.trim() || 'Untitled note' }),
    onSuccess: async (note) => { await client.invalidateQueries({ queryKey: ['notes', projectId] }); navigate(`/notes/${note.id}`) },
  })
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <div className="min-w-0 flex-1"><Field label="Name of the new note" maxLength={200} value={title} onChange={setTitle} description="Leave empty for “Untitled note”" /></div>
      <Button type="submit" isDisabled={create.isPending}>Create and write</Button>
      <ErrorText error={create.error} />
    </form>
  )
}

/** One note in its own tile on the project page. */
export function NoteTile({ projectId, noteId, canEdit }: { projectId: string; noteId: string; canEdit: boolean }) {
  const { notes, tick, archive, cardOf } = useNoteCards(projectId)
  const note = notes.data?.find((n) => n.id === noteId)
  if (!note) return null // deleted or archived since, or not shared with this person
  return (
    <section aria-label={`Note: ${note.title}`}>
      <NoteCardView note={note} card={cardOf(note.id)} canEdit={canEdit} onTick={(line) => tick.mutate({ noteId: note.id, line })}
        onArchive={() => archive.mutate({ noteId: note.id, archived: true })} />
      <ErrorText error={tick.error ?? archive.error} />
    </section>
  )
}

function NoteCardView({ note, card, canEdit, onTick, onArchive }: {
  note: Note; card: NoteCard | undefined; canEdit: boolean; onTick: (line: CardLine) => void; onArchive: () => void
}) {
  return (
    <Card>
      <div className="flex items-start gap-1">
        <Link to={`/notes/${note.id}`} className="block min-w-0 flex-1 py-2 font-semibold">{note.title}</Link>
        <CopyNote noteId={note.id} />
        {canEdit && (
          <Button variant="ghost" aria-label={`Archive ${note.title}`} onPress={onArchive} className="min-w-11 px-2 text-stone-600 dark:text-stone-400">
            <ArchiveIcon />
          </Button>
        )}
        {canEdit && (
          <Link to={`/notes/${note.id}`} aria-label="Edit note"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800">
            <PencilIcon />
          </Link>
        )}
      </div>
      {/* A tap anywhere on the note opens it, except on a checkbox or button (owner request,
          2026-10-02). Keyboard and screen-reader users have the title link for the same thing. */}
      <div className="cursor-pointer" onClick={(e) => openUnlessControl(e, note.id)}>
        <NoteCardBody card={card} note={note} canEdit={canEdit} onTick={onTick} />
      </div>
    </Card>
  )
}

function openUnlessControl(e: React.MouseEvent, noteId: string) {
  if ((e.target as Element).closest('input, button, a, label')) return
  if (window.getSelection()?.toString()) return // selecting text to copy, not opening
  navigate(`/notes/${noteId}`)
}

/** Copies the whole note as plain text (checkboxes as ☐ / ☑). */
function CopyNote({ noteId }: { noteId: string }) {
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)
  const copy = async () => {
    try {
      const note = await api<Note>('GET', `/api/v1/notes/${noteId}`)
      await navigator.clipboard.writeText(noteText(note.content ?? EMPTY_DOC))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setFailed(true)
      setTimeout(() => setFailed(false), 3000)
    }
  }
  return (
    <Button variant="ghost" aria-label={copied ? 'Copied' : failed ? "Couldn't copy" : 'Copy note text'} onPress={() => void copy()}
      className="min-w-11 px-2 text-stone-600 dark:text-stone-400">
      {copied ? <CheckIcon /> : <CopyIcon />}
    </Button>
  )
}

const COLLAPSED_LINES = 8
const INDENT = ['', 'pl-6', 'pl-12', 'pl-16', 'pl-20', 'pl-24', 'pl-28']

/** The note on its card, in its own order; long notes open up with "Show all". */
function NoteCardBody({ card, note, canEdit, onTick }: {
  card: NoteCard | undefined; note: Note; canEdit: boolean; onTick: (line: CardLine) => void
}) {
  const [expanded, setExpanded] = useRemembered(`note-expanded:${note.id}`, false)
  // Beyond the first 50 notes (or while loading), a short text preview.
  if (!card) return <p className="line-clamp-2 text-stone-600 dark:text-stone-400">{notePreview(note.text_content, false) || 'Empty note'}</p>
  if (card.lines.length === 0) return <p className="text-stone-500">Empty note</p>
  const lines = expanded ? card.lines : card.lines.slice(0, COLLAPSED_LINES)
  const hidden = card.lines.length - COLLAPSED_LINES
  return (
    <div>
      <ul>
        {lines.map((line, i) => (
          <li key={`${i}-${line.kind}-${line.checked}-${line.text}`} className={INDENT[line.depth] ?? ''}>
            {line.kind === 'check' ? (
              <TickRow line={line} canEdit={canEdit} onTick={onTick} />
            ) : line.kind === 'bullet' ? (
              <p className="flex gap-2 py-0.5"><span aria-hidden="true" className="text-stone-500">{line.marker}</span><span className="min-w-0 whitespace-pre-line">{line.text}</span></p>
            ) : (
              <p className={`whitespace-pre-line py-0.5 ${line.kind === 'heading' ? 'font-semibold' : ''}`}>{line.text}</p>
            )}
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <Button variant="ghost" onPress={() => setExpanded(!expanded)} className="-ml-2 px-2 text-sm text-brand-700 dark:text-brand-100">
          {expanded ? 'Show less' : `Show all (${hidden} more)`}
        </Button>
      )}
      {expanded && card.more > 0 && <Link to={`/notes/${note.id}`} className="block text-sm text-brand-700 dark:text-brand-100">+{card.more} more lines in the note</Link>}
    </div>
  )
}

/** The whole note as plain text, for copying (checkboxes as ☐ / ☑, lists as • or 1.). */
function noteText(doc: JSONContent): string {
  const inline = (n: JSONContent): string =>
    n.type === 'text' ? n.text ?? '' : n.type === 'hardBreak' ? '\n' : (n.content ?? []).map(inline).join('')
  const out: string[] = []
  const walk = (blocks: JSONContent[], indent: string) => {
    for (const block of blocks) {
      if (block.type === 'bulletList' || block.type === 'orderedList' || block.type === 'taskList') {
        (block.content ?? []).forEach((item, i) => {
          const marker = block.type === 'taskList' ? (item.attrs?.checked ? '☑ ' : '☐ ') : block.type === 'orderedList' ? `${i + 1}. ` : '• '
          const [first, ...rest] = item.content ?? []
          out.push(indent + marker + (first ? inline(first) : ''))
          walk(rest, `${indent}    `)
        })
      } else if (block.type === 'blockquote') {
        walk(block.content ?? [], `${indent}> `)
      } else if (block.type === 'horizontalRule') {
        out.push(`${indent}---`)
      } else {
        out.push(indent + inline(block))
      }
    }
  }
  walk(doc.content ?? [], '')
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim()
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
    // ...but always open the latest version: a copy kept from an earlier visit could be older
    // than a tick made since on the project page, and Done would then be refused as a conflict.
    gcTime: 0,
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
    client.invalidateQueries({ queryKey: ['note-cards'] }),
  ])
  const save = useMutation({
    // "Merge when safe" (owner decision, 2026-10-02): if the note was saved elsewhere meanwhile
    // (someone else, or this person on another device) but only in a part this save doesn't
    // change (title or text), both changes are kept. Otherwise it's a conflict: keep mine,
    // keep theirs, or keep both. `mode` is the choice after a conflict.
    mutationFn: async (mode: 'save' | 'mine' | 'both' = 'save') => {
      const myTitle = title.trim() || 'Untitled note'
      const put = (version: number, body: { title: string; content: JSONContent }) =>
        api<Note>('PUT', `/api/v1/notes/${note.id}`, body, { 'If-Match': `"${version}"` })
      if (mode === 'both') {
        const copy = await api<Note>('POST', `/api/v1/projects/${note.project_id}/notes`, { title: `${myTitle} (my copy)`.slice(0, 200) })
        return api<Note>('PUT', `/api/v1/notes/${copy.id}`, { title: copy.title, content: doc }, { 'If-Match': `"${copy.version}"` })
      }
      try {
        return await put(note.version, { title: myTitle, content: doc })
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e
        const latest = await api<Note>('GET', `/api/v1/notes/${note.id}`)
        const mineTitle = myTitle !== note.title
        const theirsTitle = latest.title !== note.title
        const theirsText = JSON.stringify(latest.content ?? EMPTY_DOC) !== JSON.stringify(note.content ?? EMPTY_DOC)
        const clash = (mineTitle && theirsTitle && myTitle !== latest.title) || (edited && theirsText)
        if (clash && mode !== 'mine') throw e
        return put(latest.version, {
          title: mineTitle ? myTitle : latest.title,
          content: edited || mode === 'mine' ? doc : latest.content ?? EMPTY_DOC,
        })
      }
    },
    onSuccess: refresh,
  })
  const conflict = save.error instanceof ApiError && save.error.status === 409
  const choose = async (mode: 'mine' | 'both') => {
    try {
      await save.mutateAsync(mode)
    } catch {
      return // the error is shown
    }
    if (mode === 'both') {
      // My version is saved as a copy; this note now shows theirs.
      await client.invalidateQueries({ queryKey: ['note', note.id] })
    } else {
      await client.invalidateQueries({ queryKey: ['note', note.id] })
      navigate(backTo, { force: true })
    }
  }
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

  // Archive (or restore) from the editor: unsaved changes are saved first.
  const archive = useMutation({
    mutationFn: (archived: boolean) => api('POST', `/api/v1/notes/${note.id}/archive`, { archived }),
  })
  const archiveAndGo = async (archived: boolean) => {
    if (dirty) {
      try {
        await save.mutateAsync('save')
      } catch {
        return // the error (offline, conflict, ...) is shown
      }
    }
    try {
      await archive.mutateAsync(archived)
    } catch {
      return
    }
    await Promise.all([refresh(), client.invalidateQueries({ queryKey: ['note', note.id] })])
    navigate(backTo, { force: true })
  }

  const saveAndGo = async (to: string) => {
    if (dirty) {
      try {
        await save.mutateAsync('save')
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
      {note.archived && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">Archived: not shown on the project page. Tap Restore to bring it back.</p>}
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
          <p className="font-medium">This note was changed in the same place since you opened it (by someone else, or by you on another device), so your changes aren't saved yet.</p>
          <div className="flex flex-wrap gap-2">
            <Button onPress={() => void choose('mine')} isDisabled={save.isPending}>Keep mine</Button>
            <Button variant="secondary" onPress={() => void choose('both')} isDisabled={save.isPending}>Keep both (mine as a copy)</Button>
            <Button variant="danger-ghost" onPress={() => void client.invalidateQueries({ queryKey: ['note', note.id] })}>
              Keep theirs (discard mine)
            </Button>
          </div>
        </div>
      ) : (
        <ErrorText error={save.error ?? remove.error ?? archive.error} />
      )}

      {/* Done stays in reach at the bottom of the screen (above the phone's tab bar). */}
      <div className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-10 flex items-center gap-2 rounded-2xl bg-white/95 p-2 shadow-sm ring-1 ring-stone-200 backdrop-blur md:bottom-4 dark:bg-stone-900/95 dark:ring-stone-800">
        <Button className="flex-1" onPress={() => void saveAndGo(backTo)} isDisabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Done'}
        </Button>
        {dirty && <span role="status" className="text-xs text-amber-700 dark:text-amber-400">Not saved yet</span>}
        {note.can_edit && (
          <Button variant="ghost" onPress={() => void archiveAndGo(!note.archived)} isDisabled={save.isPending || archive.isPending}>
            {note.archived ? 'Restore' : 'Archive'}
          </Button>
        )}
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

/** One checkbox; it shows the new state in the same tap, then the save catches up. */
function TickRow({ line, canEdit, onTick }: { line: CardLine; canEdit: boolean; onTick: (line: CardLine) => void }) {
  const [checked, setChecked] = useState(Boolean(line.checked))
  return (
    <div className="flex min-h-11 items-start gap-1">
      {/* Only the box ticks; tapping the words opens the note. The label is the box's tap area. */}
      <label className="-my-0.5 -ml-3 flex min-h-11 min-w-11 shrink-0 justify-center pt-3">
        <input type="checkbox" checked={checked} disabled={!canEdit} aria-label={line.text || '(empty)'} className="size-5 accent-brand-600"
          onChange={() => { setChecked(!checked); onTick(line) }} />
      </label>
      <span className={`min-w-0 whitespace-pre-line py-2.5 ${checked ? 'text-stone-500 line-through' : ''}`}>{line.text || '(empty)'}</span>
    </div>
  )
}
