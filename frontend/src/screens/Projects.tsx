import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Project, stageLabel } from '../api.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'

export function ProjectsScreen() {
  const client = useQueryClient()
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api<{ items: Project[] }>('GET', '/api/v1/projects?limit=200'),
  })
  const [title, setTitle] = useState('')
  const create = useMutation({
    mutationFn: () => api<Project>('POST', '/api/v1/projects', { title }),
    onSuccess: async (p) => {
      setTitle('')
      await client.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${p.id}`)
    },
  })
  const items = projects.data?.items ?? []
  const inProgress = items.filter((p) => p.stage === 'in_progress').length
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Projects</h1>
      <Card>
        <Form onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
          <Field label="New project" isRequired maxLength={200} value={title} onChange={setTitle} />
          <ErrorText error={create.error} />
          <Button type="submit" isDisabled={create.isPending}>Add project</Button>
        </Form>
      </Card>
      {inProgress > 3 && (
        <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          You have {inProgress} projects in progress. Finishing one before starting another helps.
        </p>
      )}
      <ErrorText error={projects.error} />
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((p) => (
          <li key={p.id}>
            <Card className="h-full">
              <Link to={`/projects/${p.id}`} className="block text-lg font-semibold">{p.title}</Link>
              <p className="mt-1 text-sm text-stone-500">
                {stageLabel(p.stage)} · {p.open_tasks} open task{p.open_tasks === 1 ? '' : 's'}
                {p.role !== 'owner' && ` · ${p.role}`}
              </p>
            </Card>
          </li>
        ))}
      </ul>
      {projects.isSuccess && items.length === 0 && (
        <p className="text-stone-500">No projects yet. Add your first idea above.</p>
      )}
    </div>
  )
}
