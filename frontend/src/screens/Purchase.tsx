// One purchase: a cost entry with its optional details (owner request, 2026-09-28): the
// store, a receipt, and item lines, some copied from the project's lists with their estimated
// prices and then set to what was paid. The amount paid stays what was typed (tax included);
// the items are a breakdown.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, useRef, useState } from 'react'
import { api } from '../api.ts'
import { formatCents, parseAmount } from '../money.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { DOCUMENT_TYPES, uploadToProject } from '../uploads.ts'
import type { ListSummary } from './Lists.tsx'

type Item = { id: string; text: string; quantity: string | null; price_cents: number | null; list_item_id: string | null; version: number }
type Purchase = {
  id: string; project_id: string; description: string; amount_cents: number; spent_on: string
  store: string; receipt_id: string | null; receipt_name: string | null; version: number
  items: Item[]; can_edit: boolean
}
type ListItem = { id: string; text: string; quantity: string | null; price_cents: number | null; checked: boolean }

const lineCents = (i: { price_cents: number | null; quantity: string | null }) =>
  Math.round((i.price_cents ?? 0) * (i.quantity ? Number(i.quantity) : 1))
const qtyText = (q: string | null) => (q ? String(Number(q)) : '')
const priceText = (c: number | null) => (c === null ? '' : (c / 100).toFixed(2))
const blurOnEnter = (e: KeyboardEvent<HTMLInputElement>) => { if (e.key === 'Enter') e.currentTarget.blur() }
const input = 'min-w-0 rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900'

export function PurchaseScreen({ id }: { id: string }) {
  const purchase = useQuery({ queryKey: ['cost', id], queryFn: () => api<Purchase>('GET', `/api/v1/costs/${id}`) })
  if (purchase.error) return <ErrorText error={purchase.error} />
  if (!purchase.data) return <p className="text-stone-500">Loading…</p>
  return <PurchaseView purchase={purchase.data} />
}

