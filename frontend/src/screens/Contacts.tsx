import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, uploadFile } from '../api.ts'
import { formatCents, type QuoteStatus, STATUS_LABEL } from '../money.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'
import { MailIcon, PhoneIcon, SearchIcon } from '../icons.tsx'
import { ShareButton } from './Sharing.tsx'

// A website may be typed without https:// (www.example.com); it's added when saving. Only
// web addresses are accepted (the server allows only http:// and https:// links).
const WEBSITE = /^(https?:\/\/)?[^\s/:]+\.[^\s]+$/i
function withScheme(website: string): string {
  const w = website.trim()
  return !w || /^https?:\/\//i.test(w) ? w : `https://${w}`
}
/** Search: every word must appear in the name, company, email, notes or phone (digits). */
function matches(c: Contact, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const text = [c.name, c.company, c.email, c.notes, KIND_LABEL[c.kind]].join(' ').toLowerCase()
  const digits = c.phone.replace(/\D/g, '')
  return words.every((w) => text.includes(w) || (/\d/.test(w) && digits.includes(w.replace(/\D/g, ''))))
}
const telHref = (phone: string) => `tel:${phone.replace(/[^\d+]/g, '')}`
const iconLink = 'inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl text-brand-700 hover:bg-stone-100 dark:text-brand-100 dark:hover:bg-stone-800'

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
  has_photo: boolean
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
  const [query, setQuery] = useState('')
  const shown = (contacts.data ?? []).filter((c) => matches(c, query))
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Contacts</h1>
      <p className="text-stone-600 dark:text-stone-400">Contractors and suppliers. Each contact is private to you until you share it.</p>
      {(contacts.data ?? []).length > 0 && (
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-3 text-stone-500"><SearchIcon /></span>
          <input type="search" aria-label="Search contacts" placeholder="Search by name, company, phone, email or notes"
            value={query} onChange={(e) => setQuery(e.target.value)} maxLength={100}
            className="min-h-11 w-full rounded-xl border border-stone-300 bg-white py-2.5 pl-10 pr-3 dark:border-stone-700 dark:bg-stone-900" />
        </div>
      )}
      <ul className="grid gap-2 sm:grid-cols-2">
        {shown.map((c) => (
          <li key={c.id}>
            <Card>
              <div className="flex items-start gap-1">
                {c.has_photo && (
                  <img src={`/api/v1/contacts/${c.id}/photo/thumbnail?v=${c.version}`} alt="" loading="lazy"
                    className="mr-2 size-12 shrink-0 rounded-full bg-stone-200 object-cover dark:bg-stone-800" />
                )}
                <div className="min-w-0 flex-1">
                  <Link to={`/contacts/${c.id}`} className="block font-semibold">{c.name}</Link>
                  <p className="text-sm text-stone-500">{[KIND_LABEL[c.kind], c.company, c.phone].filter(Boolean).join(' · ')}</p>
                </div>
                {c.phone && <a href={telHref(c.phone)} aria-label={`Call ${c.phone}`} className={iconLink}><PhoneIcon /></a>}
                {c.email && <a href={`mailto:${c.email}`} aria-label={`Email ${c.email}`} className={iconLink}><MailIcon /></a>}
              </div>
            </Card>
          </li>
        ))}
      </ul>
      {contacts.data?.length === 0 && <p className="text-sm text-stone-500">No contacts yet.</p>}
      {(contacts.data ?? []).length > 0 && shown.length === 0 && <p className="text-sm text-stone-500">No contacts match “{query.trim()}”.</p>}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate() }}>
        <div className="min-w-0 flex-1"><Field label="New contact" maxLength={200} value={name} onChange={setName} /></div>
        <select aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value as Kind)} className={select}>
          {(Object.keys(KIND_LABEL) as Kind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <Button type="submit" variant="secondary" isDisabled={create.isPending}>Add contact</Button>
      </form>
      <ImportContact kind={kind} />
      <ErrorText error={create.error ?? contacts.error} />
    </div>
  )
}

type PickedContact = { name?: string[]; email?: string[]; tel?: string[] }
type ContactsManager = { select: (props: string[], options?: { multiple?: boolean }) => Promise<PickedContact[]> }

/** A contact from the phone: a contact card (.vcf) shared or saved from its Contacts app, or
 * (Android) picked straight from the phone's contacts. */
function ImportContact({ kind }: { kind: Kind }) {
  const pick = useRef<HTMLInputElement>(null)
  const phoneContacts = (navigator as Navigator & { contacts?: ContactsManager }).contacts
  const fromFile = useMutation({
    mutationFn: (file: File) => uploadFile<Contact>(`/api/v1/contacts/import?kind=${kind}`, file),
    onSuccess: (c) => navigate(`/contacts/${c.id}`),
  })
  const fromPicker = useMutation({
    mutationFn: async () => {
      const [picked] = await phoneContacts!.select(['name', 'email', 'tel'], { multiple: false })
      if (!picked?.name?.[0]) return null
      return api<Contact>('POST', '/api/v1/contacts', {
        name: picked.name[0].slice(0, 200), kind,
        phone: (picked.tel?.[0] ?? '').slice(0, 50), email: (picked.email?.[0] ?? '').slice(0, 254),
      })
    },
    onSuccess: (c) => { if (c) navigate(`/contacts/${c.id}`) },
  })
  return (
    <Card className="space-y-2">
      <h2 className="font-semibold">From your phone</h2>
      <p className="text-sm text-stone-600 dark:text-stone-400">
        In your phone's Contacts, share the contact (iPhone: Share Contact, then Save to Files), then choose that file here.
        The type chosen above is used.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onPress={() => pick.current?.click()} isDisabled={fromFile.isPending}>
          {fromFile.isPending ? 'Importing…' : 'Import a contact card'}
        </Button>
        {phoneContacts && (
          <Button variant="secondary" onPress={() => fromPicker.mutate()} isDisabled={fromPicker.isPending}>Pick from phone contacts</Button>
        )}
      </div>
      <input ref={pick} type="file" accept=".vcf,text/vcard,text/x-vcard" hidden aria-label="Choose a contact card"
        onChange={(e) => { const file = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (file) fromFile.mutate(file) }} />
      <ErrorText error={fromFile.error ?? fromPicker.error} />
    </Card>
  )
}

