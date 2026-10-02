import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, stageLabel, uploadFile } from '../api.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'
import { ShareButton } from './Sharing.tsx'
import { AssetService } from './AssetService.tsx'

type AssetKind = 'vehicle' | 'boat' | 'house' | 'property' | 'equipment' | 'tool' | 'other'
type Detail = { label: string; value: string }
type Asset = {
  id: string
  name: string
  kind: AssetKind
  details: Detail[]
  notes: string
  role: 'owner' | 'editor' | 'viewer' | null
  projects: number
  version: number
  has_photo: boolean
  history?: { id: string; title: string; stage: string; updated_at: string }[] | null
}

const KIND_LABEL: Record<AssetKind, string> = {
  vehicle: 'Vehicle',
  boat: 'Boat',
  house: 'House',
  property: 'Property',
  equipment: 'Equipment',
  tool: 'Tool',
  other: 'Other',
}

// Suggested details per kind, so a new asset starts with useful blanks.
const SUGGESTED: Partial<Record<AssetKind, string[]>> = {
  vehicle: ['Make and model', 'Year', 'VIN', 'Plate', 'Mileage'],
  boat: ['Make and model', 'Year', 'Hull ID', 'Engine', 'Engine hours'],
  house: ['Address', 'Year built', 'Furnace', 'Water heater'],
  equipment: ['Make and model', 'Serial number', 'Purchased'],
  tool: ['Make and model', 'Serial number'],
}

const select = 'min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900'

function KindSelect({ value, onChange }: { value: AssetKind; onChange: (k: AssetKind) => void }) {
  return (
    <select aria-label="Kind" value={value} onChange={(e) => onChange(e.target.value as AssetKind)} className={select}>
      {(Object.keys(KIND_LABEL) as AssetKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
    </select>
  )
}

/** Everything the household owns and looks after. */
export function AssetsScreen() {
  const assets = useQuery({ queryKey: ['assets'], queryFn: () => api<Asset[]>('GET', '/api/v1/assets') })
  const [name, setName] = useState('')
  const [kind, setKind] = useState<AssetKind>('vehicle')
  const create = useMutation({
    mutationFn: () => api<Asset>('POST', '/api/v1/assets', {
      name, kind, details: (SUGGESTED[kind] ?? []).map((label) => ({ label, value: '' })),
    }),
    onSuccess: (a) => navigate(`/assets/${a.id}`),
  })
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Assets</h1>
      <p className="text-stone-600 dark:text-stone-400">Vehicles, boats, the house: the things your projects are about. Each keeps its own service history.</p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {(assets.data ?? []).map((a) => (
          <li key={a.id}>
            <Card className="flex items-center gap-3">
              {/* No photo: nothing, rather than a placeholder. */}
              {a.has_photo && (
                <img src={`/api/v1/assets/${a.id}/photo/thumbnail?v=${a.version}`} alt="" loading="lazy"
                  className="size-16 shrink-0 rounded-xl bg-stone-200 object-cover dark:bg-stone-800" />
              )}
              <span className="min-w-0">
                <Link to={`/assets/${a.id}`} className="block truncate font-semibold">{a.name}</Link>
                <span className="block text-sm text-stone-500">{KIND_LABEL[a.kind]} · {a.projects === 1 ? '1 project' : `${a.projects} projects`}</span>
              </span>
            </Card>
          </li>
        ))}
      </ul>
      {assets.data?.length === 0 && <p className="text-sm text-stone-500">No assets yet.</p>}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate() }}>
        <div className="min-w-0 flex-1"><Field label="New asset" maxLength={200} value={name} onChange={setName} /></div>
        <KindSelect value={kind} onChange={setKind} />
        <Button type="submit" variant="secondary" isDisabled={create.isPending}>Add asset</Button>
      </form>
      <ErrorText error={create.error ?? assets.error} />
    </div>
  )
}