function PurchaseView({ purchase: p }: { purchase: Purchase }) {
  const client = useQueryClient()
  const key = ['cost', p.id]
  const refreshProject = () => client.invalidateQueries({ queryKey: ['costs', p.project_id] })
  // Changes are sent one at a time, each with the version the previous one returned, so two
  // boxes changed in quick succession aren't refused as someone else's change.
  const chain = useRef<Promise<unknown>>(Promise.resolve())
  const serial = <T,>(send: () => Promise<T>): Promise<T> => {
    const run = chain.current.catch(() => undefined).then(send)
    chain.current = run
    return run
  }
  const saveCost = useMutation({
    mutationFn: (changes: Partial<Purchase>) => serial(async () => {
      const latest = client.getQueryData<Purchase>(key) ?? p
      const saved = await api<Omit<Purchase, 'items' | 'can_edit'>>('PATCH', `/api/v1/costs/${p.id}`, changes, { 'If-Match': `"${latest.version}"` })
      client.setQueryData<Purchase>(key, (d) => d && { ...d, ...saved })
    }),
    onSettled: refreshProject,
  })
  const saveItem = useMutation({
    mutationFn: ({ item, changes }: { item: Item; changes: Partial<Item> }) => serial(async () => {
      const latest = client.getQueryData<Purchase>(key)?.items.find((i) => i.id === item.id) ?? item
      const saved = await api<Item>('PATCH', `/api/v1/cost-items/${item.id}`, changes, { 'If-Match': `"${latest.version}"` })
      client.setQueryData<Purchase>(key, (d) => d && { ...d, items: d.items.map((i) => (i.id === saved.id ? saved : i)) })
    }),
  })
  const setItems = (items: Item[]) => client.setQueryData<Purchase>(key, (d) => d && { ...d, items })
  const addItems = useMutation({
    mutationFn: (body: { items?: { text: string; quantity?: string; price_cents?: number }[]; list_item_ids?: string[] }) =>
      api<Item[]>('POST', `/api/v1/costs/${p.id}/items`, body),
    onSuccess: setItems,
    onSettled: refreshProject,
  })
  const removeItem = useMutation({
    mutationFn: (item: Item) => api('DELETE', `/api/v1/cost-items/${item.id}`),
    onSuccess: (_d, item) => client.setQueryData<Purchase>(key, (d) => d && { ...d, items: d.items.filter((i) => i.id !== item.id) }),
    onSettled: refreshProject,
  })
  const removeEntry = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/costs/${p.id}`),
    onSuccess: async () => { await refreshProject(); navigate(`/projects/${p.project_id}`) },
  })
  const [confirmDelete, setConfirmDelete] = useState(false)
  const itemsTotal = p.items.reduce((sum, i) => sum + lineCents(i), 0)
  const priced = p.items.some((i) => i.price_cents !== null)
  const difference = p.amount_cents - itemsTotal

  return (
    <div className="space-y-4">
      <Link to={`/projects/${p.project_id}`} className="text-sm text-brand-700 dark:text-brand-100">← Back to project</Link>
      <h1 className="text-2xl font-bold">{p.description}</h1>
      <Card className="space-y-3">
        {p.can_edit ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <SavedField label="What for" value={p.description} maxLength={300} required onSave={(v) => saveCost.mutate({ description: v })} />
            <SavedField label="Store" value={p.store} maxLength={200} onSave={(v) => saveCost.mutate({ store: v })} />
            <SavedField label="Date" type="date" value={p.spent_on} required onSave={(v) => saveCost.mutate({ spent_on: v })} />
            <SavedField label="Amount paid (CAD)" value={priceText(p.amount_cents)} maxLength={16} required inputMode="decimal"
              parse={(v) => parseAmount(v) !== null} onSave={(v) => saveCost.mutate({ amount_cents: parseAmount(v)! })} />
          </div>
        ) : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-stone-500">Store</dt><dd>{p.store || '—'}</dd>
            <dt className="text-stone-500">Date</dt><dd>{new Date(`${p.spent_on}T12:00:00`).toLocaleDateString()}</dd>
            <dt className="text-stone-500">Amount paid</dt><dd className="tabular-nums">{formatCents(p.amount_cents)}</dd>
          </dl>
        )}
        <Receipt purchase={p} onChange={(receipt_id) => saveCost.mutate({ receipt_id })} busy={saveCost.isPending} />
        <ErrorText error={saveCost.error} />
      </Card>

      <section aria-label="Items" className="space-y-3">
        <h2 className="text-lg font-semibold">Items</h2>
        {p.items.length === 0 && <p className="text-sm text-stone-500">No items yet. They're optional: add them to keep a breakdown of this purchase.</p>}
        {p.items.length > 0 && (
          <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
            {p.items.map((i) => p.can_edit
              ? <ItemRow key={i.id} item={i} onSave={(changes) => saveItem.mutate({ item: i, changes })} onDelete={() => removeItem.mutate(i)} />
              : (
                <li key={i.id} className="flex items-center gap-2 px-3 py-2">
                  <span className="min-w-0 flex-1">{i.text}</span>
                  {i.quantity && <span className="text-sm text-stone-500">{qtyText(i.quantity)} ×</span>}
                  <span className="tabular-nums">{i.price_cents !== null ? formatCents(lineCents(i)) : ''}</span>
                </li>
              ))}
          </ul>
        )}
        {priced && (
          <dl aria-label="Totals" className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-1">
            <dt className="text-stone-600 dark:text-stone-400">Items</dt><dd className="text-right tabular-nums" aria-label="Items total">{formatCents(itemsTotal)}</dd>
            <dt className="text-stone-600 dark:text-stone-400">{difference >= 0 ? 'Tax and other' : 'Items cost more than was paid by'}</dt>
            <dd className="text-right tabular-nums">{formatCents(Math.abs(difference))}</dd>
            <dt className="font-semibold">Paid</dt><dd className="text-right font-semibold tabular-nums">{formatCents(p.amount_cents)}</dd>
          </dl>
        )}
        {p.can_edit && priced && difference !== 0 && (
          <Button variant="ghost" onPress={() => saveCost.mutate({ amount_cents: itemsTotal })}>Use the items total as the amount paid</Button>
        )}
        {p.can_edit && <AddItem onAdd={(item) => addItems.mutate({ items: [item] })} busy={addItems.isPending} />}
        {p.can_edit && <FromLists purchase={p} onAdd={(ids) => addItems.mutate({ list_item_ids: ids })} busy={addItems.isPending} />}
        <ErrorText error={saveItem.error ?? addItems.error ?? removeItem.error} />
      </section>

      {p.can_edit && (
        <Button variant="danger-ghost" isDisabled={removeEntry.isPending} onPress={() => (confirmDelete ? removeEntry.mutate() : setConfirmDelete(true))}>
          {confirmDelete ? 'Tap again to delete this entry' : 'Delete this entry'}
        </Button>
      )}
      <ErrorText error={removeEntry.error} />
    </div>
  )
}

/** A box saved when you leave it (or press Enter), if it changed and is valid. */
function SavedField({ label, value, onSave, type = 'text', maxLength, required, inputMode, parse }: {
  label: string; value: string; onSave: (value: string) => void; type?: 'text' | 'date'; maxLength?: number
  required?: boolean; inputMode?: 'decimal'; parse?: (value: string) => boolean
}) {
  const [text, setText] = useState(value)
  const [base, setBase] = useState(value)
  if (base !== value) { // saved elsewhere: take it unless this box is being changed
    if (text === base) setText(value)
    setBase(value)
  }
  const ok = (!required || text.trim() !== '') && (!parse || !text.trim() || parse(text))
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      <input type={type} value={text} maxLength={maxLength} inputMode={inputMode} aria-invalid={!ok}
        onChange={(e) => setText(e.target.value)} onKeyDown={blurOnEnter}
        onBlur={() => { if (ok && text.trim() !== value) onSave(text.trim()); else if (!ok) setText(value) }}
        className={`${input} w-full ${ok ? '' : 'border-red-600'}`} />
    </label>
  )
}

function ItemRow({ item, onSave, onDelete }: { item: Item; onSave: (changes: Partial<Item>) => void; onDelete: () => void }) {
  const saved = { text: item.text, qty: qtyText(item.quantity), price: priceText(item.price_cents) }
  const [text, setText] = useState(saved.text)
  const [qty, setQty] = useState(saved.qty)
  const [price, setPrice] = useState(saved.price)
  const [base, setBase] = useState(saved)
  if (base.text !== saved.text || base.qty !== saved.qty || base.price !== saved.price) {
    if (text === base.text) setText(saved.text)
    if (qty === base.qty) setQty(saved.qty)
    if (price === base.price) setPrice(saved.price)
    setBase(saved)
  }
  const cents = price.trim() ? parseAmount(price) : null
  const priceOk = !price.trim() || (cents !== null && cents >= 0)
  const qtyOk = !qty.trim() || /^\d+(\.\d{1,3})?$/.test(qty.trim())
  const commit = () => {
    if (!text.trim() || !priceOk || !qtyOk) return
    const changes: Partial<Item> = {}
    if (text.trim() !== saved.text) changes.text = text.trim()
    if (qty.trim() !== saved.qty) changes.quantity = qty.trim() || null
    if (price.trim() !== saved.price) changes.price_cents = cents
    if (Object.keys(changes).length) onSave(changes)
  }
  return (
    <li className="flex flex-wrap items-center gap-2 px-3 py-2">
      <input aria-label={`Item: ${item.text}`} value={text} maxLength={500} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={blurOnEnter}
        className={`${input} basis-full sm:flex-1 sm:basis-auto`} />
      <input aria-label={`Quantity of ${item.text}`} value={qty} inputMode="decimal" maxLength={12} placeholder="Qty" aria-invalid={!qtyOk}
        onChange={(e) => setQty(e.target.value)} onBlur={commit} onKeyDown={blurOnEnter} className={`${input} w-20 ${qtyOk ? '' : 'border-red-600'}`} />
      <input aria-label={`Price each of ${item.text}`} value={price} inputMode="decimal" maxLength={16} placeholder="$ each" aria-invalid={!priceOk}
        onChange={(e) => setPrice(e.target.value)} onBlur={commit} onKeyDown={blurOnEnter} className={`${input} w-28 ${priceOk ? '' : 'border-red-600'}`} />
      <span className="ml-auto w-24 text-right tabular-nums text-stone-600 dark:text-stone-400">{item.price_cents !== null ? formatCents(lineCents(item)) : ''}</span>
      <Button variant="danger-ghost" aria-label={`Delete ${item.text}`} onPress={onDelete}>✕</Button>
    </li>
  )
}

function AddItem({ onAdd, busy }: { onAdd: (item: { text: string; quantity?: string; price_cents?: number }) => void; busy: boolean }) {
  const [text, setText] = useState('')
  const [qty, setQty] = useState('')
  const [price, setPrice] = useState('')
  const cents = price.trim() ? parseAmount(price) : null
  const ok = text.trim() !== '' && (!price.trim() || (cents !== null && cents >= 0)) && (!qty.trim() || /^\d+(\.\d{1,3})?$/.test(qty.trim()))
  return (
    <Form onSubmit={(e) => {
      e.preventDefault()
      if (!ok) return
      onAdd({ text: text.trim(), ...(qty.trim() ? { quantity: qty.trim() } : {}), ...(cents !== null ? { price_cents: cents } : {}) })
      setText(''); setQty(''); setPrice('')
    }}>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1"><Field label="Add an item" maxLength={500} value={text} onChange={setText} /></div>
        <div className="w-20"><Field label="Qty" inputMode="numeric" maxLength={12} value={qty} onChange={setQty} /></div>
        <div className="w-28"><Field label="Price each" inputMode="numeric" maxLength={16} value={price} onChange={setPrice} /></div>
        <Button type="submit" variant="secondary" isDisabled={!ok || busy}>Add item</Button>
      </div>
    </Form>
  )
}

/** Items checked off on the project's shopping and parts lists, to add with their prices. */
function FromLists({ purchase, onAdd, busy }: { purchase: Purchase; onAdd: (ids: string[]) => void; busy: boolean }) {
  const [open, setOpen] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const lists = useQuery({
    queryKey: ['lists', purchase.project_id],
    queryFn: () => api<ListSummary[]>('GET', `/api/v1/projects/${purchase.project_id}/lists`),
    enabled: open,
  })
  const buyable = (lists.data ?? []).filter((l) => l.kind !== 'checklist')
  const details = useQuery({
    queryKey: ['purchase-lists', purchase.project_id, buyable.map((l) => `${l.id}:${l.version}:${l.open_items}`).join(',')],
    queryFn: () => Promise.all(buyable.map((l) => api<{ id: string; title: string; items: ListItem[] }>('GET', `/api/v1/lists/${l.id}`))),
    enabled: open && lists.isSuccess,
  })
  const onPurchase = new Set(purchase.items.map((i) => i.list_item_id).filter(Boolean))
  const groups = (details.data ?? []).map((l) => ({ ...l, items: l.items.filter((i) => i.checked && !onPurchase.has(i.id)) })).filter((l) => l.items.length > 0)
  if (!open) return <Button variant="secondary" onPress={() => setOpen(true)}>Add items from a list</Button>
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">Checked-off items on this project's lists</h3>
        <Button variant="ghost" onPress={() => setOpen(false)}>Close</Button>
      </div>
      {details.isSuccess && groups.length === 0 && <p className="text-sm text-stone-500">Nothing checked off that isn't on this purchase already.</p>}
      {groups.map((l) => (
        <fieldset key={l.id} className="space-y-1">
          <legend className="text-sm font-medium text-stone-600 dark:text-stone-400">{l.title}</legend>
          {l.items.map((i) => (
            <label key={i.id} className="flex min-h-11 items-center gap-3">
              <input type="checkbox" className="size-5 accent-brand-600" checked={chosen.includes(i.id)}
                onChange={(e) => setChosen(e.target.checked ? [...chosen, i.id] : chosen.filter((x) => x !== i.id))} />
              <span className="min-w-0 flex-1">{i.text}</span>
              <span className="text-sm tabular-nums text-stone-500">{i.price_cents !== null ? formatCents(lineCents(i)) : ''}</span>
            </label>
          ))}
        </fieldset>
      ))}
      <ErrorText error={lists.error ?? details.error} />
      <Button isDisabled={chosen.length === 0 || busy} onPress={() => { onAdd(chosen); setChosen([]); setOpen(false) }}>
        {chosen.length ? `Add ${chosen.length} item${chosen.length === 1 ? '' : 's'}` : 'Add items'}
      </Button>
    </Card>
  )
}

/** The receipt: a photo or PDF kept with the project's files. */
function Receipt({ purchase: p, onChange, busy }: { purchase: Purchase; onChange: (receiptId: string | null) => void; busy: boolean }) {
  const client = useQueryClient()
  const pick = useRef<HTMLInputElement>(null)
  const camera = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: (file: File) => uploadToProject(p.project_id, file),
    onSuccess: async (doc) => { onChange(doc.id); await client.invalidateQueries({ queryKey: ['attachments', p.project_id] }) },
  })
  const onFile = (el: HTMLInputElement) => { const f = el.files?.[0]; el.value = ''; if (f) upload.mutate(f) }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium">Receipt</span>
      {p.receipt_id ? (
        <a href={`/api/v1/attachments/${p.receipt_id}/download`} download className="min-w-0 truncate text-brand-700 underline-offset-2 hover:underline dark:text-brand-100">
          {p.receipt_name ?? 'receipt'}
        </a>
      ) : (
        <span className="text-sm text-stone-500">None</span>
      )}
      {p.can_edit && (
        <>
          <Button variant="secondary" onPress={() => camera.current?.click()} isDisabled={upload.isPending || busy} className="md:hidden">Take photo</Button>
          <Button variant="secondary" onPress={() => pick.current?.click()} isDisabled={upload.isPending || busy}>
            {upload.isPending ? 'Uploading…' : p.receipt_id ? 'Replace' : 'Add receipt'}
          </Button>
          {p.receipt_id && <Button variant="ghost" onPress={() => onChange(null)} isDisabled={busy}>Remove</Button>}
          <input ref={camera} type="file" accept="image/*" capture="environment" hidden aria-hidden="true" tabIndex={-1} onChange={(e) => onFile(e.currentTarget)} />
          <input ref={pick} type="file" accept={DOCUMENT_TYPES} hidden aria-label="Choose the receipt" onChange={(e) => onFile(e.currentTarget)} />
        </>
      )}
      <ErrorText error={upload.error} />
    </div>
  )
}
