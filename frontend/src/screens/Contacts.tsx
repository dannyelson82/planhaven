import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { formatCents, type QuoteStatus, STATUS_LABEL } from '../money.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'
import { ShareButton } from './Sharing.tsx'

type Kind = 'contractor' | 'supplier' | 'other'
export type Quote = {
  id: string
  project_id: string
  project_title: string
  title: string
  amount_cents: number | null
  status: QuoteStatus
  notes: string
  contact_id: string | null
  contact_name: string | null
  attachment_id: string | null
  attachment_name: string | null
  version: number
}
export type { QuoteStatus }
export type Contact = {
  id: string
  name: string
  company: string
  kind: Kind
  phone: string
  email: string
  website: string
  notes: string
  role: 'owner' | 'editor' | 'viewer' | null
  version: number
  quotes?: Quote[] | null
}

const KIND_LABEL: Record<Kind, string> = { contractor: 'Contractor', supplier: 'Supplier', other: 'Other' }
const select = 'min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900'

/** Contractors and suppliers you've shared with each other. */
export function ContactsScreen() {
  const contacts = useQuery({ queryKey: ['contacts'], queryFn: () => api<Contact[]>('GET', '/api/v1/contacts') })
  const [name, setName] = useState('')
  const [kind, setKind] = useState<Kind>('contractor')
  const create = useMutation({
    mutationFn: () => api<Contact>('POST', '/api/v1/contacts', { name, kind }),
    onSuccess: (c) => navigate(`/contacts/${c.id}`),
  })
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Contacts</h1>
      <p className="text-stone-600 dark:text-stone-400">Contractors and suppliers. Each contact is private to you until you share it.</p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {(contacts.data ?? []).map((c) => (
          <li key={c.id}>
            <Card>
              <Link to={`/contacts/${c.id}`} className="block font-semibold">{c.name}</Link>
              <p className="text-sm text-stone-500">{[KIND_LABEL[c.kind], c.company, c.phone].filter(Boolean).join(' · ')}</p>
            </Card>
          </li>
        ))}
      </ul>
      {contacts.data?.length === 0 && <p className="text-sm text-stone-500">No contacts yet.</p>}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate() }}>
        <div className="min-w-0 flex-1"><Field label="New contact" maxLength={200} value={name} onChange={setName} /></div>
        <select aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value as Kind)} className={select}>
          {(Object.keys(KIND_LABEL) as Kind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <Button type="submit" variant="secondary" isDisabled={create.isPending}>Add contact</Button>
      </form>
      <ErrorText error={create.error ?? contacts.error} />
    </div>
  )
}

/** One contact: details, sharing, and their quotes on projects you can see. */
export function ContactScreen({ id, myId }: { id: string; myId: string }) {
  const contact = useQuery({ queryKey: ['contact', id], queryFn: () => api<Contact>('GET', `/api/v1/contacts/${id}`) })
  if (contact.error) return <ErrorText error={contact.error} />
  if (!contact.data) return <p className="text-stone-500">Loading…</p>
  return <ContactDetail key={contact.data.version} contact={contact.data} myId={myId} />
}