/** One asset: details, notes, sharing and its projects (service history). */
export function AssetScreen({ id, myId }: { id: string; myId: string }) {
  const asset = useQuery({ queryKey: ['asset', id], queryFn: () => api<Asset>('GET', `/api/v1/assets/${id}`) })
  if (asset.error) return <ErrorText error={asset.error} />
  if (!asset.data) return <p className="text-stone-500">Loading…</p>
  const a = asset.data
  return (
    <div className="space-y-4">
      <Link to="/assets" className="text-sm text-brand-700 dark:text-brand-100">← All assets</Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{a.name}</h1>
        <ShareButton kind="asset" id={a.id} isOwner={a.role === 'owner'} myId={myId} />
      </div>
      {/* Outside the keyed form, so a photo picked while the form refreshes isn't lost. */}
      <AssetPhoto asset={a} canEdit={a.role === 'owner' || a.role === 'editor'} />
      {/* key: start the form over when the asset changes on the server. */}
      <AssetDetail key={a.version} asset={a} />
      <AssetService assetId={a.id} />
    </div>
  )
}

function AssetDetail({ asset }: { asset: Asset }) {
  const client = useQueryClient()
  const canEdit = asset.role === 'owner' || asset.role === 'editor'
  const [name, setName] = useState(asset.name)
  const [kind, setKind] = useState<AssetKind>(asset.kind)
  const [details, setDetails] = useState<Detail[]>(asset.details)
  const [notes, setNotes] = useState(asset.notes)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const dirty = name !== asset.name || kind !== asset.kind || notes !== asset.notes || JSON.stringify(details) !== JSON.stringify(asset.details)
  const save = useMutation({
    mutationFn: () => api('PUT', `/api/v1/assets/${asset.id}`, {
      name, kind, notes, details: details.filter((d) => d.label.trim()).map((d) => ({ label: d.label.trim(), value: d.value })),
    }, { 'If-Match': `"${asset.version}"` }),
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: ['asset', asset.id] }), client.invalidateQueries({ queryKey: ['assets'] })]),
  })
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/assets/${asset.id}`),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['assets'] }); navigate('/assets') },
  })
  const setDetail = (i: number, part: Partial<Detail>) => setDetails(details.map((d, j) => (j === i ? { ...d, ...part } : d)))
  const input = 'block w-full min-w-0 rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900'

  return (
    <div className="space-y-4">

      <Card className="space-y-3">
        {canEdit ? (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-0 flex-1"><Field label="Name" isRequired maxLength={200} value={name} onChange={setName} /></div>
              <KindSelect value={kind} onChange={setKind} />
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Details</legend>
              {details.map((d, i) => (
                // eslint-disable-next-line react/no-array-index-key -- rows have no identity of their own
                <div key={i} className="flex items-end gap-1">
                  {/* The detail's name reads like a field label but can be edited. */}
                  <div className="min-w-0 flex-1">
                    <input aria-label={`Detail ${i + 1} name`} placeholder="Name" maxLength={60} value={d.label} onChange={(e) => setDetail(i, { label: e.target.value })}
                      className="block w-full min-w-0 rounded-md bg-transparent px-1 py-1 text-sm font-medium text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800" />
                    <input aria-label={d.label || `Detail ${i + 1}`} maxLength={500} value={d.value} onChange={(e) => setDetail(i, { value: e.target.value })} className={input} />
                  </div>
                  <Button variant="ghost" aria-label={`Remove ${d.label || 'detail'}`} onPress={() => setDetails(details.filter((_, j) => j !== i))}>✕</Button>
                </div>
              ))}
              {details.length < 40 && (
                <Button variant="ghost" onPress={() => setDetails([...details, { label: '', value: '' }])}>+ Add a detail</Button>
              )}
            </fieldset>
            <Field label="Notes" multiline maxLength={20000} value={notes} onChange={setNotes} />
            <div className="flex flex-wrap gap-2">
              <Button onPress={() => save.mutate()} isDisabled={!dirty || !name.trim() || save.isPending}>Save</Button>
              {asset.role === 'owner' && (
                <Button variant="danger-ghost" onPress={() => (confirmDelete ? remove.mutate() : setConfirmDelete(true))} isDisabled={remove.isPending}>
                  {confirmDelete ? 'Tap again to delete this asset' : 'Delete asset'}
                </Button>
              )}
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-stone-500">{KIND_LABEL[asset.kind]}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              {asset.details.filter((d) => d.value).map((d) => (
                <div key={d.label} className="contents">
                  <dt className="text-stone-500">{d.label}</dt>
                  <dd className="break-words">{d.value}</dd>
                </div>
              ))}
            </dl>
            {asset.notes && <p className="whitespace-pre-wrap">{asset.notes}</p>}
          </>
        )}
        <ErrorText error={save.error ?? remove.error} />
      </Card>

      <section aria-label="Projects for this asset" className="space-y-2">
        <h2 className="text-lg font-semibold">Projects</h2>
        {(asset.history ?? []).length === 0 && <p className="text-sm text-stone-500">No projects for this yet. Link one from a project page.</p>}
        <ul className="space-y-2">
          {(asset.history ?? []).map((p) => (
            <li key={p.id}>
              <Card className="flex items-center justify-between gap-2 py-3">
                <Link to={`/projects/${p.id}`} className="min-w-0 truncate font-medium">{p.title}</Link>
                <span className="shrink-0 text-sm text-stone-500">{stageLabel(p.stage)} · {new Date(p.updated_at).toLocaleDateString()}</span>
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

/** On a project page: which asset the project is for; editors can change it. */
export function ProjectAssetPicker({ projectId, assetId, assetName, canEdit }: {
  projectId: string; assetId: string | null; assetName: string | null; canEdit: boolean
}) {
  const client = useQueryClient()
  const assets = useQuery({ queryKey: ['assets'], queryFn: () => api<Asset[]>('GET', '/api/v1/assets'), enabled: canEdit })
  const link = useMutation({
    mutationFn: (id: string | null) => api('PUT', `/api/v1/projects/${projectId}/asset`, { asset_id: id }),
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: ['project', projectId] }), client.invalidateQueries({ queryKey: ['assets'] })]),
  })
  if (!canEdit) {
    return assetId ? <p className="text-sm text-stone-600 dark:text-stone-400">For <Link to={`/assets/${assetId}`} className="font-medium text-brand-700 dark:text-brand-100">{assetName}</Link></p> : null
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <label htmlFor="project-asset" className="text-stone-600 dark:text-stone-400">For</label>
      <select id="project-asset" className={select} value={assetId ?? ''} onChange={(e) => link.mutate(e.target.value || null)} disabled={link.isPending}>
        <option value="">No asset</option>
        {/* Keep showing a linked asset even if it isn't in the list yet. */}
        {assetId && !(assets.data ?? []).some((a) => a.id === assetId) && <option value={assetId}>{assetName}</option>}
        {(assets.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
      {assetId && <Link to={`/assets/${assetId}`} className="text-brand-700 dark:text-brand-100">Open</Link>}
      <ErrorText error={link.error} />
    </div>
  )
}

/** The asset's photo: shown large on its page and small on its card. */
function AssetPhoto({ asset, canEdit }: { asset: Asset; canEdit: boolean }) {
  const client = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['asset', asset.id] }),
    client.invalidateQueries({ queryKey: ['assets'] }),
  ])
  const upload = useMutation({ mutationFn: (file: File) => uploadFile(`/api/v1/assets/${asset.id}/photo`, file, 'PUT'), onSettled: refresh })
  const remove = useMutation({ mutationFn: () => api('DELETE', `/api/v1/assets/${asset.id}/photo`), onSettled: refresh })
  if (!asset.has_photo && !canEdit) return null
  return (
    <div className="space-y-2">
      {asset.has_photo && (
        <img src={`/api/v1/assets/${asset.id}/photo?v=${asset.version}`} alt={asset.name}
          className="max-h-72 w-full rounded-2xl bg-stone-200 object-cover dark:bg-stone-800" />
      )}
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onPress={() => input.current?.click()} isDisabled={upload.isPending}>
            {upload.isPending ? 'Uploading…' : asset.has_photo ? 'Change photo' : 'Add a photo'}
          </Button>
          {asset.has_photo && <Button variant="danger-ghost" onPress={() => remove.mutate()} isDisabled={remove.isPending}>Remove photo</Button>}
          <input ref={input} type="file" accept="image/*,.heic,.heif" hidden aria-label="Choose a photo" data-testid="asset-photo-input"
            onChange={(e) => { const f = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (f) upload.mutate(f) }} />
        </div>
      )}
      <ErrorText error={upload.error ?? remove.error} />
    </div>
  )
}
