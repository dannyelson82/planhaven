// Templates (owner request, 2026-09-28): a list, or a project's tasks, saved to reuse in later
// projects. Private to whoever made it until they share it, one person at a time.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { formatCents } from '../money.ts'
import { cachedGet } from '../offline.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { ShareButton } from './Sharing.tsx'

type Role = 'owner' | 'editor' | 'viewer'
type Template = { id: string; kind: 'list' | 'tasks'; list_kind: string | null; name: string; role: Role | null; item_count: number; version: number }
type TemplateItem = { id: string; text: string; quantity: string | null; unit: string | null; price_cents: number | null; notes: string }
type TemplateDetail = Template & { items: TemplateItem[] }
type Project = { id: string; title: string; role: Role | null }

const KIND_LABEL: Record<string, string> = { shopping: 'Shopping list', parts: 'Parts list', checklist: 'Checklist' }
const describe = (t: Template) => `${t.kind === 'tasks' ? 'Tasks' : KIND_LABEL[t.list_kind ?? ''] ?? 'List'} · ${t.item_count} ${t.kind === 'tasks' ? 'task' : 'item'}${t.item_count === 1 ? '' : 's'}${t.role && t.role !== 'owner' ? ' · shared with you' : ''}`
const select = 'min-h-11 min-w-0 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900'

