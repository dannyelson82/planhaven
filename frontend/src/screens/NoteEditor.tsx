// The note editor (TipTap), loaded only when a note is opened. It edits a copy of the note in
// this browser; nothing is sent until the person taps Done (owner decision 2026-09-28,
// docs/adr/0016-notes-save-on-done.md). No live co-editing, no automatic saving.
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { EditorContent, type JSONContent, useEditor, useEditorState, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Button, Card } from '../ui.tsx'

export default function NoteEditor({ initial, canEdit, onChange }: {
  initial: JSONContent
  canEdit: boolean
  onChange: (doc: JSONContent) => void
}) {
  const editor = useEditor({
    injectCSS: false,
    editable: canEdit,
    immediatelyRender: true,
    content: initial,
    editorProps: {
      attributes: {
        class: 'note-content', role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Note',
        ...(canEdit ? {} : { 'aria-readonly': 'true' }),
        // Grammar-checker extensions (Grammarly, LanguageTool) rewrite text inside editors
        // behind the editor's back, which garbles notes. Ask them to stay out.
        'data-gramm': 'false', 'data-gramm_editor': 'false', 'data-enable-grammarly': 'false',
        'data-lt-active': 'false',
      },
    },
    extensions: [
      StarterKit.configure({ link: { openOnClick: false, autolink: true } }),
      TaskList,
      TaskItem.configure({ nested: true }),
    ],
    onUpdate: ({ editor: e }) => onChange(e.getJSON()),
  })

  return (
    <div className="space-y-2">
      {canEdit && editor && <Toolbar editor={editor} />}
      <Card className="min-h-64">
        <EditorContent editor={editor} />
      </Card>
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
