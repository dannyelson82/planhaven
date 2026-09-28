import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Checkbox } from 'react-aria-components'
import { api } from '../api.ts'
import { navigate } from '../router.ts'
import { useLiveProject } from '../live.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { cachedGet, sendOrQueue, updateOfflineCopy } from '../offline.ts'

export type ListSummary = { id: string; project_id: string; title: string; kind: Kind; open_items: number; total_items: number; version: number }
type Kind = 'shopping' | 'parts' | 'checklist'
type Item = { id: string; text: string; quantity: string | null; unit: string | null; price_cents: number | null; checked: boolean; version: number }
type ListDetail = ListSummary & { items: Item[] }

const KIND_LABEL: Record<Kind, string> = { shopping: 'Shopping', parts: 'Parts', checklist: 'Checklist' }

/** Lists section on a project page. */
export function ProjectLists({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const client = useQueryClient()
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => cachedGet<ListSummary[]>(`/api/v1/projects/${projectId}/lists`) })
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<Kind>('shopping')
  const create = useMutation({
    mutationFn: () => api('POST', `/api/v1/projects/${projectId}/lists`, { title, kind }),
    onSuccess: async () => { setTitle(''); await client.invalidateQueries({ queryKey: ['lists', projectId] }) },
  })
  return (
    <section aria-label="Lists" className="space-y-3">
      <h2 className="text-lg font-semibold">Lists</h2>
      <ul className="grid gap-2 sm:grid-cols-2">
        {(lists.data ?? []).map((l) => (
          <li key={l.id}>
            <Card>
              <Link to={`/lists/${l.id}`} className="block font-semibold">{l.title}</Link>
              <p className="text-sm text-stone-500">{KIND_LABEL[l.kind]} · {l.open_items} to get of {l.total_items}</p>
            </Card>
          </li>
        ))}
      </ul>
      {canEdit && (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate() }}>
          <div className="min-w-0 flex-1"><Field label="New list" maxLength={200} value={title} onChange={setTitle} /></div>
          <select aria-label="List type" value={kind} onChange={(e) => setKind(e.target.value as Kind)}
            className="min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900">
            {(Object.keys(KIND_LABEL) as Kind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
          </select>
          <Button type="submit" variant="secondary" isDisabled={create.isPending}>Add list</Button>
        </form>
      )}
      <ErrorText error={create.error ?? lists.error} />
    </section>
  )
}

function quantityText(i: Item): string {
  const q = i.quantity ? String(Number(i.quantity)) : ''
  return [q, i.unit].filter(Boolean).join(' ')
}

