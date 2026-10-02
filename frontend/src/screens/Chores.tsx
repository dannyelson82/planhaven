// Chores (ADR 0013): tasks assigned to someone, once or repeating, with proof (a photo or a
// note) that the person who assigned it approves or sends back. The assignee sees only their
// chores, not the rest of the project.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, dueLabel, type Task, uploadFile } from '../api.ts'
import type { Person } from '../conversations.ts'
import { Button, Card, ErrorText, Field, Form, Link } from '../ui.tsx'
import { type Chore, DAYS, type Freq, type Proof, repeatText, useMyChores } from '../chores.ts'

type Submission = {
  id: string; task_id: string; submitted_by: string; submitted_at: string; note: string; has_photo: boolean
  status: string; comment: string
}

const PROOF_LABEL: Record<Proof, string> = { none: 'No proof needed', photo: 'A photo', note: 'A short note' }

function usePeople() {
  return useQuery({ queryKey: ['people-status'], queryFn: () => api<Person[]>('GET', '/api/v1/people/status'), staleTime: 30_000 })
}

/** The task row's chore line: who, how often, and whether it's waiting for approval. */
export function ChoreLine({ task, myId }: { task: Task; myId: string }) {
  const people = usePeople()
  if (!task.assignee_id) return null
  const name = task.assignee_id === myId ? 'you' : people.data?.find((p) => p.id === task.assignee_id)?.name ?? 'someone'
  const repeat = repeatText({ repeat_freq: task.repeat_freq ?? null, repeat_interval: task.repeat_interval ?? 1, repeat_days: task.repeat_days ?? null })
  return (
    <span className="block text-xs text-brand-700 dark:text-brand-100">
      Chore for {name}{repeat ? ` · ${repeat.toLowerCase()}` : ''}{task.waiting ? ' · waiting for approval' : ''}
    </span>
  )
}

// ---------------------------------------------------------------- assigning (in a task's details)

const localInput = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function ChoreForm({ task, myId, done }: { task: Task; myId: string; done: () => void }) {
  const client = useQueryClient()
  const people = usePeople()
  const [assignee, setAssignee] = useState(task.assignee_id ?? '')
  const [proof, setProof] = useState<Proof>(task.proof ?? 'none')
  const [freq, setFreq] = useState<Freq | ''>(task.repeat_freq ?? '')
  const [every, setEvery] = useState(String(task.repeat_interval ?? 1))
  const [days, setDays] = useState<number[]>(task.repeat_days ?? [])
  const [due, setDue] = useState(task.due_all_day ? '' : localInput(task.due_at))
  const n = Number(every)
  const ok = Number.isInteger(n) && n >= 1 && n <= 52 && (!freq || due) && (freq !== 'weekly' || days.length > 0)
  const save = useMutation({
    mutationFn: () => api('PUT', `/api/v1/tasks/${task.id}/chore`, {
      assignee_id: assignee || null,
      proof,
      repeat_freq: freq || null,
      repeat_interval: n,
      repeat_days: freq === 'weekly' ? days : null,
      due_at: due ? new Date(due).toISOString() : task.due_at,
      due_all_day: due ? false : task.due_all_day,
    }, { 'If-Match': `"${task.version}"` }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['tasks', task.project_id] }); done() },
  })
  const select = 'mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900'
  return (
    <Form onSubmit={(e) => { e.preventDefault(); if (ok) save.mutate() }}>
      <h2 className="text-lg font-semibold">Chore</h2>
      <label className="block text-sm font-medium">
        Assign to
        <select value={assignee} onChange={(e) => setAssignee(e.target.value)} className={select}>
          <option value="">Nobody (not a chore)</option>
          <option value={myId}>Me</option>
          {(people.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      {assignee && (
        <>
          <label className="block text-sm font-medium">
            Due
            <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} className={select} />
          </label>
          <label className="block text-sm font-medium">
            Repeats
            <select value={freq} onChange={(e) => setFreq(e.target.value as Freq | '')} className={select}>
              <option value="">Never (once)</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </label>
          {freq && (
            <div className="flex items-end gap-2 text-sm">
              <div className="w-44"><Field label={freq === 'daily' ? 'Every … days' : freq === 'weekly' ? 'Every … weeks' : 'Every … months'} inputMode="numeric" maxLength={2} value={every} onChange={setEvery} /></div>
            </div>
          )}
          {freq === 'weekly' && (
            <fieldset className="flex flex-wrap gap-2">
              <legend className="mb-1 text-sm font-medium">On</legend>
              {DAYS.map((d, i) => (
                <label key={d} className="flex min-h-11 items-center gap-1 rounded-xl px-2 ring-1 ring-stone-300 dark:ring-stone-700">
                  <input type="checkbox" className="size-4 accent-brand-600" checked={days.includes(i)}
                    onChange={() => setDays(days.includes(i) ? days.filter((x) => x !== i) : [...days, i])} />
                  {d}
                </label>
              ))}
            </fieldset>
          )}
          {freq && !due && <p className="text-sm text-amber-700 dark:text-amber-400">A repeating chore needs its first due date and time.</p>}
          <label className="block text-sm font-medium">
            Proof when done
            <select value={proof} onChange={(e) => setProof(e.target.value as Proof)} className={select}>
              {(Object.keys(PROOF_LABEL) as Proof[]).map((p) => <option key={p} value={p}>{PROOF_LABEL[p]}</option>)}
            </select>
          </label>
          {proof !== 'none' && assignee !== myId && <p className="text-sm text-stone-500">You'll be asked to approve it (or send it back) when it's done.</p>}
        </>
      )}
      <ErrorText error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" className="flex-1" isDisabled={!ok || save.isPending}>Save</Button>
        <Button variant="ghost" onPress={done}>Cancel</Button>
      </div>
    </Form>
  )
}

