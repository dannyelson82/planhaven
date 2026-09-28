// The project's add bar (owner request, 2026-09-28): every "add" lives in one row under the
// project title; each opens a drawer that slides down with its form.
import { type ReactNode, useState } from 'react'
import { Button, Card } from '../ui.tsx'

export type AddKind = 'task' | 'list' | 'note' | 'file' | 'quote' | 'cost'

const BUTTON: Record<AddKind, string> = {
  task: 'Task', list: 'List', note: 'Note', file: 'Photo or file', quote: 'Quote', cost: 'Cost',
}
// Drawer titles; worded so they don't repeat the field labels inside them.
const TITLE: Record<AddKind, string> = {
  task: 'Add to tasks', list: 'Add to lists', note: 'Start a note', file: 'Add to photos and files',
  quote: 'Add to quotes', cost: 'Add to costs',
}

export function AddBar({ forms }: { forms: Record<AddKind, ReactNode> }) {
  const [open, setOpen] = useState<AddKind | null>(null)
  return (
    <div className="space-y-3">
      <div role="toolbar" aria-label="Add to this project" className="grid grid-cols-3 gap-2 md:flex md:flex-wrap">
        {(Object.keys(BUTTON) as AddKind[]).map((kind) => (
          <Button key={kind} variant={open === kind ? 'primary' : 'secondary'} aria-expanded={open === kind}
            aria-controls={open === kind ? 'add-drawer' : undefined} className="px-2 text-sm md:px-4 md:text-base"
            onPress={() => setOpen(open === kind ? null : kind)}>
            <span aria-hidden="true">+</span>{BUTTON[kind]}
          </Button>
        ))}
      </div>
      {open && (
        <Card key={open} className="space-y-3 motion-safe:animate-slide-down">
          <div id="add-drawer" className="flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">{TITLE[open]}</h2>
            <Button variant="ghost" onPress={() => setOpen(null)}>Close</Button>
          </div>
          {forms[open]}
        </Card>
      )}
    </div>
  )
}