/** One list: made for a phone in one hand in a store. */
export function ListScreen({ id }: { id: string }) {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ['list', id], queryFn: () => cachedGet<ListDetail>(`/api/v1/lists/${id}`) })
  useLiveProject(list.data?.project_id)
  // Also refresh the project's list summaries (counts), shown when going back.
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['list', id] }),
    client.invalidateQueries({ queryKey: ['lists'] }),
  ])
  const [text, setText] = useState('')
  const [qty, setQty] = useState('')
  // The boxes clear as soon as you tap Add, so you can type the next item while this one
  // saves; if saving fails, the text comes back.
  // Without a connection, adding and checking off are kept on this device and sent later
  // (the Idempotency-Key makes a resent add harmless). The change shows straight away.
  const offlineKey = `GET /api/v1/lists/${id}`
  const showLocally = async (change: (d: ListDetail) => ListDetail) => {
    client.setQueryData<ListDetail>(['list', id], (d) => d && change(d))
    await updateOfflineCopy<ListDetail>(offlineKey, change)
  }
  const add = useMutation({
    mutationFn: async (item: { text: string; qty: string }) => {
      const key = crypto.randomUUID()
      const queued = await sendOrQueue({
        method: 'POST', path: `/api/v1/lists/${id}/items`, headers: { 'Idempotency-Key': key },
        label: `Add “${item.text}”`,
        body: { text: item.text, ...(item.qty ? { quantity: item.qty } : {}) },
      })
      if (queued) {
        const pending: Item = { id: `pending-${key}`, text: item.text, quantity: item.qty || null, unit: null, price_cents: null, checked: false, version: 0 }
        await showLocally((d) => ({ ...d, items: [...d.items, pending] }))
      }
    },
    onMutate: () => { setText(''); setQty('') },
    onError: (_e, item) => { setText(item.text); setQty(item.qty) },
    onSettled: refresh,
  })
  const toggle = useMutation({
    mutationFn: async (i: Item) => {
      const queued = await sendOrQueue({ method: 'PATCH', path: `/api/v1/list-items/${i.id}`, body: { checked: !i.checked }, headers: {}, label: `${i.checked ? 'Uncheck' : 'Check off'} “${i.text}”` })
      if (queued) await showLocally((d) => ({ ...d, items: d.items.map((x) => x.id === i.id ? { ...x, checked: !i.checked } : x) }))
    },
    onMutate: async (i) => {
      await client.cancelQueries({ queryKey: ['list', id] })
      client.setQueryData<ListDetail>(['list', id], (d) => d && { ...d, items: d.items.map((x) => x.id === i.id ? { ...x, checked: !x.checked } : x) })
    },
    onSettled: refresh,
  })
  // Deleting only happens in edit mode, and can be undone for a few seconds.
  const [editing, setEditing] = useState(false)
  const [deleted, setDeleted] = useState<Item | null>(null)
  useEffect(() => {
    if (!deleted) return
    const timer = setTimeout(() => setDeleted(null), 8000)
    return () => clearTimeout(timer)
  }, [deleted])
  const remove = useMutation({
    mutationFn: (i: Item) => api('DELETE', `/api/v1/list-items/${i.id}`),
    onSuccess: (_d, i) => setDeleted(i),
    onSettled: refresh,
  })
  const undo = useMutation({
    mutationFn: (i: Item) => api('POST', `/api/v1/lists/${id}/items`, {
      text: i.text, ...(i.quantity ? { quantity: i.quantity } : {}), ...(i.unit ? { unit: i.unit } : {}),
    }, { 'Idempotency-Key': crypto.randomUUID() }),
    onSuccess: () => setDeleted(null),
    onSettled: refresh,
  })
  const [confirmDelete, setConfirmDelete] = useState(false)
  const removeList = useMutation({
    mutationFn: (projectId: string) => api('DELETE', `/api/v1/lists/${id}`).then(() => projectId),
    onSuccess: async (projectId) => {
      await client.invalidateQueries({ queryKey: ['lists'] })
      navigate(`/projects/${projectId}`)
    },
  })
  const save = useMutation({
    mutationFn: ({ i, text, qty }: { i: Item; text: string; qty: string }) =>
      api('PATCH', `/api/v1/list-items/${i.id}`, { text, quantity: qty.trim() || null }, { 'If-Match': `"${i.version}"` }),
    onSettled: refresh,
  })
  // Edit mode: the list's name can be changed (saved when you leave the box).
  const rename = useMutation({
    mutationFn: (title: string) => api('PATCH', `/api/v1/lists/${id}`, { title }, { 'If-Match': `"${list.data?.version}"` }),
    onSettled: async () => { await refresh(); await client.invalidateQueries({ queryKey: ['lists'] }) },
  })
  if (list.error) return <ErrorText error={list.error} />
  if (!list.data) return <p className="text-stone-500">Loading…</p>
  const l = list.data
  const open = l.items.filter((i) => !i.checked)
  const done = l.items.filter((i) => i.checked)
  return (
    <div className="space-y-4">
      <Link to={`/projects/${l.project_id}`} className="text-sm text-brand-700 dark:text-brand-100">← Back to project</Link>
      <div className="flex items-center justify-between gap-2">
        {editing ? (
          <input aria-label="List name" maxLength={200} defaultValue={l.title}
            onBlur={(e) => { const t = e.target.value.trim(); if (t && t !== l.title) rename.mutate(t); else e.target.value = l.title }}
            className="block min-w-0 flex-1 rounded-xl bg-transparent px-1 text-2xl font-bold ring-1 ring-stone-300 focus:outline-2 focus:outline-brand-600 dark:ring-stone-700" />
        ) : (
          <h1 className="text-2xl font-bold">{l.title}</h1>
        )}
        <Button variant={editing ? 'primary' : 'secondary'} onPress={() => setEditing(!editing)}>{editing ? 'Done' : 'Edit'}</Button>
      </div>
      {deleted && (
        <p role="status" className="flex items-center justify-between gap-2 rounded-xl bg-stone-100 p-2 pl-3 dark:bg-stone-800">
          <span className="min-w-0 truncate">Deleted “{deleted.text}”</span>
          <Button variant="ghost" onPress={() => undo.mutate(deleted)} isDisabled={undo.isPending}>Undo</Button>
        </p>
      )}
      <Form onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate({ text, qty }) }}>
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1"><Field label="Add item" isRequired maxLength={500} value={text} onChange={setText} /></div>
          <div className="w-20"><Field label="Qty" inputMode="numeric" maxLength={12} value={qty} onChange={setQty} /></div>
        </div>
        <ErrorText error={add.error} />
        <Button type="submit">Add</Button>
      </Form>
      <ItemList items={open} editing={editing} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} onSave={(i, text, qty) => save.mutate({ i, text, qty })} />
      {open.length === 0 && <p className="text-stone-500">All done!</p>}
      {done.length > 0 && (
        <>
          <p className="pt-2 text-sm font-medium text-stone-500">In the cart ({done.length})</p>
          <ItemList items={done} editing={editing} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} onSave={(i, text, qty) => save.mutate({ i, text, qty })} />
        </>
      )}
      {editing && (
        <div className="flex justify-end">
          <Button variant="danger-ghost" isDisabled={removeList.isPending}
            onPress={() => (confirmDelete ? removeList.mutate(l.project_id) : setConfirmDelete(true))}>
            {confirmDelete ? 'Tap again to delete this list' : 'Delete this list'}
          </Button>
        </div>
      )}
      <ErrorText error={toggle.error ?? remove.error ?? save.error ?? undo.error ?? removeList.error ?? rename.error} />
    </div>
  )
}

