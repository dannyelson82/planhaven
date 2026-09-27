import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Checkbox } from 'react-aria-components'
import { api } from '../api.ts'
import { useLiveProject } from '../live.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'

export type ListSummary = { id: string; project_id: string; title: string; kind: Kind; open_items: number; total_items: number; version: number }
type Kind = 'shopping' | 'parts' | 'checklist'
type Item = { id: string; text: string; quantity: string | null; unit: string | null; price_cents: number | null; checked: boolean; version: number }
type ListDetail = ListSummary & { items: Item[] }

const KIND_LABEL: Record<Kind, string> = { shopping: 'Shopping', parts: 'Parts', checklist: 'Checklist' }

/** Lists section on a project page. */
export function ProjectLists({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const client = useQueryClient()
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => api<ListSummary[]>('GET', `/api/v1/projects/${projectId}/lists`) })
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
  const list = useQuery({ queryKey: ['list', id], queryFn: () => api<ListDetail>('GET', `/api/v1/lists/${id}`) })
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
  const add = useMutation({
    mutationFn: (item: { text: string; qty: string }) => api('POST', `/api/v1/lists/${id}/items`, {
      text: item.text, ...(item.qty ? { quantity: item.qty } : {}),
    }, { 'Idempotency-Key': crypto.randomUUID() }),
    onMutate: () => { setText(''); setQty('') },
    onError: (_e, item) => { setText(item.text); setQty(item.qty) },
    onSettled: refresh,
  })
  const toggle = useMutation({
    mutationFn: (i: Item) => api('PATCH', `/api/v1/list-items/${i.id}`, { checked: !i.checked }),
    onMutate: async (i) => {
      await client.cancelQueries({ queryKey: ['list', id] })
      client.setQueryData<ListDetail>(['list', id], (d) => d && { ...d, items: d.items.map((x) => x.id === i.id ? { ...x, checked: !x.checked } : x) })
    },
    onSettled: refresh,
  })
  const remove = useMutation({ mutationFn: (i: Item) => api('DELETE', `/api/v1/list-items/${i.id}`), onSettled: refresh })
  if (list.error) return <ErrorText error={list.error} />
  if (!list.data) return <p className="text-stone-500">Loading…</p>
  const l = list.data
  const open = l.items.filter((i) => !i.checked)
  const done = l.items.filter((i) => i.checked)
  return (
    <div className="space-y-4">
      <Link to={`/projects/${l.project_id}`} className="text-sm text-brand-700 dark:text-brand-100">← Back to project</Link>
      <h1 className="text-2xl font-bold">{l.title}</h1>
      <Form onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate({ text, qty }) }}>
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1"><Field label="Add item" isRequired maxLength={500} value={text} onChange={setText} /></div>
          <div className="w-20"><Field label="Qty" inputMode="numeric" maxLength={12} value={qty} onChange={setQty} /></div>
        </div>
        <ErrorText error={add.error} />
        <Button type="submit">Add</Button>
      </Form>
      <ItemList items={open} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} />
      {open.length === 0 && <p className="text-stone-500">All done!</p>}
      {done.length > 0 && (
        <>
          <p className="pt-2 text-sm font-medium text-stone-500">In the cart ({done.length})</p>
          <ItemList items={done} onToggle={(i) => toggle.mutate(i)} onDelete={(i) => remove.mutate(i)} />
        </>
      )}
      <ErrorText error={toggle.error ?? remove.error} />
    </div>
  )
}

function ItemList({ items, onToggle, onDelete }: { items: Item[]; onToggle: (i: Item) => void; onDelete: (i: Item) => void }) {
  if (items.length === 0) return null
  return (
    <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
      {items.map((i) => (
        <li key={i.id} className="flex items-center gap-2 px-3">
          <Checkbox isSelected={i.checked} onChange={() => onToggle(i)} className="group flex min-h-14 flex-1 items-center gap-3">
            <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-full border-2 border-stone-400 group-data-[selected]:border-brand-600 group-data-[selected]:bg-brand-600 group-data-[selected]:text-white">
              {i.checked ? '✓' : ''}
            </span>
            <span className={`min-w-0 flex-1 text-lg ${i.checked ? 'text-stone-500 line-through' : ''}`}>{i.text}</span>
            {quantityText(i) && <span className="text-sm text-stone-500">{quantityText(i)}</span>}
          </Checkbox>
          <Button variant="ghost" aria-label={`Delete ${i.text}`} onPress={() => onDelete(i)}>✕</Button>
        </li>
      ))}
    </ul>
  )
}