export function TemplatesScreen() {
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('GET', '/api/v1/templates') })
  const lists = (templates.data ?? []).filter((t) => t.kind === 'list')
  const tasks = (templates.data ?? []).filter((t) => t.kind === 'tasks')
  const group = (title: string, items: Template[]) => (
    <section aria-label={title} className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      {items.length === 0 && <p className="text-sm text-stone-500">None yet.</p>}
      <ul className="grid gap-2 sm:grid-cols-2">
        {items.map((t) => (
          <li key={t.id}>
            <Card>
              <Link to={`/templates/${t.id}`} className="block font-semibold">{t.name}</Link>
              <p className="text-sm text-stone-500">{describe(t)}</p>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  )
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Templates</h1>
      <p className="text-stone-600 dark:text-stone-400">
        Lists and sets of tasks saved to reuse in later projects. Save one from a list (Save as template) or from a
        project's tasks; start from one with + List or + Task on a project. Yours alone until you share it.
      </p>
      {group('Lists', lists)}
      {group('Tasks', tasks)}
      <ErrorText error={templates.error} />
    </div>
  )
}

export function TemplateScreen({ id, myId }: { id: string; myId: string }) {
  const template = useQuery({ queryKey: ['template', id], queryFn: () => api<TemplateDetail>('GET', `/api/v1/templates/${id}`) })
  if (template.error) return <ErrorText error={template.error} />
  if (!template.data) return <p className="text-stone-500">Loading…</p>
  return <TemplateView key={template.data.version} template={template.data} myId={myId} />
}

function TemplateView({ template: t, myId }: { template: TemplateDetail; myId: string }) {
  const client = useQueryClient()
  const canEdit = t.role === 'owner' || t.role === 'editor'
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['template', t.id] }),
    client.invalidateQueries({ queryKey: ['templates'] }),
  ])
  const [name, setName] = useState(t.name)
  const rename = useMutation({
    mutationFn: () => api('PATCH', `/api/v1/templates/${t.id}`, { name: name.trim() }, { 'If-Match': `"${t.version}"` }),
    onSettled: refresh,
  })
  const removeItem = useMutation({ mutationFn: (item: TemplateItem) => api('DELETE', `/api/v1/template-items/${item.id}`), onSettled: refresh })
  const [confirmDelete, setConfirmDelete] = useState(false)
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/templates/${t.id}`),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['templates'] }); navigate('/templates') },
  })
  return (
    <div className="space-y-4">
      <Link to="/templates" className="text-sm text-brand-700 dark:text-brand-100">← All templates</Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t.name}</h1>
        <ShareButton kind="template" id={t.id} isOwner={t.role === 'owner'} myId={myId} />
      </div>
      <p className="text-stone-600 dark:text-stone-400">{describe(t)}</p>
      {canEdit && (
        <Form onSubmit={(e) => { e.preventDefault(); if (name.trim() && name.trim() !== t.name) rename.mutate() }}>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1"><Field label="Template name" maxLength={200} value={name} onChange={setName} /></div>
            <Button type="submit" variant="secondary" isDisabled={!name.trim() || name.trim() === t.name || rename.isPending}>Rename</Button>
          </div>
        </Form>
      )}
      <UseTemplate template={t} />
      <section aria-label="In this template" className="space-y-2">
        <h2 className="text-lg font-semibold">{t.kind === 'tasks' ? 'Tasks' : 'Items'}</h2>
        <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
          {t.items.map((i) => (
            <li key={i.id} className="flex items-center gap-2 px-3 py-2">
              <span className="min-w-0 flex-1">
                <span className="block">{i.text}</span>
                {i.notes && <span className="block truncate text-sm text-stone-500">{i.notes}</span>}
              </span>
              {i.quantity && <span className="text-sm text-stone-500">{String(Number(i.quantity))}{i.unit ? ` ${i.unit}` : ''}</span>}
              {i.price_cents !== null && <span className="text-sm tabular-nums text-stone-500">{formatCents(i.price_cents)} each</span>}
              {canEdit && <Button variant="ghost" aria-label={`Remove ${i.text}`} onPress={() => removeItem.mutate(i)}>✕</Button>}
            </li>
          ))}
        </ul>
      </section>
      {t.role === 'owner' && (
        <Button variant="danger-ghost" isDisabled={remove.isPending} onPress={() => (confirmDelete ? remove.mutate() : setConfirmDelete(true))}>
          {confirmDelete ? 'Tap again to delete this template' : 'Delete this template'}
        </Button>
      )}
      <ErrorText error={rename.error ?? removeItem.error ?? remove.error} />
    </div>
  )
}

/** Use a template in one of your projects (where you can edit). */
function UseTemplate({ template: t }: { template: Template }) {
  // Same query (and cache) as the Projects page.
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => cachedGet<{ items: Project[] }>('/api/v1/projects?limit=200') })
  const editable = (projects.data?.items ?? []).filter((p) => p.role === 'owner' || p.role === 'editor')
  const [projectId, setProjectId] = useState('')
  const use = useTemplate(t)
  return (
    <Card className="space-y-2">
      <h2 className="font-semibold">Use it in a project</h2>
      <div className="flex flex-wrap gap-2">
        <select aria-label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)} className={`${select} flex-1`}>
          <option value="">Choose a project…</option>
          {editable.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
        <Button isDisabled={!projectId || use.isPending} onPress={() => use.mutate(projectId)}>
          {t.kind === 'tasks' ? 'Add these tasks' : 'Make this list'}
        </Button>
      </div>
      <ErrorText error={use.error} />
    </Card>
  )
}

function useTemplate(t: Pick<Template, 'id' | 'kind'>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (projectId: string) => api<{ list_id: string | null }>('POST', `/api/v1/templates/${t.id}/use`, { project_id: projectId })
      .then((r) => ({ ...r, projectId })),
    onSuccess: async ({ list_id, projectId }) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['lists', projectId] }),
        client.invalidateQueries({ queryKey: ['tasks', projectId] }),
        client.invalidateQueries({ queryKey: ['projects'] }),
      ])
      navigate(list_id ? `/lists/${list_id}` : `/projects/${projectId}`)
    },
  })
}

/** In the add bar: start a list, or add tasks, from a template. */
export function FromTemplate({ projectId, kind }: { projectId: string; kind: 'list' | 'tasks' }) {
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('GET', '/api/v1/templates') })
  const mine = (templates.data ?? []).filter((t) => t.kind === kind)
  const [chosen, setChosen] = useState('')
  const use = useTemplate({ id: chosen, kind })
  if (mine.length === 0) return null
  return (
    <div className="space-y-2 border-t border-stone-200 pt-3 dark:border-stone-800">
      <div className="flex flex-wrap gap-2">
        <select aria-label={kind === 'list' ? 'List template' : 'Task template'} value={chosen} onChange={(e) => setChosen(e.target.value)} className={`${select} flex-1`}>
          <option value="">{kind === 'list' ? 'Or start from a template…' : 'Or add tasks from a template…'}</option>
          {mine.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.item_count})</option>)}
        </select>
        <Button variant="secondary" isDisabled={!chosen || use.isPending} onPress={() => use.mutate(projectId)}>Use template</Button>
      </div>
      <ErrorText error={use.error} />
    </div>
  )
}

/** Save as template: a name, then saved (a list with its items; a project's open tasks). */
export function SaveAsTemplate({ path, suggested, label }: { path: string; suggested: string; label: string }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(suggested)
  const save = useMutation({
    mutationFn: () => api<Template>('POST', path, { name: name.trim() }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['templates'] }) },
  })
  if (save.data) {
    return (
      <p role="status" className="text-sm">
        Saved as template “{save.data.name}”. <Link to={`/templates/${save.data.id}`} className="font-medium text-brand-700 dark:text-brand-100">Open</Link>
      </p>
    )
  }
  if (!open) return <Button variant="ghost" onPress={() => setOpen(true)}>{label}</Button>
  return (
    <Form onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate() }}>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1"><Field label="Template name" maxLength={200} value={name} onChange={setName} /></div>
        <Button type="submit" isDisabled={!name.trim() || save.isPending}>Save template</Button>
        <Button variant="ghost" onPress={() => setOpen(false)}>Cancel</Button>
      </div>
      <ErrorText error={save.error} />
    </Form>
  )
}
