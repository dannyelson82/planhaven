import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { Checkbox } from 'react-aria-components'
import { api } from '../api.ts'
import { formatCents, parseAmount } from '../money.ts'
import { navigate } from '../router.ts'
import { useLiveProject } from '../live.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { cachedGet, sendOrQueue, updateOfflineCopy } from '../offline.ts'

export type ListSummary = {
  id: string; project_id: string; title: string; kind: Kind; open_items: number; total_items: number; version: number
  estimated_cents: number | null; remaining_cents: number | null
}
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
              <p className="text-sm text-stone-500">{KIND_LABEL[l.kind]} · {l.open_items} to get of {l.total_items}{l.remaining_cents !== null && ` · about ${formatCents(l.remaining_cents)} to go`}</p>
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

/** Estimated price for the line: price each x quantity (1 when there's no quantity). */
function lineCents(i: Item): number {
  return Math.round((i.price_cents ?? 0) * (i.quantity ? Number(i.quantity) : 1))
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
      ...(i.price_cents !== null ? { price_cents: i.price_cents } : {}),
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
  const saving = useRef<Promise<unknown>>(Promise.resolve())
  const save = useMutation({
    // One save at a time, each with the version the previous one returned: two boxes of a row
    // changed in quick succession aren't refused as someone else's change.
    mutationFn: ({ i, text, qty, price }: { i: Item; text: string; qty: string; price: number | null }) => {
      const run = saving.current.catch(() => undefined).then(async () => {
        const latest = client.getQueryData<ListDetail>(['list', id])?.items.find((x) => x.id === i.id)
        const updated = await api<Item>('PATCH', `/api/v1/list-items/${i.id}`, { text, quantity: qty.trim() || null, price_cents: price },
          { 'If-Match': `"${latest?.version ?? i.version}"` })
        client.setQueryData<ListDetail>(['list', id], (d) => d && { ...d, items: d.items.map((x) => x.id === updated.id ? updated : x) })
      })
      saving.current = run
      return run
    },
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
      {l.kind !== 'checklist' && l.estimated_cents !== null && (
        <p className="text-stone-600 dark:text-stone-400">
          Estimated <span className="font-semibold tabular-nums">{formatCents(l.estimated_cents)}</span>
          {' · '}<span className="tabular-nums">{formatCents(l.remaining_cents ?? 0)}</span> still to get
        </p>
      )}
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
      <ItemList items={open} editing={editing} priced={l.kind !== 'checklist'} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} onSave={(i, text, qty, price) => save.mutate({ i, text, qty, price })} />
      {open.length === 0 && <p className="text-stone-500">All done!</p>}
      {done.length > 0 && (
        <>
          <p className="pt-2 text-sm font-medium text-stone-500">In the cart ({done.length})</p>
          <ItemList items={done} editing={editing} priced={l.kind !== 'checklist'} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} onSave={(i, text, qty, price) => save.mutate({ i, text, qty, price })} />
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

type Handlers = { onToggle: (i: Item) => void; onDelete: (i: Item) => void; onSave: (i: Item, text: string, qty: string, price: number | null) => void }

function ItemList({ items, editing, priced, onToggle, onDelete, onSave }: { items: Item[]; editing: boolean; priced: boolean } & Handlers) {
  if (items.length === 0) return null
  if (editing) {
    return (
      <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
        {items.map((i) => <EditRow key={i.id} item={i} priced={priced} onDelete={onDelete} onSave={onSave} />)}
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
            {priced && i.price_cents !== null && <span className="text-sm tabular-nums text-stone-500">{formatCents(lineCents(i))}</span>}
            {i.id.startsWith('pending-') && <span className="text-xs text-amber-700 dark:text-amber-400">not sent yet</span>}
          </Checkbox>
        </li>
      ))}
    </ul>
  )
}

/** Edit mode: change the name, quantity or estimated price each (saved when you leave the
 * box), or delete. */
function EditRow({ item, priced, onDelete, onSave }: { item: Item; priced: boolean } & Pick<Handlers, 'onDelete' | 'onSave'>) {
  const saved = {
    text: item.text,
    qty: item.quantity ? String(Number(item.quantity)) : '',
    price: item.price_cents === null ? '' : (item.price_cents / 100).toFixed(2),
  }
  const [text, setText] = useState(saved.text)
  const [qty, setQty] = useState(saved.qty)
  const [price, setPrice] = useState(saved.price)
  // A newer saved copy arrived (e.g. after saving another box of this row): take it for the
  // boxes not being changed, keep what's being typed in the others.
  const [base, setBase] = useState(saved)
  if (base.text !== saved.text || base.qty !== saved.qty || base.price !== saved.price) {
    if (text === base.text) setText(saved.text)
    if (qty === base.qty) setQty(saved.qty)
    if (price === base.price) setPrice(saved.price)
    setBase(saved)
  }
  const cents = price.trim() ? parseAmount(price) : null
  const priceOk = !price.trim() || (cents !== null && cents >= 0)
  const pending = item.id.startsWith('pending-')
  const commit = () => {
    if (text.trim() && priceOk && (text !== saved.text || qty !== saved.qty || price !== saved.price)) onSave(item, text.trim(), qty, cents)
  }
  const input = 'min-w-0 rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900'
  const enter = (e: KeyboardEvent<HTMLInputElement>) => { if (e.key === 'Enter') e.currentTarget.blur() }
  return (
    <li className="flex flex-wrap items-center gap-2 px-3 py-2">
      <input aria-label={`Name of ${item.text}`} value={text} maxLength={500} disabled={pending}
        onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={enter}
        className={`${input} basis-full sm:flex-1 sm:basis-auto`} />
      <input aria-label={`Quantity of ${item.text}`} value={qty} inputMode="decimal" maxLength={12} disabled={pending}
        onChange={(e) => setQty(e.target.value)} onBlur={commit} onKeyDown={enter}
        className={`${input} w-20`} placeholder="Qty" />
      {priced && (
        <input aria-label={`Price each of ${item.text}`} value={price} inputMode="decimal" maxLength={16} disabled={pending}
          aria-invalid={!priceOk} onChange={(e) => setPrice(e.target.value)} onBlur={commit} onKeyDown={enter}
          className={`${input} w-28 ${priceOk ? '' : 'border-red-600'}`} placeholder="$ each" />
      )}
      <Button variant="danger-ghost" aria-label={`Delete ${item.text}`} isDisabled={pending} className="ml-auto"
        onPress={() => onDelete({ ...item, text: text.trim() || item.text, quantity: qty.trim() || null })}>✕</Button>
    </li>
  )
}