/** One contact: details, sharing, and their quotes on projects you can see. */
export function ContactScreen({ id, myId }: { id: string; myId: string }) {
  const contact = useQuery({ queryKey: ['contact', id], queryFn: () => api<Contact>('GET', `/api/v1/contacts/${id}`) })
  // The photo upload lives out here, not in the (re-keyed) form, so a photo picked while the
  // form refreshes isn't lost.
  const client = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ['contact', id] }),
    client.invalidateQueries({ queryKey: ['contacts'] }),
  ])
  const upload = useMutation({ mutationFn: (file: File) => uploadFile(`/api/v1/contacts/${id}/photo`, file, 'PUT'), onSettled: refresh })
  const removePhoto = useMutation({ mutationFn: () => api('DELETE', `/api/v1/contacts/${id}/photo`), onSettled: refresh })
  if (contact.error) return <ErrorText error={contact.error} />
  if (!contact.data) return <p className="text-stone-500">Loading…</p>
  const photo: PhotoControls = {
    pick: () => input.current?.click(),
    remove: () => removePhoto.mutate(),
    busy: upload.isPending || removePhoto.isPending,
    uploading: upload.isPending,
    error: upload.error ?? removePhoto.error,
  }
  return (
    <>
      <ContactDetail key={contact.data.version} contact={contact.data} myId={myId} photo={photo} />
      <input ref={input} type="file" accept="image/*,.heic,.heif" hidden aria-label="Choose a photo" data-testid="contact-photo-input"
        onChange={(e) => { const f = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (f) upload.mutate(f) }} />
    </>
  )
}

type PhotoControls = { pick: () => void; remove: () => void; busy: boolean; uploading: boolean; error: unknown }

/** The contact's photo on its page, with Add / Change / Remove for editors. No photo, no box. */
function ContactPhoto({ contact, canEdit, photo }: { contact: Contact; canEdit: boolean; photo: PhotoControls }) {
  if (!contact.has_photo && !canEdit) return null
  return (
    <div className="flex flex-wrap items-center gap-3">
      {contact.has_photo && (
        <img src={`/api/v1/contacts/${contact.id}/photo?v=${contact.version}`} alt={contact.name}
          className="size-28 rounded-2xl bg-stone-200 object-cover dark:bg-stone-800" />
      )}
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onPress={photo.pick} isDisabled={photo.busy}>
            {photo.uploading ? 'Uploading…' : contact.has_photo ? 'Change photo' : 'Add a photo'}
          </Button>
          {contact.has_photo && <Button variant="danger-ghost" onPress={photo.remove} isDisabled={photo.busy}>Remove photo</Button>}
        </div>
      )}
      <ErrorText error={photo.error} />
    </div>
  )
}

function ContactDetail({ contact, myId, photo }: { contact: Contact; myId: string; photo: PhotoControls }) {
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
    mutationFn: () => api('PUT', `/api/v1/contacts/${contact.id}`, { ...form, website: withScheme(form.website) }, { 'If-Match': `"${contact.version}"` }),
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: ['contact', contact.id] }), client.invalidateQueries({ queryKey: ['contacts'] })]),
  })
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/contacts/${contact.id}`),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['contacts'] }); navigate('/contacts') },
  })
  const websiteOk = !form.website.trim() || WEBSITE.test(form.website.trim())

  return (
    <div className="space-y-4">
      <Link to="/contacts" className="text-sm text-brand-700 dark:text-brand-100">← All contacts</Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{contact.name}</h1>
        <ShareButton kind="contact" id={contact.id} isOwner={contact.role === 'owner'} myId={myId} />
      </div>
      <ContactPhoto contact={contact} canEdit={canEdit} photo={photo} />
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
            <Field label="Website" inputMode="url" maxLength={492} value={form.website} onChange={(v) => set({ website: v })}
              description={websiteOk ? undefined : 'Enter a web address, like www.example.com'} />
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
        <div className="flex flex-wrap gap-2">
            {contact.phone && <a href={telHref(contact.phone)} className="inline-flex min-h-11 items-center rounded-xl px-4 font-medium text-brand-700 ring-1 ring-stone-300 dark:text-brand-100 dark:ring-stone-700">Call</a>}
            {contact.email && <a href={`mailto:${contact.email}`} className="inline-flex min-h-11 items-center rounded-xl px-4 font-medium text-brand-700 ring-1 ring-stone-300 dark:text-brand-100 dark:ring-stone-700">Email</a>}
            {/* A contact card (.vcf): the phone offers to add it to its contacts. */}
            <a href={`/api/v1/contacts/${contact.id}/vcard`} download className="inline-flex min-h-11 items-center rounded-xl px-4 font-medium text-brand-700 ring-1 ring-stone-300 dark:text-brand-100 dark:ring-stone-700">Save to phone</a>
          </div>
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
