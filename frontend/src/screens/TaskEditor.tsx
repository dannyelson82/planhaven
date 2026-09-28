import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Dialog, DialogTrigger, Heading, Modal } from 'react-aria-components'
import { api, type Need, type Task } from '../api.ts'
import { Button, ErrorText, Field, Form } from '../ui.tsx'

/** Edit a task's title, notes, due date and the list items it needs. */
export function TaskEditor({ task, needs = [] }: { task: Task; needs?: Need[] }) {
  return (
    <DialogTrigger>
      <Button variant="ghost" aria-label={`Edit ${task.title}`}>✎</Button>
      <Modal isDismissable className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 sm:items-center">
        <Dialog className="max-h-[85dvh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
          {({ close }) => <EditForm task={task} needs={needs} close={close} />}
        </Dialog>
      </Modal>
    </DialogTrigger>
  )
}

function EditForm({ task, needs, close }: { task: Task; needs: Need[]; close: () => void }) {
  const client = useQueryClient()
  const initial = needs.map((n) => n.list_item_id)
  const [picked, setPicked] = useState<string[]>(initial)
  const needsChanged = picked.length !== initial.length || picked.some((id) => !initial.includes(id))
  const [title, setTitle] = useState(task.title)
  const [notes, setNotes] = useState(task.notes)
  const [due, setDue] = useState(task.due_at ? task.due_at.slice(0, 10) : '')
  const save = useMutation({
    mutationFn: () =>
      api('PATCH', `/api/v1/tasks/${task.id}`, {
        title, notes,
        due_at: due ? `${due}T00:00:00Z` : null,
        due_all_day: !!due,
      }, { 'If-Match': `"${task.version}"` }).then(() =>
        needsChanged ? api('PUT', `/api/v1/tasks/${task.id}/needs`, { item_ids: picked }) : undefined),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['tasks', task.project_id] }),
        client.invalidateQueries({ queryKey: ['task-needs', task.project_id] }),
      ])
      close()
    },
  })
  return (
    <Form onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <Heading slot="title" className="text-lg font-semibold">Edit task</Heading>
      <Field label="Title" isRequired maxLength={300} value={title} onChange={setTitle} />
      <Field label="Notes" multiline maxLength={20000} value={notes} onChange={setNotes} />
      <label className="block text-sm font-medium">
        Due date
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
          className="mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900" />
      </label>
      <NeedsPicker projectId={task.project_id} picked={picked} onChange={setPicked} />
      <ErrorText error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" isDisabled={save.isPending} className="flex-1">Save</Button>
        <Button variant="ghost" onPress={close}>Cancel</Button>
      </div>
    </Form>
  )
}

type ListSummary = { id: string; title: string }
type ListDetail = { id: string; title: string; items: { id: string; text: string; checked: boolean }[] }

/** Pick what the task needs from the project's lists (shopping, parts, ...). */
function NeedsPicker({ projectId, picked, onChange }: { projectId: string; picked: string[]; onChange: (ids: string[]) => void }) {
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => api<ListSummary[]>('GET', `/api/v1/projects/${projectId}/lists`) })
  const details = useQueries({
    queries: (lists.data ?? []).map((l) => ({ queryKey: ['list', l.id], queryFn: () => api<ListDetail>('GET', `/api/v1/lists/${l.id}`) })),
  })
  const toggle = (id: string) => onChange(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id])
  const withItems = details.map((d) => d.data).filter((d): d is ListDetail => !!d && d.items.length > 0)
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Items needed</legend>
      {withItems.length === 0 && <p className="text-sm text-stone-500">Add items to one of this project's lists first, then pick them here.</p>}
      {withItems.map((l) => (
        <div key={l.id}>
          <p className="text-xs font-medium uppercase tracking-wide text-stone-500">{l.title}</p>
          {l.items.map((i) => (
            <label key={i.id} className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={picked.includes(i.id)} onChange={() => toggle(i.id)} className="size-5 accent-brand-600" />
              <span className={i.checked ? 'text-stone-500' : ''}>{i.text}{i.checked && ' (got it)'}</span>
            </label>
          ))}
        </div>
      ))}
    </fieldset>
  )
}
