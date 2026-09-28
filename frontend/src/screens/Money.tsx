import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { formatCents, parseAmount, type QuoteStatus, STATUS_LABEL } from '../money.ts'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'
import type { Contact, Quote } from './Contacts.tsx'

type Cost = { id: string; description: string; amount_cents: number; spent_on: string; quote_id: string | null }
type FileItem = { id: string; filename: string }

const select = 'min-h-11 min-w-0 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900'

/** Quotes from contractors and money spent, on a project page. */
export function ProjectMoney({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const client = useQueryClient()
  const quotes = useQuery({ queryKey: ['quotes', projectId], queryFn: () => api<Quote[]>('GET', `/api/v1/projects/${projectId}/quotes`) })
  const costs = useQuery({ queryKey: ['costs', projectId], queryFn: () => api<Cost[]>('GET', `/api/v1/projects/${projectId}/costs`) })
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['quotes', projectId] }),
    client.invalidateQueries({ queryKey: ['costs', projectId] }),
    client.invalidateQueries({ queryKey: ['contact'] }),
  ])
  const setStatus = useMutation({
    mutationFn: ({ q, status }: { q: Quote; status: QuoteStatus }) =>
      api('PATCH', `/api/v1/quotes/${q.id}`, { status }, { 'If-Match': `"${q.version}"` }),
    onSettled: refresh,
  })
  const removeQuote = useMutation({ mutationFn: (q: Quote) => api('DELETE', `/api/v1/quotes/${q.id}`), onSettled: refresh })
  const removeCost = useMutation({ mutationFn: (c: Cost) => api('DELETE', `/api/v1/costs/${c.id}`), onSettled: refresh })
  const total = (costs.data ?? []).reduce((sum, c) => sum + c.amount_cents, 0)

  return (
    <section aria-label="Quotes and costs" className="space-y-3">
      <h2 className="text-lg font-semibold">Quotes and costs</h2>
      <ul className="space-y-2">
        {(quotes.data ?? []).map((q) => (
          <li key={q.id}>
            <Card className="flex flex-wrap items-center gap-2 py-3">
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{q.title}</span>
                <span className="block text-sm text-stone-500">
                  {q.contact_name ? <Link to={`/contacts/${q.contact_id}`} className="text-brand-700 dark:text-brand-100">{q.contact_name}</Link>
                    : q.contact_id ? 'A contact not shared with you' : 'No contact'}
                  {q.amount_cents !== null && ` · ${formatCents(q.amount_cents)}`}
                  {q.attachment_id && <> · <a href={`/api/v1/attachments/${q.attachment_id}/download`} download className="text-brand-700 dark:text-brand-100">{q.attachment_name ?? 'document'}</a></>}
                </span>
              </span>
              {canEdit ? (
                <select aria-label={`Status of ${q.title}`} className={select} value={q.status}
                  onChange={(e) => setStatus.mutate({ q, status: e.target.value as QuoteStatus })}>
                  {(Object.keys(STATUS_LABEL) as QuoteStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                </select>
              ) : (
                <span className="text-sm">{STATUS_LABEL[q.status]}</span>
              )}
              {canEdit && <Button variant="ghost" aria-label={`Delete quote ${q.title}`} onPress={() => removeQuote.mutate(q)}>✕</Button>}
            </Card>
          </li>
        ))}
      </ul>
      {canEdit && <AddQuote projectId={projectId} onAdded={refresh} />}

      <div className="space-y-2 pt-2">
        <div className="flex items-baseline justify-between">
          <h3 className="font-semibold">Spent</h3>
          <span className="font-semibold" aria-label="Total spent">{formatCents(total)}</span>
        </div>
        {(costs.data ?? []).length > 0 && (
          <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
            {(costs.data ?? []).map((c) => (
              <li key={c.id} className="flex items-center gap-2 px-3 py-1">
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{c.description}</span>
                  <span className="block text-xs text-stone-500">{new Date(`${c.spent_on}T12:00:00`).toLocaleDateString()}</span>
                </span>
                <span className="tabular-nums">{formatCents(c.amount_cents)}</span>
                {canEdit && <Button variant="ghost" aria-label={`Delete cost ${c.description}`} onPress={() => removeCost.mutate(c)}>✕</Button>}
              </li>
            ))}
          </ul>
        )}
        {canEdit && <AddCost projectId={projectId} quotes={quotes.data ?? []} onAdded={refresh} />}
      </div>
      <ErrorText error={setStatus.error ?? removeQuote.error ?? removeCost.error ?? quotes.error ?? costs.error} />
    </section>
  )
}

function AddQuote({ projectId, onAdded }: { projectId: string; onAdded: () => Promise<unknown> }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [contactId, setContactId] = useState('')
  const [amount, setAmount] = useState('')
  const [fileId, setFileId] = useState('')
  const contacts = useQuery({ queryKey: ['contacts'], queryFn: () => api<Contact[]>('GET', '/api/v1/contacts'), enabled: open })
  const files = useQuery({ queryKey: ['attachments', projectId], queryFn: () => api<FileItem[]>('GET', `/api/v1/projects/${projectId}/attachments`), enabled: open })
  const cents = amount.trim() ? parseAmount(amount) : null
  const amountOk = !amount.trim() || (cents !== null && cents >= 0)
  const add = useMutation({
    mutationFn: () => api('POST', `/api/v1/projects/${projectId}/quotes`, {
      title, contact_id: contactId || null, amount_cents: cents, attachment_id: fileId || null,
      status: cents !== null ? 'received' : 'requested',
    }),
    onSuccess: async () => { setTitle(''); setAmount(''); setContactId(''); setFileId(''); setOpen(false); await onAdded() },
  })
  if (!open) return <Button variant="secondary" onPress={() => setOpen(true)}>Add a quote</Button>
  return (
    <Card>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (title.trim() && amountOk) add.mutate() }}>
        <Field label="What for" isRequired maxLength={200} value={title} onChange={setTitle} />
        <div className="flex flex-wrap gap-2">
          <select aria-label="Contact" className={`${select} flex-1`} value={contactId} onChange={(e) => setContactId(e.target.value)}>
            <option value="">No contact</option>
            {(contacts.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <div className="w-36"><Field label="Amount (CAD)" inputMode="numeric" maxLength={16} value={amount} onChange={setAmount}
            description={amountOk ? 'Leave empty if requested' : 'Like 1850.00'} /></div>
        </div>
        {(files.data ?? []).length > 0 && (
          <select aria-label="Document" className={`${select} w-full`} value={fileId} onChange={(e) => setFileId(e.target.value)}>
            <option value="">No document</option>
            {(files.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.filename}</option>)}
          </select>
        )}
        <ErrorText error={add.error} />
        <div className="flex gap-2">
          <Button type="submit" isDisabled={!title.trim() || !amountOk || add.isPending}>Add quote</Button>
          <Button variant="ghost" onPress={() => setOpen(false)}>Cancel</Button>
        </div>
      </form>
    </Card>
  )
}

