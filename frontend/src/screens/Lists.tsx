import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Checkbox } from 'react-aria-components'
import { api } from '../api.ts'
import { formatCents, parseAmount } from '../money.ts'
import { navigate } from '../router.ts'
import { useLiveProject } from '../live.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { cachedGet, sendOrQueue, updateOfflineCopy } from '../offline.ts'
import { Movable } from './Movable.tsx'
import { SaveAsTemplate } from './Templates.tsx'

export type ListSummary = {
  id: string; project_id: string; title: string; kind: Kind; open_items: number; total_items: number; version: number
  estimated_cents: number | null; remaining_cents: number | null
}
type Kind = 'shopping' | 'parts' | 'checklist'
type Item = { id: string; text: string; quantity: string | null; unit: string | null; price_cents: number | null; checked: boolean; version: number }
type ListDetail = ListSummary & { items: Item[] }

const KIND_LABEL: Record<Kind, string> = { shopping: 'Shopping', parts: 'Parts', checklist: 'Checklist' }

/** Lists group on a project page (lists given their own tile are left out). */
export function ProjectLists({ projectId, exclude = [] }: { projectId: string; exclude?: string[] }) {
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => cachedGet<ListSummary[]>(`/api/v1/projects/${projectId}/lists`) })
  return (
    <section aria-label="Lists" className="space-y-3">
      <h2 className="text-lg font-semibold">Lists</h2>
      <ul className="grid gap-2 @xl:grid-cols-2">
        {(lists.data ?? []).filter((l) => !exclude.includes(l.id)).map((l) => (
          <li key={l.id}><Movable dragKey={`list:${l.id}`} label={`List: ${l.title}`}><ListCard list={l} /></Movable></li>
        ))}
      </ul>
      {lists.data?.length === 0 && <p className="text-sm text-stone-500">No lists yet.</p>}
      <ErrorText error={lists.error} />
    </section>
  )
}

function quantityText(i: Item): string {
  const q = i.quantity ? String(Number(i.quantity)) : ''
  return [q, i.unit].filter(Boolean).join(' ')
}

function ListCard({ list: l, children }: { list: ListSummary; children?: ReactNode }) {
  return (
    <Card>
      <Link to={`/lists/${l.id}`} className="block font-semibold">{l.title}</Link>
      <p className="text-sm text-stone-500">{KIND_LABEL[l.kind]} · {l.open_items} to get of {l.total_items}{l.remaining_cents !== null && ` · about ${formatCents(l.remaining_cents)} to go`}</p>
      {children}
    </Card>
  )
}

/** New list (in the project's add bar). */
export function NewListForm({ projectId }: { projectId: string }) {
  const client = useQueryClient()
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<Kind>('shopping')
  const create = useMutation({
    mutationFn: () => api('POST', `/api/v1/projects/${projectId}/lists`, { title, kind }),
    onSuccess: async () => { setTitle(''); await client.invalidateQueries({ queryKey: ['lists', projectId] }) },
  })
  return (
    <>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate() }}>
        <div className="min-w-0 flex-1"><Field label="New list" maxLength={200} value={title} onChange={setTitle} /></div>
        <select aria-label="List type" value={kind} onChange={(e) => setKind(e.target.value as Kind)}
          className="min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900">
          {(Object.keys(KIND_LABEL) as Kind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <Button type="submit" variant="secondary" isDisabled={create.isPending}>Add list</Button>
      </form>
      <ErrorText error={create.error} />
    </>
  )
}

/** One list in its own tile on the project page: what's still to get. */
export function ListTile({ projectId, listId }: { projectId: string; listId: string }) {
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => cachedGet<ListSummary[]>(`/api/v1/projects/${projectId}/lists`) })
  const summary = lists.data?.find((l) => l.id === listId)
  const detail = useQuery({
    queryKey: ['list', listId, 'tile', summary?.version, summary?.open_items, summary?.total_items],
    queryFn: () => api<ListDetail>('GET', `/api/v1/lists/${listId}`),
    enabled: summary !== undefined,
  })
  if (!summary) return null // deleted since, or not shared with this person
  const open = (detail.data?.items ?? []).filter((i) => !i.checked)
  return (
    <section aria-label={`List: ${summary.title}`}>
      <ListCard list={summary}>
        {open.length > 0 && (
          <ul className="mt-2 space-y-1">
            {open.slice(0, 12).map((i) => (
              <li key={i.id} className="flex gap-2"><span className="min-w-0 flex-1">{i.text}</span><span className="text-sm text-stone-500">{quantityText(i)}</span></li>
            ))}
            {open.length > 12 && <li className="text-sm text-stone-500">+{open.length - 12} more</li>}
          </ul>
        )}
      </ListCard>
    </section>
  )
}

type Suggestion = { text: string; quantity: string | null; unit: string | null; price_cents: number | null }