type Handlers = { onToggle: (i: Item) => void; onDelete: (i: Item) => void; onSave: (i: Item, text: string, qty: string) => void }

function ItemList({ items, editing, onToggle, onDelete, onSave }: { items: Item[]; editing: boolean } & Handlers) {
  if (items.length === 0) return null
  if (editing) {
    return (
      <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
        {items.map((i) => <EditRow key={`${i.id}-${i.version}`} item={i} onDelete={onDelete} onSave={onSave} />)}
      </ul>
    )
  }
  return (
    <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
      {items.map((i) => (
        <li key={i.id} className="flex items-center gap-2 px-3">
          <Checkbox isSelected={i.checked} isDisabled={i.id.startsWith('pending-')} onChange={() => onToggle(i)} className="group flex min-h-14 flex-1 items-center gap-3">
            <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-full border-2 border-stone-400 group-data-[selected]:border-brand-600 group-data-[selected]:bg-brand-600 group-data-[selected]:text-white">
              {i.checked ? '✓' : ''}
            </span>
            <span className={`min-w-0 flex-1 text-lg ${i.checked ? 'text-stone-500 line-through' : ''}`}>{i.text}</span>
            {quantityText(i) && <span className="text-sm text-stone-500">{quantityText(i)}</span>}
            {i.id.startsWith('pending-') && <span className="text-xs text-amber-700 dark:text-amber-400">not sent yet</span>}
          </Checkbox>
        </li>
      ))}
    </ul>
  )
}

/** Edit mode: change the name or quantity (saved when you leave the box), or delete. */
function EditRow({ item, onDelete, onSave }: { item: Item } & Pick<Handlers, 'onDelete' | 'onSave'>) {
  const [text, setText] = useState(item.text)
  const [qty, setQty] = useState(item.quantity ? String(Number(item.quantity)) : '')
  const pending = item.id.startsWith('pending-')
  const commit = () => {
    const original = item.quantity ? String(Number(item.quantity)) : ''
    if (text.trim() && (text !== item.text || qty !== original)) onSave(item, text.trim(), qty)
  }
  const input = 'min-w-0 rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900'
  return (
    <li className="flex items-center gap-2 px-3 py-2">
      <input aria-label={`Name of ${item.text}`} value={text} maxLength={500} disabled={pending}
        onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
        className={`${input} flex-1`} />
      <input aria-label={`Quantity of ${item.text}`} value={qty} inputMode="decimal" maxLength={12} disabled={pending}
        onChange={(e) => setQty(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
        className={`${input} w-20`} placeholder="Qty" />
      <Button variant="danger-ghost" aria-label={`Delete ${item.text}`} isDisabled={pending}
        onPress={() => onDelete({ ...item, text: text.trim() || item.text, quantity: qty.trim() || null })}>✕</Button>
    </li>
  )
}