function AddCost({ projectId, quotes, onAdded }: { projectId: string; quotes: Quote[]; onAdded: () => Promise<unknown> }) {
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [quoteId, setQuoteId] = useState('')
  const cents = parseAmount(amount)
  const add = useMutation({
    mutationFn: () => api('POST', `/api/v1/projects/${projectId}/costs`, { description, amount_cents: cents, quote_id: quoteId || null }),
    onSuccess: async () => { setDescription(''); setAmount(''); setQuoteId(''); await onAdded() },
  })
  const accepted = quotes.filter((q) => q.status === 'accepted')
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (description.trim() && cents !== null) add.mutate() }}>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1"><Field label="Money spent on" maxLength={300} value={description} onChange={setDescription} /></div>
        <div className="w-32"><Field label="Amount (CAD)" inputMode="numeric" maxLength={16} value={amount} onChange={setAmount} /></div>
      </div>
      {accepted.length > 0 && (
        <select aria-label="Paid for quote" className={`${select} w-full`} value={quoteId} onChange={(e) => setQuoteId(e.target.value)}>
          <option value="">Not for a quote</option>
          {accepted.map((q) => <option key={q.id} value={q.id}>{q.title}</option>)}
        </select>
      )}
      <ErrorText error={add.error} />
      <Button type="submit" variant="secondary" isDisabled={!description.trim() || cents === null || add.isPending}>Add cost</Button>
    </form>
  )
}
