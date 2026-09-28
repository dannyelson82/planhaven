import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, uploadFile } from '../api.ts'
import { cachedGet } from '../offline.ts'
import { formatCents, parseAmount, type QuoteStatus, STATUS_LABEL } from '../money.ts'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'
import type { Contact, Quote } from './Contacts.tsx'
import type { ListSummary } from './Lists.tsx'

type Cost = { id: string; description: string; amount_cents: number; spent_on: string; quote_id: string | null }
type FileItem = { id: string; filename: string }

/** Upload a document (an estimate, a receipt) to the project's files; returns it. */
function uploadToProject(projectId: string, file: File): Promise<FileItem> {
  const params = new URLSearchParams({ filename: file.name || 'document' })
  return uploadFile<FileItem>(`/api/v1/projects/${projectId}/attachments?${params}`, file)
}
const DOCUMENT_TYPES = 'application/pdf,image/*,.heic,.heif'

const select = 'min-h-11 min-w-0 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900'

function useMoney(projectId: string) {
  const client = useQueryClient()
  const quotes = useQuery({ queryKey: ['quotes', projectId], queryFn: () => api<Quote[]>('GET', `/api/v1/projects/${projectId}/quotes`) })
  const costs = useQuery({ queryKey: ['costs', projectId], queryFn: () => api<Cost[]>('GET', `/api/v1/projects/${projectId}/costs`) })
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['quotes', projectId] }),
    client.invalidateQueries({ queryKey: ['costs', projectId] }),
    client.invalidateQueries({ queryKey: ['contact'] }),
  ])
  return { quotes, costs, refresh }
}

/** Quotes from contractors on a project page (added from the project's add bar). */
export function ProjectQuotes({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const { quotes, refresh } = useMoney(projectId)
  const setStatus = useMutation({
    mutationFn: ({ q, status }: { q: Quote; status: QuoteStatus }) =>
      api('PATCH', `/api/v1/quotes/${q.id}`, { status }, { 'If-Match': `"${q.version}"` }),
    onSettled: refresh,
  })
  const removeQuote = useMutation({ mutationFn: (q: Quote) => api('DELETE', `/api/v1/quotes/${q.id}`), onSettled: refresh })
  return (
    <section aria-label="Quotes" className="space-y-3">
      <h2 className="text-lg font-semibold">Quotes</h2>
      {quotes.data?.length === 0 && <p className="text-sm text-stone-500">No quotes yet.</p>}
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
              {canEdit && !q.attachment_id && <AttachEstimate projectId={projectId} quote={q} onDone={refresh} />}
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
      <ErrorText error={setStatus.error ?? removeQuote.error ?? quotes.error} />
    </section>
  )
}

/** Money spent on a project, and the budget: accepted quotes plus list estimates vs. spent. */
export function ProjectCosts({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const { quotes, costs, refresh } = useMoney(projectId)
  const removeCost = useMutation({ mutationFn: (c: Cost) => api('DELETE', `/api/v1/costs/${c.id}`), onSettled: refresh })
  const total = (costs.data ?? []).reduce((sum, c) => sum + c.amount_cents, 0)
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => cachedGet<ListSummary[]>(`/api/v1/projects/${projectId}/lists`) })
  const quoted = (quotes.data ?? []).filter((q) => q.status === 'accepted').reduce((sum, q) => sum + (q.amount_cents ?? 0), 0)
  const listed = (lists.data ?? []).filter((l) => l.kind !== 'checklist').reduce((sum, l) => sum + (l.estimated_cents ?? 0), 0)
  const planned = quoted + listed
  return (
    <section aria-label="Costs" className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Costs</h2>
        <span className="font-semibold" aria-label="Total spent">{formatCents(total)}</span>
      </div>
      {(planned > 0 || total > 0) && (
        <dl aria-label="Budget" className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 rounded-2xl bg-white p-4 ring-1 ring-stone-200 dark:bg-stone-900 dark:ring-stone-800">
          <dt className="text-stone-600 dark:text-stone-400">Accepted quotes</dt><dd className="text-right tabular-nums">{formatCents(quoted)}</dd>
          <dt className="text-stone-600 dark:text-stone-400">Lists (estimated)</dt><dd className="text-right tabular-nums">{formatCents(listed)}</dd>
          <dt className="font-semibold">Planned</dt><dd className="text-right font-semibold tabular-nums" aria-label="Planned total">{formatCents(planned)}</dd>
          <dt className="text-stone-600 dark:text-stone-400">Spent</dt><dd className="text-right tabular-nums">{formatCents(total)}</dd>
          {total > planned ? (
            <><dt className="font-semibold text-red-700 dark:text-red-400">Over by</dt><dd className="text-right font-semibold tabular-nums text-red-700 dark:text-red-400">{formatCents(total - planned)}</dd></>
          ) : (
            <><dt className="font-semibold">Left</dt><dd className="text-right font-semibold tabular-nums" aria-label="Left to spend">{formatCents(planned - total)}</dd></>
          )}
        </dl>
      )}
      {costs.data?.length === 0 && <p className="text-sm text-stone-500">Nothing spent yet.</p>}
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
      <ErrorText error={removeCost.error ?? costs.error} />
    </section>
  )
}