// ---------------------------------------------------------------- the Chores page

export function ChoresScreen() {
  const mine = useMyChores()
  const toReview = useQuery({ queryKey: ['chores', 'to-review'], queryFn: () => api<{ submission: Submission; chore: Chore }[]>('GET', '/api/v1/chores/to-review') })
  const people = usePeople()
  const name = (id: string) => people.data?.find((p) => p.id === id)?.name ?? 'Someone'
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Chores</h1>
      <section aria-label="My chores" className="space-y-2">
        <h2 className="text-lg font-semibold">My chores</h2>
        {mine.isSuccess && mine.data.length === 0 && <p className="text-stone-500">Nothing to do right now.</p>}
        <ul className="space-y-2">
          {(mine.data ?? []).map((c) => <li key={c.id}><MyChore c={c} /></li>)}
        </ul>
        <ErrorText error={mine.error} />
      </section>
      {(toReview.data ?? []).length > 0 && (
        <section aria-label="To approve" className="space-y-2">
          <h2 className="text-lg font-semibold">To approve</h2>
          <ul className="space-y-2">
            {(toReview.data ?? []).map((r) => <li key={r.submission.id}><ToApprove s={r.submission} c={r.chore} who={name(r.submission.submitted_by)} /></li>)}
          </ul>
        </section>
      )}
      <p className="text-sm text-stone-500">Chores are tasks someone assigned to you. To give someone a chore, open a task on a project and tap Chore.</p>
    </div>
  )
}

function MyChore({ c }: { c: Chore }) {
  const client = useQueryClient()
  const [note, setNote] = useState('')
  const [open, setOpen] = useState(false)
  const camera = useRef<HTMLInputElement>(null)
  const pick = useRef<HTMLInputElement>(null)
  const refresh = () => client.invalidateQueries({ queryKey: ['chores'] })
  const done = useMutation({
    mutationFn: async (photo: File | null) => {
      const s = await api<{ id: string; status: string }>('POST', `/api/v1/tasks/${c.id}/submissions`, { note })
      if (photo) await uploadFile(`/api/v1/submissions/${s.id}/photo`, photo, 'PUT')
    },
    onSuccess: async () => { setOpen(false); setNote(''); await refresh() },
  })
  const onPhoto = (input: HTMLInputElement) => {
    const file = input.files?.[0]
    input.value = ''
    if (file) done.mutate(file)
  }
  const due = dueLabel(c, true)
  const repeat = repeatText(c)
  const waiting = c.status === 'pending'
  return (
    <Card className="space-y-2">
      <div>
        <p className="font-semibold">{c.title}</p>
        <p className="text-sm text-stone-500">{[due && `Due ${due}`, repeat, c.project_title].filter(Boolean).join(' · ')}</p>
        {c.notes && <p className="whitespace-pre-wrap text-sm">{c.notes}</p>}
      </div>
      {c.status === 'sent_back' && (
        <p role="status" className="rounded-xl bg-amber-50 p-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Sent back: {c.comment}
        </p>
      )}
      {waiting ? (
        <p className="text-sm text-brand-700 dark:text-brand-100">Done, waiting for approval.</p>
      ) : !open ? (
        <Button onPress={() => (c.proof === 'none' ? done.mutate(null) : setOpen(true))} isDisabled={done.isPending}>Done</Button>
      ) : (
        <div className="space-y-2">
          {c.proof === 'note' && (
            <Form onSubmit={(e) => { e.preventDefault(); if (note.trim()) done.mutate(null) }}>
              <Field label="What did you do?" multiline isRequired maxLength={2000} value={note} onChange={setNote} />
              <Button type="submit" isDisabled={!note.trim() || done.isPending}>Send</Button>
            </Form>
          )}
          {c.proof === 'photo' && (
            <>
              <p className="text-sm">Add a photo to show it's done.</p>
              <div className="flex flex-wrap gap-2">
                <Button onPress={() => camera.current?.click()} isDisabled={done.isPending} className="md:hidden">Take photo</Button>
                <Button variant="secondary" onPress={() => pick.current?.click()} isDisabled={done.isPending}>Choose a photo</Button>
              </div>
              <input ref={camera} type="file" accept="image/*" capture="environment" hidden aria-hidden="true" tabIndex={-1} onChange={(e) => onPhoto(e.currentTarget)} />
              <input ref={pick} type="file" accept="image/*,.heic,.heif" hidden aria-label="Choose a photo" onChange={(e) => onPhoto(e.currentTarget)} />
              {done.isPending && <p role="status" className="text-sm text-stone-500">Sending…</p>}
            </>
          )}
          <Button variant="ghost" onPress={() => setOpen(false)}>Cancel</Button>
        </div>
      )}
      <ErrorText error={done.error} />
    </Card>
  )
}

