import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Dialog, DialogTrigger, Heading, Modal } from 'react-aria-components'
import { api, type Task } from '../api.ts'
import { Button, ErrorText, Field, Form } from '../ui.tsx'

/** Edit a task's title, notes and due date. */
export function TaskEditor({ task }: { task: Task }) {
  return (
    <DialogTrigger>
      <Button variant="ghost" aria-label={`Edit ${task.title}`}>✎</Button>
      <Modal isDismissable className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 sm:items-center">
        <Dialog className="w-full max-w-md rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
          {({ close }) => <EditForm task={task} close={close} />}
        </Dialog>
      </Modal>
    </DialogTrigger>
  )
}

function EditForm({ task, close }: { task: Task; close: () => void }) {
  const client = useQueryClient()
  const [title, setTitle] = useState(task.title)
  const [notes, setNotes] = useState(task.notes)
  const [due, setDue] = useState(task.due_at ? task.due_at.slice(0, 10) : '')
  const save = useMutation({
    mutationFn: () =>
      api('PATCH', `/api/v1/tasks/${task.id}`, {
        title, notes,
        due_at: due ? `${due}T00:00:00Z` : null,
        due_all_day: !!due,
      }, { 'If-Match': `"${task.version}"` }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['tasks', task.project_id] })
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
      <ErrorText error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" isDisabled={save.isPending} className="flex-1">Save</Button>
        <Button variant="ghost" onPress={close}>Cancel</Button>
      </div>
    </Form>
  )
}
