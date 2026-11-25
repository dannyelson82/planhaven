// The projects list, with each person's own folders (ADR 0022): folders can hold folders (up to
// five levels), a project is in one folder or none. Folders only organize your list; they never
// change who can see a project. Tabs (maintainer, 2026-11-25): Active, Done, Archived, and Trash
// for deleted projects (30 days).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Tab as AriaTab, TabList, TabPanel, Tabs } from 'react-aria-components'
import { api, type Project, stageLabel } from '../api.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { cachedGet } from '../offline.ts'
import { MyChoresLink } from './Chores.tsx'
import { byOrder, type Folder, folderChoices, foldersHolding, folderUrl, type Tab, TABS, tabOf, trail } from '../folders.ts'
import { useRememberedChoice } from '../remember.ts'
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

type Deleted = { kind: string; id: string; title: string; deleted_at: string }

const TAB_LABEL: Record<Tab, string> = { active: 'Active', done: 'Done', archived: 'Archived', trash: 'Trash' }
const DAY = 24 * 60 * 60 * 1000

/** Deleted projects you can bring back, for 30 days after deleting them. */
function ProjectTrash({ deleted, onRestored }: { deleted: Deleted[]; onRestored: () => void }) {
  const client = useQueryClient()
  const restore = useMutation({
    mutationFn: (d: Deleted) => api('POST', `/api/v1/trash/project/${d.id}/restore`),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['trash'] })
      await client.invalidateQueries({ queryKey: ['projects'] })
      onRestored()
    },
  })
  if (deleted.length === 0) return <p className="text-stone-500">No deleted projects. Deleted projects stay here for 30 days.</p>
  return (
    <div className="space-y-3">
      <p className="text-sm text-stone-600 dark:text-stone-400">Deleted projects stay here for 30 days, then they're gone for good. Restoring one brings back everything in it.</p>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Deleted projects">
        {deleted.map((d) => {
          const gone = new Date(new Date(d.deleted_at).getTime() + 30 * DAY)
          return (
            <li key={d.id}>
              <Card className="h-full space-y-2">
                <p className="text-lg font-semibold">{d.title}</p>
                <p className="text-sm text-stone-500">
                  Deleted {new Date(d.deleted_at).toLocaleDateString()} · gone for good after {gone.toLocaleDateString()}
                </p>
                <Button variant="secondary" aria-label={`Restore ${d.title}`} onPress={() => restore.mutate(d)} isDisabled={restore.isPending}>Restore</Button>
              </Card>
            </li>
          )
        })}
      </ul>
      <ErrorText error={restore.error} />
    </div>
  )
}

export function ProjectsScreen({ folderId = null }: { folderId?: string | null }) {
  const refresh = useRefresh()
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => cachedGet<{ items: Project[] }>('/api/v1/projects?limit=200'),
  })
  const trash = useQuery({ queryKey: ['trash'], queryFn: () => api<Deleted[]>('GET', '/api/v1/trash') })
  const folders = useFolders()
  const [tab, setTab] = useRememberedChoice<Tab>('projects-tab', 'active', TABS)
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
  const deleted = (trash.data ?? []).filter((d) => d.kind === 'project')
  // A project whose folder isn't known (yet) shows at the top level, never nowhere.
  const placeOf = (p: Project) => (p.folder_id && byId.has(p.folder_id) ? p.folder_id : null)
  const onTab = (t: Tab) => items.filter((p) => tabOf(p.stage) === t)
  const count = (t: Tab) => (t === 'trash' ? deleted.length : onTab(t).length)
  const inTab = tab === 'trash' ? [] : onTab(tab)
  const shown = inTab.filter((p) => placeOf(p) === folderId)
  // Active shows every folder (a new one is empty); Done and Archived only those holding some.
  const holding = foldersHolding(all, inTab.map(placeOf))
  const subfolders = all
    .filter((f) => f.parent_id === folderId && (tab === 'active' || holding.has(f.id)))
    .sort(byOrder)
  const direct = (id: string) => inTab.filter((p) => placeOf(p) === id).length
  const inProgress = items.filter((p) => p.stage === 'in_progress').length
  const missing = folderId !== null && folders.isSuccess && !here
  const panel = (
    <div className="space-y-4">
      {tab === 'active' && (
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
      )}
      {tab === 'active' && !folderId && inProgress > 3 && (
        <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          You have {inProgress} projects in progress. Finishing one before starting another helps.
        </p>
      )}
      {tab === 'trash' ? (
        <>
          <ErrorText error={trash.error} />
          <ProjectTrash deleted={deleted} onRestored={() => setTab('active')} />
        </>
      ) : (
        <>
          <ErrorText error={projects.error ?? folders.error} />
          {subfolders.length > 0 && (
            <section aria-label="Folders">
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {subfolders.map((f) => {
                  const inner = all.filter((x) => x.parent_id === f.id && (tab === 'active' || holding.has(x.id))).length
                  const n = direct(f.id)
                  return (
                    <li key={f.id}>
                      <Card className="h-full">
                        <Link to={folderUrl(f.id)} className="flex items-center gap-2 text-lg font-semibold">
                          <span className="text-brand-700 dark:text-brand-100"><FolderIcon /></span> {f.name}
                        </Link>
                        <p className="mt-1 text-sm text-stone-500">
                          {n} project{n === 1 ? '' : 's'}
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
          {projects.isSuccess && items.length === 0 && tab === 'active' && (
            <p className="text-stone-500">No projects yet. Add your first idea above.</p>
          )}
          {projects.isSuccess && shown.length === 0 && subfolders.length === 0 && (items.length > 0 || tab !== 'active') && (
            <p className="text-stone-500">
              {tab === 'done' ? 'No done projects here. A project shows here when you set its stage to Done.'
                : tab === 'archived' ? 'No archived projects here. Set a project\'s stage to Archived to put it away.'
                  : here ? 'Nothing in this folder yet. Move projects here with Move to folder.' : 'All your projects are in folders.'}
            </p>
          )}
        </>
      )}
    </div>
  )
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
      {here && tab !== 'trash' && <FolderActions folder={here} folders={all} />}
      <Tabs selectedKey={tab} onSelectionChange={(k) => setTab(k as Tab)}>
        <TabList aria-label="Which projects" className="flex border-b border-stone-200 dark:border-stone-700 sm:gap-1">
          {TABS.map((t) => (
            <AriaTab key={t} id={t}
              className="flex min-h-11 flex-1 cursor-pointer flex-col items-center justify-center border-b-2 border-transparent px-1 py-1.5 text-sm text-stone-600 outline-none data-[selected]:border-brand-600 data-[selected]:font-semibold data-[selected]:text-brand-700 data-[focus-visible]:ring-2 data-[focus-visible]:ring-brand-500 sm:flex-none sm:flex-row sm:gap-1 sm:px-3 dark:text-stone-400 dark:data-[selected]:text-brand-100">
              <span>{TAB_LABEL[t]}</span> <span className="text-xs text-stone-500 sm:text-sm">({count(t)})</span>
            </AriaTab>
          ))}
        </TabList>
        {TABS.map((t) => (
          <TabPanel key={t} id={t} className="pt-4 outline-none">{t === tab ? panel : null}</TabPanel>
        ))}
      </Tabs>
    </div>
  )
}