function ToApprove({ s, c, who }: { s: Submission; c: Chore; who: string }) {
  const client = useQueryClient()
  const [comment, setComment] = useState('')
  const [sendingBack, setSendingBack] = useState(false)
  const review = useMutation({
    mutationFn: (approve: boolean) => api('POST', `/api/v1/submissions/${s.id}/review`, { approve, comment }),
    onSuccess: () => Promise.all([client.invalidateQueries({ queryKey: ['chores'] }), client.invalidateQueries({ queryKey: ['tasks', c.project_id] })]),
  })
  return (
    <Card className="space-y-2">
      <div>
        <p className="font-semibold">{c.title}</p>
        <p className="text-sm text-stone-500">{who} · {new Date(s.submitted_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}{c.project_title && <> · <Link to={`/projects/${c.project_id}`} className="underline">{c.project_title}</Link></>}</p>
      </div>
      {s.has_photo && (
        <a href={`/api/v1/submissions/${s.id}/photo`} target="_blank" rel="noopener noreferrer">
          <img src={`/api/v1/submissions/${s.id}/photo/thumbnail`} alt={`Photo for ${c.title}`} className="max-h-48 rounded-xl" />
        </a>
      )}
      {s.note && <p className="whitespace-pre-wrap rounded-xl bg-stone-100 p-2 text-sm dark:bg-stone-800">{s.note}</p>}
      {sendingBack ? (
        <Form onSubmit={(e) => { e.preventDefault(); if (comment.trim()) review.mutate(false) }}>
          <Field label="What still needs doing?" isRequired maxLength={1000} value={comment} onChange={setComment} />
          <div className="flex gap-2">
            <Button type="submit" isDisabled={!comment.trim() || review.isPending}>Send back</Button>
            <Button variant="ghost" onPress={() => setSendingBack(false)}>Cancel</Button>
          </div>
        </Form>
      ) : (
        <div className="flex gap-2">
          <Button onPress={() => review.mutate(true)} isDisabled={review.isPending}>Approve</Button>
          <Button variant="secondary" onPress={() => setSendingBack(true)}>Send back</Button>
        </div>
      )}
      <ErrorText error={review.error} />
    </Card>
  )
}

/** On Projects: your chores, one tap away (a household member may have only these). */
export function MyChoresLink() {
  const mine = useMyChores()
  const toReview = useQuery({ queryKey: ['chores', 'to-review'], queryFn: () => api<unknown[]>('GET', '/api/v1/chores/to-review') })
  const todo = mine.data?.filter((c) => c.status !== 'pending').length ?? 0
  const approve = toReview.data?.length ?? 0
  if (!mine.data?.length && !approve) return null
  return (
    <Card className="py-3">
      <Link to="/chores" className="font-medium text-brand-700 dark:text-brand-100">Chores</Link>
      <p className="text-sm text-stone-500">
        {[todo && `${todo} for you to do`, approve && `${approve} to approve`].filter(Boolean).join(' · ') || 'Waiting for approval'}
      </p>
    </Card>
  )
}
