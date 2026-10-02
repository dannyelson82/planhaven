import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { Button as AriaButton, Dialog, DialogTrigger, Heading, Modal } from 'react-aria-components'
import { api, ApiError, dueLabel, type Need, type Task } from '../api.ts'
import { Button, ErrorText, Field, Form } from '../ui.tsx'
import { ChoreForm } from './Chores.tsx'
import { repeatText } from '../chores.ts'

/**
 * A task on the project page: tapping it opens its details (notes, due date, the items it
 * needs), with Edit from there (owner request, 2026-10-02). The checkbox beside it ticks it.
 */
export function TaskDetails({ task, needs, canEdit, myId, summary }: { task: Task; needs: Need[]; canEdit: boolean; myId: string; summary: ReactNode }) {
  const [editing, setEditing] = useState<false | 'task' | 'chore'>(false)
  return (
    <DialogTrigger onOpenChange={(open) => { if (!open) setEditing(false) }}>
      <AriaButton aria-label={`Details: ${task.title}`} className="min-h-12 min-w-0 flex-1 cursor-pointer py-2 text-left outline-none data-[focus-visible]:ring-2 data-[focus-visible]:ring-brand-600">
        {summary}
      </AriaButton>
      <Modal isDismissable className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 sm:items-center">
        <Dialog className="max-h-[85dvh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
          {({ close }) => editing === 'task'
            ? <EditForm task={task} needs={needs} close={() => setEditing(false)} />
            : editing === 'chore'
              ? <ChoreForm task={task} myId={myId} done={() => setEditing(false)} />
              : <TaskView task={task} needs={needs} canEdit={canEdit} onEdit={() => setEditing('task')} onChore={() => setEditing('chore')} close={close} />}
        </Dialog>
      </Modal>
    </DialogTrigger>
  )
}

function TaskView({ task, needs, canEdit, onEdit, onChore, close }: {
  task: Task; needs: Need[]; canEdit: boolean; onEdit: () => void; onChore: () => void; close: () => void
}) {
  const due = dueLabel(task, true)
  return (
    <div className="space-y-4">
      <Heading slot="title" className={`text-lg font-semibold ${task.done ? 'text-stone-500 line-through' : ''}`}>{task.title}</Heading>
      <dl className="space-y-3 text-sm">
        <div>
          <dt className="font-medium text-stone-500">Due</dt>
          <dd>{due ?? 'No due date'}</dd>
        </div>
        <div>
          <dt className="font-medium text-stone-500">Status</dt>
          <dd>{task.done ? 'Done' : 'Open'}</dd>
        </div>
        {task.assignee_id && (
          <div>
            <dt className="font-medium text-stone-500">Chore</dt>
            <dd>{[repeatText({ repeat_freq: task.repeat_freq ?? null, repeat_interval: task.repeat_interval ?? 1, repeat_days: task.repeat_days ?? null }) ?? 'Once',
              task.proof === 'photo' ? 'with a photo' : task.proof === 'note' ? 'with a note' : null,
              task.waiting ? 'waiting for approval' : null].filter(Boolean).join(', ')}</dd>
          </div>
        )}
        <div>
          <dt className="font-medium text-stone-500">Notes</dt>
          <dd className="whitespace-pre-wrap">{task.notes || 'No notes'}</dd>
        </div>
        <div>
          <dt className="font-medium text-stone-500">Items needed</dt>
          <dd>
            {needs.length === 0 ? 'None' : (
              <ul>
                {needs.map((n) => (
                  <li key={n.list_item_id} className={n.checked ? 'text-stone-500' : ''}>
                    {n.checked ? '✓' : '•'} {n.text}{n.quantity ? ` (${String(Number(n.quantity))}${n.unit ? ` ${n.unit}` : ''})` : ''}
                    <span className="text-stone-500"> · {n.list_title}{n.checked ? ', got it' : ''}</span>
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
      <div className="flex gap-2">
        {canEdit && <Button onPress={onEdit} className="flex-1">Edit</Button>}
        {canEdit && <Button variant="secondary" onPress={onChore}>Chore</Button>}
        <Button variant={canEdit ? 'ghost' : 'primary'} onPress={close} className={canEdit ? '' : 'flex-1'}>Close</Button>
      </div>
    </div>
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
    // Only what changed, with what it held before ("merge when safe", owner decision
    // 2026-10-02): a change made meanwhile to other fields is kept, not refused. After a
    // conflict, "Keep mine" (force) saves over the newest copy.
    mutationFn: async (force: boolean) => {
      const was = task.due_at ? task.due_at.slice(0, 10) : ''
      const changed: Record<string, unknown> = {}
      const base: Record<string, unknown> = {}
      if (title !== task.title) { changed.title = title; base.title = task.title }
      if (notes !== task.notes) { changed.notes = notes; base.notes = task.notes }
      if (due !== was) {
        Object.assign(changed, { due_at: due ? `${due}T00:00:00Z` : null, due_all_day: !!due })
        Object.assign(base, { due_at: task.due_at, due_all_day: task.due_all_day })
      }
      if (Object.keys(changed).length) {
        const version = force ? (await api<Task[]>('GET', `/api/v1/projects/${task.project_id}/tasks`)).find((t) => t.id === task.id)?.version : task.version
        await api('PATCH', `/api/v1/tasks/${task.id}`, { ...changed, ...(force ? {} : { base }) }, { 'If-Match': `"${version ?? task.version}"` })
      }
      if (needsChanged) await api('PUT', `/api/v1/tasks/${task.id}/needs`, { item_ids: picked })
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['tasks', task.project_id] }),
        client.invalidateQueries({ queryKey: ['task-needs', task.project_id] }),
      ])
      close()
    },
  })
  const conflict = save.error instanceof ApiError && save.error.status === 409
  return (
    <Form onSubmit={(e) => { e.preventDefault(); save.mutate(false) }}>
      <Heading slot="title" className="text-lg font-semibold">Edit task</Heading>
      <Field label="Title" isRequired maxLength={300} value={title} onChange={setTitle} />
      <Field label="Notes" multiline maxLength={20000} value={notes} onChange={setNotes} />
      <label className="block text-sm font-medium">
        Due date
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
          className="mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900" />
      </label>
      <NeedsPicker projectId={task.project_id} picked={picked} onChange={setPicked} />
      {conflict ? (
        <div role="alert" className="space-y-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <p>Someone changed the same thing on this task (maybe you, on another device) while you were editing.</p>
          <div className="flex flex-wrap gap-2">
            <Button onPress={() => save.mutate(true)} isDisabled={save.isPending}>Keep mine</Button>
            <Button variant="secondary" onPress={async () => { await client.invalidateQueries({ queryKey: ['tasks', task.project_id] }); close() }}>Keep theirs</Button>
          </div>
        </div>
      ) : <ErrorText error={save.error} />}
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