/** New quote (in the project's add bar). */
export function AddQuote({ projectId }: { projectId: string }) {
  const { refresh: onAdded } = useMoney(projectId)
  const [title, setTitle] = useState('')
  const [contactId, setContactId] = useState('')
  const [amount, setAmount] = useState('')
  const [fileId, setFileId] = useState('')
  const contacts = useQuery({ queryKey: ['contacts'], queryFn: () => api<Contact[]>('GET', '/api/v1/contacts') })
  const files = useQuery({ queryKey: ['attachments', projectId], queryFn: () => api<FileItem[]>('GET', `/api/v1/projects/${projectId}/attachments`) })
  const cents = amount.trim() ? parseAmount(amount) : null
  const amountOk = !amount.trim() || (cents !== null && cents >= 0)
  const client = useQueryClient()
  const pick = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: (file: File) => uploadToProject(projectId, file),
    onSuccess: async (file) => { await client.invalidateQueries({ queryKey: ['attachments', projectId] }); setFileId(file.id) },
  })
  const add = useMutation({
    mutationFn: () => api('POST', `/api/v1/projects/${projectId}/quotes`, {
      title, contact_id: contactId || null, amount_cents: cents, attachment_id: fileId || null,
      status: cents !== null ? 'received' : 'requested',
    }),
    onSuccess: async () => { setTitle(''); setAmount(''); setContactId(''); setFileId(''); await onAdded() },
  })
  return (
    <div>
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
        <div className="flex flex-wrap items-center gap-2">
          {(files.data ?? []).length > 0 && (
            <select aria-label="Document" className={`${select} min-w-0 flex-1`} value={fileId} onChange={(e) => setFileId(e.target.value)}>
              <option value="">No document</option>
              {(files.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.filename}</option>)}
            </select>
          )}
          <Button variant="secondary" onPress={() => pick.current?.click()} isDisabled={upload.isPending}>
            {upload.isPending ? 'Uploading…' : 'Upload the estimate'}
          </Button>
          <input ref={pick} type="file" accept={DOCUMENT_TYPES} hidden aria-label="Choose the estimate file"
            onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) upload.mutate(file) }} />
        </div>
        <ErrorText error={upload.error} />
        <ErrorText error={add.error} />
        <div className="flex gap-2">
          <Button type="submit" isDisabled={!title.trim() || !amountOk || add.isPending}>Add quote</Button>
        </div>
      </form>
    </div>
  )
}

/** Money spent (in the project's add bar); may be for an accepted quote. */
export function AddCost({ projectId }: { projectId: string }) {
  const { quotes: quoteQuery, refresh: onAdded } = useMoney(projectId)
  const quotes = quoteQuery.data ?? []
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

/** A quote without its document yet: upload the estimate and link it. */
function AttachEstimate({ projectId, quote, onDone }: { projectId: string; quote: Quote; onDone: () => Promise<unknown> }) {
  const client = useQueryClient()
  const pick = useRef<HTMLInputElement>(null)
  const attach = useMutation({
    mutationFn: async (file: File) => {
      const doc = await uploadToProject(projectId, file)
      await api('PATCH', `/api/v1/quotes/${quote.id}`, { attachment_id: doc.id }, { 'If-Match': `"${quote.version}"` })
    },
    onSettled: async () => { await client.invalidateQueries({ queryKey: ['attachments', projectId] }); await onDone() },
  })
  return (
    <>
      <Button variant="ghost" onPress={() => pick.current?.click()} isDisabled={attach.isPending}>
        {attach.isPending ? 'Uploading…' : 'Attach estimate'}
      </Button>
      <input ref={pick} type="file" accept={DOCUMENT_TYPES} hidden aria-label={`Choose the estimate for ${quote.title}`}
        onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) attach.mutate(file) }} />
      <ErrorText error={attach.error} />
    </>
  )
}