function ContactDetail({ contact, myId }: { contact: Contact; myId: string }) {
  const client = useQueryClient()
  const canEdit = contact.role === 'owner' || contact.role === 'editor'
  const [form, setForm] = useState({
    name: contact.name, company: contact.company, kind: contact.kind, phone: contact.phone,
    email: contact.email, website: contact.website, notes: contact.notes,
  })
  const [confirmDelete, setConfirmDelete] = useState(false)
  const set = (part: Partial<typeof form>) => setForm({ ...form, ...part })
  const dirty = (Object.keys(form) as (keyof typeof form)[]).some((k) => form[k] !== contact[k])
  const save = useMutation({
    mutationFn: () => api('PUT', `/api/v1/contacts/${contact.id}`, form, { 'If-Match': `"${contact.version}"` }),
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: ['contact', contact.id] }), client.invalidateQueries({ queryKey: ['contacts'] })]),
  })
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/contacts/${contact.id}`),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['contacts'] }); navigate('/contacts') },
  })
  const websiteOk = !form.website || /^https?:\/\/\S+$/.test(form.website)

  return (
    <div className="space-y-4">
      <Link to="/contacts" className="text-sm text-brand-700 dark:text-brand-100">← All contacts</Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{contact.name}</h1>
        <ShareButton kind="contact" id={contact.id} isOwner={contact.role === 'owner'} myId={myId} />
      </div>
      <Card className="space-y-3">
        {canEdit ? (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-0 flex-1"><Field label="Name" isRequired maxLength={200} value={form.name} onChange={(v) => set({ name: v })} /></div>
              <select aria-label="Type" value={form.kind} onChange={(e) => set({ kind: e.target.value as Kind })} className={select}>
                {(Object.keys(KIND_LABEL) as Kind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
              </select>
            </div>
            <Field label="Company" maxLength={200} value={form.company} onChange={(v) => set({ company: v })} />
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Phone" type="tel" maxLength={50} value={form.phone} onChange={(v) => set({ phone: v })} />
              <Field label="Email" type="email" maxLength={254} value={form.email} onChange={(v) => set({ email: v })} />
            </div>
            <Field label="Website" type="url" maxLength={500} value={form.website} onChange={(v) => set({ website: v })}
              description={websiteOk ? undefined : 'Start with https://'} />
            <Field label="Notes" multiline maxLength={20000} value={form.notes} onChange={(v) => set({ notes: v })} />
            <div className="flex flex-wrap gap-2">
              <Button onPress={() => save.mutate()} isDisabled={!dirty || !form.name.trim() || !websiteOk || save.isPending}>Save</Button>
              {contact.role === 'owner' && (
                <Button variant="danger-ghost" onPress={() => (confirmDelete ? remove.mutate() : setConfirmDelete(true))} isDisabled={remove.isPending}>
                  {confirmDelete ? 'Tap again to delete this contact' : 'Delete contact'}
                </Button>
              )}
            </div>
          </>
        ) : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            {([['Company', contact.company], ['Phone', contact.phone], ['Email', contact.email], ['Website', contact.website]] as const)
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-stone-500">{k}</dt><dd className="break-words">{v}</dd></div>
              ))}
          </dl>
        )}
        {(contact.phone || contact.email) && (
          <div className="flex flex-wrap gap-2">
            {contact.phone && <a href={`tel:${contact.phone.replace(/[^\d+]/g, '')}`} className="inline-flex min-h-11 items-center rounded-xl px-4 font-medium text-brand-700 ring-1 ring-stone-300 dark:text-brand-100 dark:ring-stone-700">Call</a>}
            {contact.email && <a href={`mailto:${contact.email}`} className="inline-flex min-h-11 items-center rounded-xl px-4 font-medium text-brand-700 ring-1 ring-stone-300 dark:text-brand-100 dark:ring-stone-700">Email</a>}
          </div>
        )}
        <ErrorText error={save.error ?? remove.error} />
      </Card>
      <section aria-label="Quotes" className="space-y-2">
        <h2 className="text-lg font-semibold">Quotes</h2>
        {(contact.quotes ?? []).length === 0 && <p className="text-sm text-stone-500">No quotes from this contact on your projects.</p>}
        <ul className="space-y-2">
          {(contact.quotes ?? []).map((q) => (
            <li key={q.id}>
              <Card className="flex flex-wrap items-center justify-between gap-2 py-3">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{q.title}</span>
                  <Link to={`/projects/${q.project_id}`} className="text-sm text-brand-700 dark:text-brand-100">{q.project_title}</Link>
                </span>
                <span className="text-sm text-stone-500">{q.amount_cents !== null ? formatCents(q.amount_cents) : '—'} · {STATUS_LABEL[q.status]}</span>
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
