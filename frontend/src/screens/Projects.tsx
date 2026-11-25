// The projects list, with each person's own folders (ADR 0022): folders can hold folders (up to
// five levels), a project is in one folder or none. Folders only organize your list; they never
// change who can see a project.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Project, stageLabel } from '../api.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { cachedGet } from '../offline.ts'
import { MyChoresLink } from './Chores.tsx'
import { byOrder, type Folder, folderChoices, folderUrl, trail } from '../folders.ts'
import { FolderIcon } from '../icons.tsx'

function useFolders() {
  return useQuery({ queryKey: ['folders'], queryFn: () => cachedGet<Folder[]>('/api/v1/folders') })
}

function useRefresh() {
  const client = useQueryClient()
  return async () => {
    await client.invalidateQueries({ queryKey: ['folders'] })
    await client.invalidateQueries({ queryKey: ['projects'] })
  }
}

const select = 'mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900'

function MoveProject({ project, folders }: { project: Project; folders: Folder[] }) {
  const refresh = useRefresh()
  const [open, setOpen] = useState(false)
  const move = useMutation({
    mutationFn: (folderId: string | null) => api('PUT', `/api/v1/projects/${project.id}/folder`, { folder_id: folderId }),
    onSuccess: () => setOpen(false),
    onSettled: refresh,
  })
  if (!open)
    return <Button variant="ghost" aria-label={`Move ${project.title} to a folder`} onPress={() => setOpen(true)}>Move to folder</Button>
  return (
    <div className="mt-2">
      <label className="text-sm font-medium" htmlFor={`folder-${project.id}`}>Folder for {project.title}</label>
      <select id={`folder-${project.id}`} className={select} value={project.folder_id ?? ''} disabled={move.isPending}
        onChange={(e) => move.mutate(e.target.value || null)}>
        <option value="">Not in a folder</option>
        {folderChoices(folders).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>
      <ErrorText error={move.error} />
      <Button variant="ghost" onPress={() => setOpen(false)}>Done</Button>
    </div>
  )
}

/** Rename, move or delete the folder you're in. */
function FolderActions({ folder, folders }: { folder: Folder; folders: Folder[] }) {
  const refresh = useRefresh()
  const [mode, setMode] = useState<'none' | 'rename' | 'move' | 'delete'>('none')
  const [name, setName] = useState(folder.name)
  const save = useMutation({
    mutationFn: (body: { name?: string; parent_id?: string | null }) => api('PATCH', `/api/v1/folders/${folder.id}`, body),
    onSuccess: () => setMode('none'),
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/folders/${folder.id}`),
    onSuccess: async () => {
      await refresh()
      navigate(folderUrl(folder.parent_id))
    },
  })
  return (
    <div className="space-y-2">
      {mode === 'none' && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onPress={() => { setName(folder.name); setMode('rename') }}>Rename</Button>
          <Button variant="secondary" onPress={() => setMode('move')}>Move folder</Button>
          <Button variant="danger-ghost" onPress={() => setMode('delete')}>Delete folder</Button>
        </div>
      )}
      {mode === 'rename' && (
        <Form onSubmit={(e) => { e.preventDefault(); save.mutate({ name }) }}>
          <Field label="Folder name" isRequired maxLength={100} value={name} onChange={setName} autoFocus />
          <div className="flex gap-2">
            <Button type="submit" isDisabled={save.isPending}>Save</Button>
            <Button variant="ghost" onPress={() => setMode('none')}>Cancel</Button>
          </div>
        </Form>
      )}
      {mode === 'move' && (
        <div>
          <label className="text-sm font-medium" htmlFor="folder-parent">Put {folder.name} in</label>
          <select id="folder-parent" className={select} value={folder.parent_id ?? ''} disabled={save.isPending}
            onChange={(e) => save.mutate({ parent_id: e.target.value || null })}>
            <option value="">Projects (top level)</option>
            {folderChoices(folders, folder.id).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <Button variant="ghost" onPress={() => setMode('none')}>Cancel</Button>
        </div>
      )}
      {mode === 'delete' && (
        <div className="space-y-2 rounded-xl border border-red-200 p-3 dark:border-red-900">
          <p className="text-sm">Delete the folder “{folder.name}”? Its projects and folders move up a level. No project is deleted.</p>
          <div className="flex gap-2">
            <Button variant="danger-ghost" onPress={() => remove.mutate()} isDisabled={remove.isPending}>Delete folder</Button>
            <Button variant="ghost" onPress={() => setMode('none')}>Cancel</Button>
          </div>
        </div>
      )}
      <ErrorText error={save.error ?? remove.error} />
    </div>
  )
}

export function ProjectsScreen({ folderId = null }: { folderId?: string | null }) {
  const refresh = useRefresh()
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => cachedGet<{ items: Project[] }>('/api/v1/projects?limit=200'),
  })
  const folders = useFolders()
  const all = folders.data ?? []
  const byId = new Map(all.map((f) => [f.id, f]))
  const here = folderId ? byId.get(folderId) : undefined
  const path = trail(byId, folderId)
  const [title, setTitle] = useState('')
  const [folderName, setFolderName] = useState('')
  const create = useMutation({
    mutationFn: async () => {
      const p = await api<Project>('POST', '/api/v1/projects', { title })
      if (folderId) await api('PUT', `/api/v1/projects/${p.id}/folder`, { folder_id: folderId })
      return p
    },
    onSuccess: async (p) => {
      setTitle('')
      await refresh()
      navigate(`/projects/${p.id}`)
    },
  })
  const addFolder = useMutation({
    mutationFn: () => api<Folder>('POST', '/api/v1/folders', { name: folderName, parent_id: folderId }),
    onSuccess: async () => {
      setFolderName('')
      await refresh()
    },
  })
  const items = projects.data?.items ?? []
  // A project whose folder isn't known (yet) shows at the top level, never nowhere.
  const placeOf = (p: Project) => (p.folder_id && byId.has(p.folder_id) ? p.folder_id : null)
  const shown = items.filter((p) => placeOf(p) === folderId)
  const subfolders = all.filter((f) => f.parent_id === folderId).sort(byOrder)
  const inProgress = items.filter((p) => p.stage === 'in_progress').length
  const missing = folderId !== null && folders.isSuccess && !here
  return (
    <div className="space-y-4">
      {path.length > 0 && (
        <nav aria-label="Folder path" className="flex flex-wrap items-center gap-1 text-sm">
          <Link to="/projects" className="text-brand-700 underline dark:text-brand-100">Projects</Link>
          {path.slice(0, -1).map((f) => (
            <span key={f.id}> › <Link to={folderUrl(f.id)} className="text-brand-700 underline dark:text-brand-100">{f.name}</Link></span>
          ))}
        </nav>
      )}
      <h1 className="text-2xl font-bold">{here ? here.name : 'Projects'}</h1>
      {missing && (
        <p className="text-stone-500">This folder isn't there any more. <Link to="/projects" className="underline">Go to projects</Link></p>
      )}
      {!folderId && <MyChoresLink />}
      {here && <FolderActions folder={here} folders={all} />}
      <Card className="space-y-4">
        <Form onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
          <Field label={here ? `New project in ${here.name}` : 'New project'} isRequired maxLength={200} value={title} onChange={setTitle} />
          <ErrorText error={create.error} />
          <Button type="submit" isDisabled={create.isPending}>Add project</Button>
        </Form>
        <Form onSubmit={(e) => { e.preventDefault(); addFolder.mutate() }}>
          <Field label={here ? `New folder in ${here.name}` : 'New folder'} isRequired maxLength={100} value={folderName} onChange={setFolderName} />
          <ErrorText error={addFolder.error} />
          <Button type="submit" variant="secondary" isDisabled={addFolder.isPending}>Add folder</Button>
        </Form>
      </Card>
      {!folderId && inProgress > 3 && (
        <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          You have {inProgress} projects in progress. Finishing one before starting another helps.
        </p>
      )}
      <ErrorText error={projects.error ?? folders.error} />
      {subfolders.length > 0 && (
        <section aria-label="Folders">
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {subfolders.map((f) => {
              const inner = all.filter((x) => x.parent_id === f.id).length
              return (
                <li key={f.id}>
                  <Card className="h-full">
                    <Link to={folderUrl(f.id)} className="flex items-center gap-2 text-lg font-semibold">
                      <span className="text-brand-700 dark:text-brand-100"><FolderIcon /></span> {f.name}
                    </Link>
                    <p className="mt-1 text-sm text-stone-500">
                      {f.projects} project{f.projects === 1 ? '' : 's'}
                      {inner > 0 && ` · ${inner} folder${inner === 1 ? '' : 's'}`}
                    </p>
                  </Card>
                </li>
              )
            })}
          </ul>
        </section>
      )}
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label={here ? `Projects in ${here.name}` : 'Projects'}>
        {shown.map((p) => (
          <li key={p.id}>
            <Card className="h-full">
              <Link to={`/projects/${p.id}`} className="block text-lg font-semibold">{p.title}</Link>
              <p className="mt-1 text-sm text-stone-500">
                {stageLabel(p.stage)} · {p.open_tasks} open task{p.open_tasks === 1 ? '' : 's'}
                {p.role !== 'owner' && ` · ${p.role}`}
              </p>
              {all.length > 0 && <MoveProject project={p} folders={all} />}
            </Card>
          </li>
        ))}
      </ul>
      {projects.isSuccess && items.length === 0 && (
        <p className="text-stone-500">No projects yet. Add your first idea above.</p>
      )}
      {projects.isSuccess && items.length > 0 && shown.length === 0 && subfolders.length === 0 && (
        <p className="text-stone-500">{here ? 'Nothing in this folder yet. Move projects here with Move to folder.' : 'All your projects are in folders.'}</p>
      )}
    </div>
  )
}
