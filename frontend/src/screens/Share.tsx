// What someone with a share link sees (ADR 0015): no account, no menu, only what the link was
// given. The token comes after '#' in the link, so it never reaches the server's logs; it's
// read once, sent to open the link, and removed from the address bar.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, ApiError, uploadFile } from '../api.ts'
import { AuthPage, Button, Card, ErrorText, Field, Form } from '../ui.tsx'

type Line = { kind: 'text' | 'heading' | 'bullet' | 'check'; text: string; depth: number; marker: string | null; checked: boolean | null }
type View = {
  link_name: string
  guest_name: string
  project_title: string
  allowed: { tick_tasks: boolean; tick_items: boolean; add_photos: boolean }
  tasks: { id: string; title: string; notes: string; done: boolean }[]
  notes: { id: string; title: string; lines: Line[]; can_add: boolean }[]
  lists: { id: string; title: string; kind: string; items: { id: string; text: string; quantity: string | null; unit: string | null; checked: boolean }[] }[]
  files: { id: string; filename: string; size: number; is_photo: boolean }[]
  files_shown: boolean
}

function takeToken(): string {
  const token = window.location.hash.slice(1)
  if (token) window.history.replaceState(null, '', '/s') // out of the address bar and history
  return token
}

export function GuestScreen() {
  const [token] = useState(takeToken)
  const view = useQuery({
    queryKey: ['share-view'],
    queryFn: () => api<View>('GET', '/api/v1/share/view'),
    retry: false,
  })
  if (view.isPending) return <p className="p-6 text-stone-500">Loading…</p>
  if (view.data) return <SharedPage view={view.data} />
  if (!token) {
    return (
      <AuthPage title="This link doesn't work">
        <p>Open the whole link you were sent (it's long, with a # in it). If it still doesn't work, it may have expired or been turned off: ask the person who sent it.</p>
      </AuthPage>
    )
  }
  return <OpenLink token={token} />
}

function OpenLink({ token }: { token: string }) {
  const client = useQueryClient()
  const [name, setName] = useState('')
  const [pin, setPin] = useState('')
  const [needsPin, setNeedsPin] = useState(false)
  const open = useMutation({
    mutationFn: () => api('POST', '/api/v1/share/open', { token, name: name.trim(), ...(pin ? { pin } : {}) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['share-view'] }),
    onError: (e) => { if (e instanceof ApiError && e.status === 401) setNeedsPin(true) },
  })
  const dead = open.error instanceof ApiError && open.error.status === 404
  return (
    <AuthPage title="Shared with you">
      {dead ? (
        <p>This link doesn't work any more: it may have expired or been turned off. Ask the person who sent it.</p>
      ) : (
        <Form onSubmit={(e) => { e.preventDefault(); if (name.trim()) open.mutate() }}>
          <p className="text-stone-600 dark:text-stone-400">Someone shared part of a project with you. What you do here is shown with your name.</p>
          <Field label="Your name" isRequired maxLength={60} value={name} onChange={setName} />
          {needsPin && (
            <Field label="PIN" inputMode="numeric" maxLength={6} value={pin} onChange={(v) => setPin(v.replace(/\D/g, ''))}
              description="The 6-digit PIN you were sent separately" />
          )}
          {open.error && !(open.error instanceof ApiError && open.error.status === 401 && !pin) && <ErrorText error={open.error} />}
          <Button type="submit" className="w-full" isDisabled={!name.trim() || open.isPending || (needsPin && pin.length !== 6)}>Open</Button>
        </Form>
      )}
    </AuthPage>
  )
}

function SharedPage({ view: v }: { view: View }) {
  const client = useQueryClient()
  const refresh = () => client.invalidateQueries({ queryKey: ['share-view'] })
  const tickTask = useMutation({ mutationFn: ({ id, done }: { id: string; done: boolean }) => api('POST', `/api/v1/share/tasks/${id}`, { done }), onSettled: refresh })
  const tickItem = useMutation({ mutationFn: ({ id, checked }: { id: string; checked: boolean }) => api('POST', `/api/v1/share/list-items/${id}`, { checked }), onSettled: refresh })
  const leave = useMutation({ mutationFn: () => api('POST', '/api/v1/share/leave'), onSettled: () => { client.clear(); window.location.assign('/s') } })
  const photos = v.files.filter((f) => f.is_photo)
  const others = v.files.filter((f) => !f.is_photo)
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 pb-16 pt-[max(1rem,env(safe-area-inset-top))]">
      <header className="space-y-1">
        <p className="text-sm font-semibold uppercase tracking-wider text-brand-600">PlanHaven</p>
        <h1 className="text-2xl font-bold">{v.project_title}</h1>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Shared with {v.guest_name} through the link “{v.link_name}”. What you do here is shown with your name.
        </p>
      </header>

      {v.tasks.length > 0 && (
        <section aria-label="Tasks" className="space-y-2">
          <h2 className="text-lg font-semibold">Tasks</h2>
          <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
            {v.tasks.map((t) => (
              <li key={t.id} className="px-3 py-2">
                <label className="flex min-h-11 items-start gap-3">
                  <TickBox key={`${t.id}-${t.done}`} saved={t.done} disabled={!v.allowed.tick_tasks} className="mt-1"
                    onChange={(done) => tickTask.mutate({ id: t.id, done })} />
                  <span className="min-w-0">
                    <span className={`block ${t.done ? 'text-stone-500 line-through' : ''}`}>{t.title}</span>
                    {t.notes && <span className="block whitespace-pre-line text-sm text-stone-600 dark:text-stone-400">{t.notes}</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <ErrorText error={tickTask.error} />
        </section>
      )}

      {v.notes.map((n) => <SharedNote key={n.id} note={n} onAdded={refresh} />)}

      {v.lists.map((l) => (
        <section key={l.id} aria-label={`List: ${l.title}`} className="space-y-2">
          <h2 className="text-lg font-semibold">{l.title}</h2>
          <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
            {l.items.map((i) => (
              <li key={i.id} className="px-3">
                <label className="flex min-h-12 items-center gap-3">
                  <TickBox key={`${i.id}-${i.checked}`} saved={i.checked} disabled={!v.allowed.tick_items}
                    onChange={(checked) => tickItem.mutate({ id: i.id, checked })} />
                  <span className={`min-w-0 flex-1 ${i.checked ? 'text-stone-500 line-through' : ''}`}>{i.text}</span>
                  {i.quantity && <span className="text-sm text-stone-500">{String(Number(i.quantity))}{i.unit ? ` ${i.unit}` : ''}</span>}
                </label>
              </li>
            ))}
          </ul>
          <ErrorText error={tickItem.error} />
        </section>
      ))}

      {(v.files_shown || v.allowed.add_photos) && (
        <section aria-label="Photos and files" className="space-y-2">
          <h2 className="text-lg font-semibold">Photos and files</h2>
          {photos.length > 0 && (
            <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
              {photos.map((f) => (
                <li key={f.id}>
                  <a href={`/api/v1/share/files/${f.id}/view`} target="_blank" rel="noopener noreferrer">
                    <img src={`/api/v1/share/files/${f.id}/thumbnail`} alt={f.filename} loading="lazy" className="aspect-square w-full rounded-xl bg-stone-200 object-cover dark:bg-stone-800" />
                  </a>
                </li>
              ))}
            </ul>
          )}
          {others.map((f) => (
            <p key={f.id}><a href={`/api/v1/share/files/${f.id}/download`} download className="font-medium text-brand-700 underline dark:text-brand-100">{f.filename}</a></p>
          ))}
          {v.allowed.add_photos && <AddPhotos onAdded={refresh} />}
        </section>
      )}

      <Button variant="ghost" onPress={() => leave.mutate()}>Done: close this link on this device</Button>
    </main>
  )
}

function SharedNote({ note, onAdded }: { note: View['notes'][number]; onAdded: () => Promise<unknown> }) {
  const [text, setText] = useState('')
  const add = useMutation({
    mutationFn: () => api('POST', `/api/v1/share/notes/${note.id}/add`, { text: text.trim() }),
    onSuccess: async () => { setText(''); await onAdded() },
  })
  return (
    <section aria-label={`Note: ${note.title}`} className="space-y-2">
      <h2 className="text-lg font-semibold">{note.title}</h2>
      <Card className="space-y-1">
        {note.lines.length === 0 && <p className="text-stone-500">Nothing here yet.</p>}
        {note.lines.map((l, i) => (
          <p key={i} className={`whitespace-pre-line ${l.kind === 'heading' ? 'font-semibold' : ''} ${l.depth ? 'pl-6' : ''}`}>
            {l.kind === 'check' ? (l.checked ? '☑ ' : '☐ ') : l.kind === 'bullet' ? `${l.marker} ` : ''}{l.text}
          </p>
        ))}
      </Card>
      {note.can_add && (
        <Form onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate() }}>
          <Field label={`Add to “${note.title}”`} multiline maxLength={4000} value={text} onChange={setText}
            description="Added at the end with your name and today's date. What's already there stays as it is." />
          <ErrorText error={add.error} />
          <Button type="submit" isDisabled={!text.trim() || add.isPending}>Add</Button>
        </Form>
      )}
    </section>
  )
}

function AddPhotos({ onAdded }: { onAdded: () => Promise<unknown> }) {
  const camera = useRef<HTMLInputElement>(null)
  const pick = useRef<HTMLInputElement>(null)
  const [progress, setProgress] = useState<string | null>(null)
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const [i, file] of files.entries()) {
        setProgress(files.length > 1 ? `Uploading ${i + 1} of ${files.length}…` : 'Uploading…')
        await uploadFile(`/api/v1/share/files?${new URLSearchParams({ filename: file.name || 'photo.jpg' })}`, file)
      }
    },
    onSettled: async () => { setProgress(null); await onAdded() },
  })
  const onFiles = (el: HTMLInputElement) => { const files = [...(el.files ?? [])]; el.value = ''; if (files.length) upload.mutate(files) }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onPress={() => camera.current?.click()} isDisabled={upload.isPending} className="md:hidden">Take photo</Button>
        <Button variant="secondary" onPress={() => pick.current?.click()} isDisabled={upload.isPending}>Add photos</Button>
      </div>
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden aria-hidden="true" tabIndex={-1} onChange={(e) => onFiles(e.currentTarget)} />
      <input ref={pick} type="file" accept="image/*,.heic,.heif" multiple hidden aria-label="Choose photos" onChange={(e) => onFiles(e.currentTarget)} />
      <p className="text-sm text-stone-500">Photo locations are removed.</p>
      {progress && <p role="status" className="text-sm text-stone-500">{progress}</p>}
      <ErrorText error={upload.error} />
    </div>
  )
}

/** A checkbox that shows the tick at once; the saved state takes over when it comes back. */
function TickBox({ saved, disabled, onChange, className = '' }: { saved: boolean; disabled: boolean; onChange: (on: boolean) => void; className?: string }) {
  const [on, setOn] = useState(saved)
  return (
    <input type="checkbox" className={`size-5 shrink-0 accent-brand-600 ${className}`} checked={on} disabled={disabled}
      onChange={(e) => { setOn(e.target.checked); onChange(e.target.checked) }} />
  )
}
