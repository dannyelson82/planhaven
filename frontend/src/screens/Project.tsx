import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Checkbox, ListBox, ListBoxItem, Popover, Select, SelectValue, Button as AriaButton, Label } from 'react-aria-components'
import { api, type Project, STAGES, type Stage, type Task } from '../api.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Form } from '../ui.tsx'

export function ProjectScreen({ id }: { id: string }) {
  const client = useQueryClient()
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api<Project>('GET', `/api/v1/projects/${id}`) })
  const tasks = useQuery({ queryKey: ['tasks', id], queryFn: () => api<Task[]>('GET', `/api/v1/projects/${id}/tasks`) })
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['project', id] }),
    client.invalidateQueries({ queryKey: ['tasks', id] }),
    client.invalidateQueries({ queryKey: ['projects'] }),
  ])
  const [title, setTitle] = useState('')
  const addTask = useMutation({
    mutationFn: () => api('POST', `/api/v1/projects/${id}/tasks`, { title }),
    onSuccess: async () => { setTitle(''); await refresh() },
  })
  const toggle = useMutation({
    mutationFn: (t: Task) => api('PATCH', `/api/v1/tasks/${t.id}`, { done: !t.done }, { 'If-Match': `"${t.version}"` }),
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: (t: Task) => api('DELETE', `/api/v1/tasks/${t.id}`),
    onSettled: refresh,
  })
  const setStage = useMutation({
    mutationFn: (stage: Stage) => api('PATCH', `/api/v1/projects/${id}`, { stage }, { 'If-Match': `"${project.data?.version}"` }),
    onSettled: refresh,
  })
  const deleteProject = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/projects/${id}`),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['projects'] }); navigate('/projects') },
  })

  if (project.error) return <ErrorText error={project.error} />
  if (!project.data) return <p className="text-stone-500">Loading…</p>
  const p = project.data
  const canEdit = p.role === 'owner' || p.role === 'editor'
  const open = (tasks.data ?? []).filter((t) => !t.done)
  const done = (tasks.data ?? []).filter((t) => t.done)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{p.title}</h1>
        <Select
          aria-label="Stage"
          selectedKey={p.stage}
          onSelectionChange={(key) => setStage.mutate(key as Stage)}
          isDisabled={!canEdit || setStage.isPending}
        >
          <Label className="sr-only">Stage</Label>
          <AriaButton className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-brand-100 px-4 font-medium text-brand-700 dark:bg-stone-800 dark:text-brand-100">
            <SelectValue /> <span aria-hidden>▾</span>
          </AriaButton>
          <Popover className="rounded-xl bg-white p-1 shadow-lg ring-1 ring-stone-200 dark:bg-stone-900 dark:ring-stone-700">
            <ListBox className="outline-none">
              {STAGES.map((s) => (
                <ListBoxItem key={s.id} id={s.id} className="min-h-11 cursor-default rounded-lg px-3 py-2 outline-none focus:bg-stone-100 selected:font-semibold dark:focus:bg-stone-800">
                  {s.label}
                </ListBoxItem>
              ))}
            </ListBox>
          </Popover>
        </Select>
      </div>
      {p.description && <p className="whitespace-pre-wrap text-stone-700 dark:text-stone-300">{p.description}</p>}
      <ErrorText error={setStage.error ?? toggle.error ?? remove.error ?? tasks.error} />

      {canEdit && (
        <Card>
          <Form onSubmit={(e) => { e.preventDefault(); addTask.mutate() }}>
            <Field label="Add a task" isRequired maxLength={300} value={title} onChange={setTitle} />
            <ErrorText error={addTask.error} />
            <Button type="submit" isDisabled={addTask.isPending}>Add</Button>
          </Form>
        </Card>
      )}

      <section aria-label="Open tasks" className="space-y-2">
        {open.length > 0 && (
          <p className="text-sm font-medium text-brand-700 dark:text-brand-100">Next small step: {open[0].title}</p>
        )}
        <TaskList tasks={open} canEdit={canEdit} onToggle={(t) => toggle.mutate(t)} onDelete={(t) => remove.mutate(t)} />
        {tasks.isSuccess && open.length === 0 && <p className="text-stone-500">Nothing open. Nice!</p>}
      </section>
      {done.length > 0 && (
        <details className="rounded-2xl">
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium text-stone-500">Done ({done.length})</summary>
          <TaskList tasks={done} canEdit={canEdit} onToggle={(t) => toggle.mutate(t)} onDelete={(t) => remove.mutate(t)} />
        </details>
      )}
      {p.role === 'owner' && (
        <Button variant="danger-ghost" onPress={() => { if (window.confirm('Delete this project?')) deleteProject.mutate() }}>
          Delete project
        </Button>
      )}
    </div>
  )
}

function TaskList({ tasks, canEdit, onToggle, onDelete }: {
  tasks: Task[]
  canEdit: boolean
  onToggle: (t: Task) => void
  onDelete: (t: Task) => void
}) {
  return (
    <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
      {tasks.map((t) => (
        <li key={t.id} className="flex items-center gap-3 px-3">
          <Checkbox
            isSelected={t.done}
            isDisabled={!canEdit}
            onChange={() => onToggle(t)}
            className="group flex min-h-12 flex-1 items-center gap-3"
          >
            <span aria-hidden className="flex size-6 shrink-0 items-center justify-center rounded-md border-2 border-stone-400 group-selected:border-brand-600 group-selected:bg-brand-600 group-selected:text-white">
              {t.done ? '✓' : ''}
            </span>
            <span className={t.done ? 'text-stone-500 line-through' : ''}>{t.title}</span>
            {t.due_at && (
              <span className="ml-auto text-xs text-stone-500">
                {new Date(t.due_at).toLocaleDateString(undefined, t.due_all_day ? { timeZone: 'UTC' } : {})}
              </span>
            )}
          </Checkbox>
          {canEdit && (
            <Button variant="ghost" aria-label={`Delete ${t.title}`} onPress={() => onDelete(t)}>✕</Button>
          )}
        </li>
      ))}
    </ul>
  )
}
