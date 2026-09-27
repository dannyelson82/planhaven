// The shared rich-text editor (TipTap + Yjs). Loaded only when a note is opened: it's large.
import Collaboration from '@tiptap/extension-collaboration'
import CollaborationCaret from '@tiptap/extension-collaboration-caret'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { EditorContent, useEditor, useEditorState, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect, useState } from 'react'
import * as Y from 'yjs'
import { api } from '../api.ts'
import { NoteConnection, type Status } from '../collab.ts'
import { toMarkdown } from '../markdown.ts'
import { Button, Card } from '../ui.tsx'
const STATUS_TEXT: Record<Status, string> = {
  connecting: 'Connecting…',
  connected: 'Saved automatically',
  offline: 'Offline: reconnecting…',
  denied: 'You no longer have access to this note.',
}

// Caret colours are CSS classes (see index.css), never inline styles: the CSP forbids them.
const CARET_COLOURS = 8

function colourFor(userId: string): number {
  let hash = 0
  for (const ch of userId) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return hash % CARET_COLOURS
}

// Awareness data comes from other people's browsers: treat it as untrusted.
function safeColour(value: unknown): number {
  return Number.isInteger(value) && (value as number) >= 0 && (value as number) < CARET_COLOURS ? (value as number) : 0
}

function renderCaret(user: Record<string, unknown>): HTMLElement {
  const caret = document.createElement('span')
  caret.className = `collab-caret collab-c${safeColour(user.colour)}`
  const label = document.createElement('span')
  label.className = 'collab-caret-label'
  label.textContent = typeof user.name === 'string' ? user.name.slice(0, 40) : 'Someone'
  caret.append(label)
  return caret
}

type Live = { doc: Y.Doc; connection: NoteConnection }

export default function NoteEditor(props: { noteId: string; canEdit: boolean; me: { id: string; name: string } }) {
  const { noteId, canEdit } = props
  const [live, setLive] = useState<Live | null>(null)
  const [status, setStatus] = useState<Status>('connecting')
  const [synced, setSynced] = useState(false)
  // The document and connection live exactly as long as this screen is open.
  useEffect(() => {
    const doc = new Y.Doc()
    const connection = new NoteConnection(noteId, doc, !canEdit, (c) => { setStatus(c.status); setSynced(c.synced) })
    // Creating the connection is the external side effect; the editor needs it to render.
    // oxlint-disable-next-line react/set-state-in-effect
    setLive({ doc, connection })
    return () => { connection.destroy(); doc.destroy(); setLive(null) }
  }, [noteId, canEdit])
  if (!live) return null
  return <LiveEditor {...props} {...live} status={status} synced={synced} />
}

function LiveEditor({ noteId, canEdit, me, doc, connection, status, synced }: {
  noteId: string; canEdit: boolean; me: { id: string; name: string }; status: Status; synced: boolean
} & Live) {

  const editor = useEditor({
    injectCSS: false,
    editable: canEdit,
    immediatelyRender: true,
    editorProps: { attributes: { class: 'note-content', role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Note', ...(canEdit ? {} : { 'aria-readonly': 'true' }) } },
    extensions: [
      StarterKit.configure({ undoRedo: false, link: { openOnClick: true, autolink: true } }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Collaboration.configure({ document: doc }),
      CollaborationCaret.configure({
        provider: { awareness: connection.awareness },
        user: { name: me.name, colour: colourFor(me.id) },
        render: renderCaret,
        selectionRender: (user: Record<string, unknown>) => ({ nodeName: 'span', class: `collab-selection collab-c${safeColour(user.colour)}` }),
      }),
    ],
  }, [connection])

  // Keep the plain-text copy (used for previews and search) current: a few seconds after
  // this person's own edits, and when they leave the note.
  useEffect(() => {
    if (!canEdit || !editor) return
    let timer: ReturnType<typeof setTimeout> | undefined
    let dirty = false
    const save = () => {
      if (!dirty) return
      dirty = false
      void api('PUT', `/api/v1/notes/${noteId}/text`, { text: toMarkdown(editor.getJSON()).slice(0, 200_000) }).catch(() => { dirty = true })
    }
    const onUpdate = (_update: Uint8Array, origin: unknown) => {
      if (origin === connection) return // someone else's edit: their browser saves it
      dirty = true
      clearTimeout(timer)
      timer = setTimeout(save, 3000)
    }
    doc.on('update', onUpdate)
    return () => { doc.off('update', onUpdate); clearTimeout(timer); save() }
  }, [canEdit, editor, doc, connection, noteId])

  return (
    <div className="space-y-2">
      {canEdit && editor && <Toolbar editor={editor} />}
      <Card className="min-h-64">
        {!synced && status !== 'denied' ? <p className="text-stone-500">Loading…</p> : null}
        <EditorContent editor={editor} className={synced ? '' : 'hidden'} />
      </Card>
      <p role="status" className={`text-xs ${status === 'connected' ? 'text-stone-500' : 'text-amber-700 dark:text-amber-400'}`}>
        {canEdit ? STATUS_TEXT[status] : status === 'connected' ? 'View only: changes by others appear live' : STATUS_TEXT[status]}
      </p>
    </div>
  )
}

function Toolbar({ editor }: { editor: Editor }) {
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive('bold'),
      italic: e.isActive('italic'),
      heading: e.isActive('heading', { level: 2 }),
      bullets: e.isActive('bulletList'),
      tasks: e.isActive('taskList'),
    }),
  })
  const tools: { label: string; text: string; active: boolean; run: () => void }[] = [
    { label: 'Heading', text: 'H', active: state.heading, run: () => editor.chain().focus().toggleHeading({ level: 2 }).run() },
    { label: 'Bold', text: 'B', active: state.bold, run: () => editor.chain().focus().toggleBold().run() },
    { label: 'Italic', text: 'I', active: state.italic, run: () => editor.chain().focus().toggleItalic().run() },
    { label: 'Bulleted list', text: '•', active: state.bullets, run: () => editor.chain().focus().toggleBulletList().run() },
    { label: 'Checklist', text: '☑', active: state.tasks, run: () => editor.chain().focus().toggleTaskList().run() },
  ]
  return (
    <div role="toolbar" aria-label="Formatting" className="flex flex-wrap gap-1">
      {tools.map((t) => (
        <Button key={t.label} variant="ghost" aria-label={t.label} aria-pressed={t.active} onPress={t.run}
          className={`min-w-11 px-2 ${t.active ? 'bg-brand-100 text-brand-700 dark:bg-stone-800 dark:text-brand-100' : ''}`}>
          {t.text}
        </Button>
      ))}
    </div>
  )
}