/** While typing an item: things added to lists before, with their quantity and price. */
function ItemSuggestions({ typed, showPrices, onPick }: { typed: string; showPrices: boolean; onPick: (s: Suggestion) => void }) {
  const [query, setQuery] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setQuery(typed.trim()), 200)
    return () => clearTimeout(t)
  }, [typed])
  const found = useQuery({
    queryKey: ['item-suggestions', query],
    queryFn: () => api<Suggestion[]>('GET', `/api/v1/list-item-suggestions?q=${encodeURIComponent(query)}`),
    enabled: query.length >= 2 && navigator.onLine,
    staleTime: 60_000,
  })
  const shown = (found.data ?? []).filter((s) => s.text.toLowerCase() !== typed.trim().toLowerCase())
  if (typed.trim().length < 2 || shown.length === 0) return null
  return (
    <ul aria-label="Suggestions" className="flex flex-wrap gap-2">
      {shown.map((s) => (
        <li key={s.text}>
          <button type="button" onClick={() => onPick(s)} aria-label={`Use suggestion: ${s.text}`}
            className="min-h-11 rounded-full bg-stone-100 px-3 text-sm hover:bg-stone-200 dark:bg-stone-800 dark:hover:bg-stone-700">
            {s.text}
            {s.quantity && <span className="text-stone-500"> · {String(Number(s.quantity))}</span>}
            {showPrices && s.price_cents !== null && <span className="text-stone-500"> · {formatCents(s.price_cents)}</span>}
          </button>
        </li>
      ))}
    </ul>
  )
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
  // Price from a picked suggestion (shopping and parts lists); typing the name again drops it.
  const [price, setPrice] = useState<number | null>(null)
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
    mutationFn: async (item: { text: string; qty: string; price: number | null }) => {
      const key = crypto.randomUUID()
      const queued = await sendOrQueue({
        method: 'POST', path: `/api/v1/lists/${id}/items`, headers: { 'Idempotency-Key': key },
        label: `Add “${item.text}”`,
        body: { text: item.text, ...(item.qty ? { quantity: item.qty } : {}), ...(item.price !== null ? { price_cents: item.price } : {}) },
      })
      if (queued) {
        const pending: Item = { id: `pending-${key}`, text: item.text, quantity: item.qty || null, unit: null, price_cents: item.price, checked: false, version: 0 }
        await showLocally((d) => ({ ...d, items: [...d.items, pending] }))
      }
    },
    onMutate: () => { setText(''); setQty(''); setPrice(null) },
    onError: (_e, item) => { setText(item.text); setQty(item.qty); setPrice(item.price) },
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
  // Checked-off items become a spent entry on the project, with their estimated prices; its
  // page then takes the store, the receipt and what was actually paid.
  const record = useMutation({
    mutationFn: async () => {
      const d = list.data!
      const bought = d.items.filter((i) => i.checked && !i.id.startsWith('pending-'))
      const cost = await api<{ id: string }>('POST', `/api/v1/projects/${d.project_id}/costs`, {
        description: d.title, amount_cents: bought.reduce((sum, i) => sum + lineCents(i), 0),
      })
      await api('POST', `/api/v1/costs/${cost.id}/items`, { list_item_ids: bought.map((i) => i.id) })
      return cost.id
    },
    onSuccess: async (costId) => {
      await client.invalidateQueries({ queryKey: ['costs'] })
      navigate(`/costs/${costId}`)
    },
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
      <Form onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate({ text, qty, price: l.kind === 'checklist' ? null : price }) }}>
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1"><Field label="Add item" isRequired maxLength={500} value={text} onChange={(v) => { setText(v); setPrice(null) }} /></div>
          <div className="w-20"><Field label="Qty" inputMode="numeric" maxLength={12} value={qty} onChange={setQty} /></div>
        </div>
        <ItemSuggestions typed={text} showPrices={l.kind !== 'checklist'}
          onPick={(s) => { setText(s.text); setQty(s.quantity ? String(Number(s.quantity)) : ''); setPrice(s.price_cents) }} />
        {price !== null && l.kind !== 'checklist' && <p className="text-sm text-stone-500">Price each: {formatCents(price)} (change it in edit mode)</p>}
        <ErrorText error={add.error} />
        <Button type="submit">Add</Button>
      </Form>
      <ItemList items={open} editing={editing} priced={l.kind !== 'checklist'} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} onSave={(i, text, qty, price) => save.mutate({ i, text, qty, price })} />
      {open.length === 0 && <p className="text-stone-500">All done!</p>}
      {done.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
            <p className="text-sm font-medium text-stone-500">In the cart ({done.length})</p>
            {l.kind !== 'checklist' && !editing && (
              <Button variant="secondary" onPress={() => record.mutate()} isDisabled={record.isPending}>Record purchase</Button>
            )}
          </div>
          <ItemList items={done} editing={editing} priced={l.kind !== 'checklist'} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} onSave={(i, text, qty, price) => save.mutate({ i, text, qty, price })} />
        </>
      )}
      {!editing && l.items.length > 0 && <SaveAsTemplate path={`/api/v1/lists/${id}/template`} suggested={l.title} label="Save as template" />}
      {editing && (
        <div className="flex justify-end">
          <Button variant="danger-ghost" isDisabled={removeList.isPending}
            onPress={() => (confirmDelete ? removeList.mutate(l.project_id) : setConfirmDelete(true))}>
            {confirmDelete ? 'Tap again to delete this list' : 'Delete this list'}
          </Button>
        </div>
      )}
      <ErrorText error={toggle.error ?? remove.error ?? save.error ?? undo.error ?? removeList.error ?? rename.error ?? record.error} />
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
