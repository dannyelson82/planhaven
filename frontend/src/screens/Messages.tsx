// Messages (ADR 0018): conversations with anyone on this PlanHaven, one-to-one or in a named
// group, with who's online. New messages arrive over the live connection (src/me.ts).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, useEffect, useState } from 'react'
import { api } from '../api.ts'
import { type Conversation, type Message, type Person, seen, useConversations } from '../conversations.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText, Field, Link } from '../ui.tsx'

function Dot({ online }: { online: boolean }) {
  return <span aria-hidden className={`inline-block size-2.5 shrink-0 rounded-full ${online ? 'bg-green-500' : 'bg-stone-300 dark:bg-stone-600'}`} />
}

const when = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  return new Date().toDateString() === d.toDateString()
    ? d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function MessagesScreen({ myId }: { myId: string }) {
  const list = useConversations()
  const [starting, setStarting] = useState<'direct' | 'group' | null>(null)
  const items = list.data ?? []
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Messages</h1>
      <div className="flex flex-wrap gap-2">
        <Button variant={starting === 'direct' ? 'primary' : 'secondary'} onPress={() => setStarting(starting === 'direct' ? null : 'direct')}>New message</Button>
        <Button variant={starting === 'group' ? 'primary' : 'secondary'} onPress={() => setStarting(starting === 'group' ? null : 'group')}>New group</Button>
      </div>
      {starting && <StartConversation group={starting === 'group'} onCancel={() => setStarting(null)} />}
      {list.isSuccess && items.length === 0 && !starting && (
        <p className="text-stone-500">No messages yet. Tap New message to write to someone on this PlanHaven.</p>
      )}
      <ul aria-label="Conversations" className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 empty:hidden dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
        {items.map((c) => <ConversationRow key={c.id} c={c} myId={myId} />)}
      </ul>
      <p className="text-sm text-stone-500">
        Only the people in a conversation can read it; admins can't. Like notes, messages are stored on this server, so whoever runs it could read them in its database.
      </p>
      <ErrorText error={list.error} />
    </div>
  )
}

function ConversationRow({ c, myId }: { c: Conversation; myId: string }) {
  const other = c.is_group ? null : c.members.find((m) => m.id !== myId) ?? null
  return (
    <li>
      <Link to={`/messages/${c.id}`} className="flex min-h-16 items-center gap-3 px-3 py-2.5 hover:bg-stone-50 dark:hover:bg-stone-800">
        {other ? <Dot online={other.online} /> : <span aria-hidden className="w-2.5 text-xs text-stone-400">#</span>}
        <span className="min-w-0 flex-1">
          <span className={`block truncate ${c.unread ? 'font-semibold' : ''}`}>{c.title}</span>
          <span className="block truncate text-sm text-stone-500">{c.last_from_me && c.last_preview ? `You: ${c.last_preview}` : c.last_preview || (c.is_group ? `${c.members.length} people` : 'No messages yet')}</span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-xs text-stone-500">{when(c.last_message_at)}</span>
          {c.unread > 0 && <span className="rounded-full bg-brand-600 px-1.5 text-xs font-semibold leading-5 text-white">{c.unread}<span className="sr-only"> unread</span></span>}
        </span>
      </Link>
    </li>
  )
}

/** Pick people: one opens (or starts) a one-to-one conversation; a group takes a name. */
function StartConversation({ group, onCancel, conversation }: { group: boolean; onCancel: () => void; conversation?: Conversation }) {
  const client = useQueryClient()
  const people = useQuery({ queryKey: ['people-status'], queryFn: () => api<Person[]>('GET', '/api/v1/people/status'), staleTime: 15_000 })
  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const already = new Set(conversation?.members.map((m) => m.id) ?? [])
  const start = useMutation({
    mutationFn: (ids: string[]) => conversation
      ? Promise.all(ids.map((id) => api('POST', `/api/v1/conversations/${conversation.id}/members`, { user_id: id }))).then(() => conversation)
      : api<Conversation>('POST', '/api/v1/conversations', { people: ids, ...(group ? { title: title.trim() } : {}) }),
    onSuccess: async (c) => {
      await client.invalidateQueries({ queryKey: ['conversations'] })
      onCancel()
      if (!conversation) navigate(`/messages/${c.id}`)
    },
  })
  const shown = (people.data ?? []).filter((p) => !already.has(p.id) && p.name.toLowerCase().includes(query.trim().toLowerCase()))
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id])
  return (
    <Card className="space-y-3">
      <h2 className="font-semibold">{conversation ? 'Add people' : group ? 'New group' : 'New message'}</h2>
      {group && !conversation && <Field label="Group name" isRequired maxLength={100} value={title} onChange={setTitle} />}
      <input type="search" aria-label="Search people" placeholder="Search people" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={100}
        className="min-h-11 w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900" />
      <ul aria-label="People" className="max-h-72 space-y-1 overflow-y-auto">
        {shown.map((p) => (
          <li key={p.id}>
            {group || conversation ? (
              <label className="flex min-h-11 items-center gap-3">
                <input type="checkbox" className="size-5 accent-brand-600" checked={picked.includes(p.id)} onChange={() => toggle(p.id)} />
                <Dot online={p.online} />
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="text-xs text-stone-500">{seen(p)}</span>
              </label>
            ) : (
              <button type="button" onClick={() => start.mutate([p.id])} disabled={start.isPending}
                className="flex min-h-11 w-full items-center gap-3 rounded-xl px-2 text-left hover:bg-stone-100 dark:hover:bg-stone-800">
                <Dot online={p.online} />
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="text-xs text-stone-500">{seen(p)}</span>
              </button>
            )}
          </li>
        ))}
      </ul>
      {people.isSuccess && shown.length === 0 && <p className="text-sm text-stone-500">{query.trim() ? 'Nobody by that name.' : 'Nobody else to add yet. An admin can invite people.'}</p>}
      <ErrorText error={start.error ?? people.error} />
      <div className="flex gap-2">
        {(group || conversation) && (
          <Button onPress={() => start.mutate(picked)} isDisabled={!picked.length || (group && !conversation && !title.trim()) || start.isPending}>
            {conversation ? 'Add' : 'Start group'}
          </Button>
        )}
        <Button variant="ghost" onPress={onCancel}>Cancel</Button>
      </div>
    </Card>
  )
}

export function ConversationScreen({ id, myId }: { id: string; myId: string }) {
  const client = useQueryClient()
  const conversation = useQuery({ queryKey: ['conversations', id], queryFn: () => api<Conversation>('GET', `/api/v1/conversations/${id}`) })
  const messages = useQuery({ queryKey: ['messages', id], queryFn: () => api<Message[]>('GET', `/api/v1/conversations/${id}/messages`), staleTime: 0 })
  const [older, setOlder] = useState<Message[]>([])
  const [noMore, setNoMore] = useState(false)
  const loadOlder = useMutation({
    mutationFn: () => {
      const all = [...(messages.data ?? []), ...older]
      const oldest = all[all.length - 1]
      return api<Message[]>('GET', `/api/v1/conversations/${id}/messages?${new URLSearchParams({ before: oldest.created_at })}`)
    },
    onSuccess: (more) => { setOlder([...older, ...more]); if (more.length < 50) setNoMore(true) },
  })
  // Reading the conversation marks it read (and its notifications), also as messages arrive.
  const newest = messages.data?.[0]?.id
  useEffect(() => {
    if (!newest && !messages.isSuccess) return
    void api('POST', `/api/v1/conversations/${id}/read`).then(() => Promise.all([
      client.invalidateQueries({ queryKey: ['conversations'], exact: true }),
      client.invalidateQueries({ queryKey: ['notifications'] }),
    ])).catch(() => undefined)
  }, [id, newest, messages.isSuccess, client])
  const [showDetails, setShowDetails] = useState(false)
  if (conversation.error) return <ErrorText error={conversation.error} />
  if (!conversation.data) return <p className="text-stone-500">Loading…</p>
  const c = conversation.data
  const others = c.is_group ? [] : c.members.filter((m) => m.id !== myId)
  const all = [...(messages.data ?? []), ...older]
  return (
    <div className="flex min-h-[calc(100dvh-10rem)] flex-col gap-3">
      <Link to="/messages" className="text-sm text-brand-700 dark:text-brand-100">← All messages</Link>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold">{c.title}</h1>
          <p className="flex items-center gap-2 text-sm text-stone-500">
            {c.is_group ? c.members.map((m) => m.name).join(', ') : others[0] && <><Dot online={others[0].online} /> {seen(others[0]) || 'Online status hidden'}</>}
          </p>
        </div>
        {c.is_group && <Button variant="ghost" onPress={() => setShowDetails(!showDetails)} aria-expanded={showDetails}>Group</Button>}
      </div>
      {showDetails && <GroupDetails c={c} />}
      <section aria-label="Messages" className="flex flex-1 flex-col-reverse gap-2">
        {all.map((m, i) => <Bubble key={m.id} m={m} showName={c.is_group && !m.mine && all[i + 1]?.sender_id !== m.sender_id} conversationId={id} />)}
        {all.length >= 50 && !noMore && (
          <Button variant="ghost" onPress={() => loadOlder.mutate()} isDisabled={loadOlder.isPending} className="self-center">Earlier messages</Button>
        )}
        {messages.isSuccess && all.length === 0 && <p className="text-center text-stone-500">Say hello.</p>}
      </section>
      <Composer conversationId={id} />
      <ErrorText error={messages.error ?? loadOlder.error} />
    </div>
  )
}

function Bubble({ m, showName, conversationId }: { m: Message; showName: boolean; conversationId: string }) {
  const client = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const remove = useMutation({
    mutationFn: () => api('DELETE', `/api/v1/messages/${m.id}`),
    onSettled: () => client.invalidateQueries({ queryKey: ['messages', conversationId] }),
  })
  return (
    <div className={`flex max-w-[85%] flex-col ${m.mine ? 'self-end items-end' : 'self-start items-start'}`}>
      {showName && <span className="px-2 text-xs text-stone-500">{m.sender_name}</span>}
      <div className={`rounded-2xl px-3 py-2 ${m.deleted ? 'italic text-stone-500 ring-1 ring-stone-200 dark:ring-stone-700'
        : m.mine ? 'bg-brand-600 text-white' : 'bg-white ring-1 ring-stone-200 dark:bg-stone-900 dark:ring-stone-800'}`}>
        <p className="whitespace-pre-wrap break-words">{m.deleted ? 'Message deleted' : m.body}</p>
      </div>
      <span className="flex items-center gap-2 px-2 text-xs text-stone-500">
        {when(m.created_at)}
        {m.mine && !m.deleted && (
          <button type="button" className="min-h-8 underline-offset-2 hover:underline" onClick={() => (confirm ? remove.mutate() : setConfirm(true))}
            aria-label={confirm ? 'Tap again to delete this message' : `Delete message: ${m.body.slice(0, 40)}`}>
            {confirm ? 'Tap again to delete' : 'Delete'}
          </button>
        )}
      </span>
    </div>
  )
}

function Composer({ conversationId }: { conversationId: string }) {
  const client = useQueryClient()
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: (body: string) => api<Message>('POST', `/api/v1/conversations/${conversationId}/messages`, { body }),
    onMutate: () => setText(''),
    onError: (_e, body) => setText(body),
    onSettled: () => Promise.all([
      client.invalidateQueries({ queryKey: ['messages', conversationId] }),
      client.invalidateQueries({ queryKey: ['conversations'], exact: true }),
    ]),
  })
  const submit = () => { const body = text.trim(); if (body && !send.isPending) send.mutate(body) }
  // On a computer, Enter sends and Shift+Enter starts a new line; on a phone, the Send button.
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer: fine)').matches) { e.preventDefault(); submit() }
  }
  return (
    <form className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] flex items-end gap-2 rounded-2xl bg-white/95 p-2 ring-1 ring-stone-200 backdrop-blur md:bottom-4 dark:bg-stone-900/95 dark:ring-stone-800"
      onSubmit={(e) => { e.preventDefault(); submit() }}>
      <textarea aria-label="Message" rows={1} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
        placeholder="Message" className="max-h-40 min-h-11 min-w-0 flex-1 resize-none rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900" />
      <Button type="submit" isDisabled={!text.trim() || send.isPending}>Send</Button>
      <ErrorText error={send.error} />
    </form>
  )
}

function GroupDetails({ c }: { c: Conversation }) {
  const client = useQueryClient()
  const [name, setName] = useState(c.title)
  const [adding, setAdding] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const refresh = () => client.invalidateQueries({ queryKey: ['conversations'] })
  const rename = useMutation({ mutationFn: () => api('PATCH', `/api/v1/conversations/${c.id}`, { title: name.trim() }), onSettled: refresh })
  const leave = useMutation({
    mutationFn: () => api('POST', `/api/v1/conversations/${c.id}/leave`),
    onSuccess: async () => { await refresh(); navigate('/messages') },
  })
  return (
    <Card className="space-y-3">
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim() && name.trim() !== c.title) rename.mutate() }}>
        <div className="min-w-0 flex-1"><Field label="Group name" maxLength={100} value={name} onChange={setName} /></div>
        <Button type="submit" variant="secondary" isDisabled={!name.trim() || name.trim() === c.title || rename.isPending}>Rename</Button>
      </form>
      <ul aria-label="Members" className="space-y-1 text-sm">
        {c.members.map((m) => <li key={m.id} className="flex items-center gap-2"><Dot online={m.online} /> {m.name} <span className="text-stone-500">{seen(m)}</span></li>)}
      </ul>
      {adding ? <StartConversation group onCancel={() => setAdding(false)} conversation={c} /> : <Button variant="secondary" onPress={() => setAdding(true)}>Add people</Button>}
      <Button variant="danger-ghost" onPress={() => (confirm ? leave.mutate() : setConfirm(true))} isDisabled={leave.isPending}>
        {confirm ? 'Tap again to leave this group' : 'Leave group'}
      </Button>
      <ErrorText error={rename.error ?? leave.error} />
    </Card>
  )
}

/** Account: whether others see when you're online. */
export function PresenceCard() {
  const client = useQueryClient()
  const presence = useQuery({ queryKey: ['presence'], queryFn: () => api<{ hidden: boolean }>('GET', '/api/v1/presence') })
  const [box, setBox] = useState<{ saved: boolean; on: boolean } | null>(null)
  const saved = presence.data?.hidden ?? false
  const hidden = box && box.saved === saved ? box.on : saved
  const save = useMutation({
    mutationFn: (h: boolean) => api<{ hidden: boolean }>('PUT', '/api/v1/presence', { hidden: h }),
    onSuccess: (r) => client.setQueryData(['presence'], r),
  })
  return (
    <Card className="space-y-1">
      <label className="flex min-h-11 items-center gap-3">
        <input type="checkbox" className="size-5 accent-brand-600" checked={hidden} disabled={!presence.isSuccess}
          onChange={(e) => { setBox({ saved, on: e.target.checked }); save.mutate(e.target.checked) }} />
        <span className="font-medium">Hide my online status</span>
      </label>
      <p className="text-sm text-stone-500">Others won't see when you're online or when you were last here.</p>
      <ErrorText error={save.error ?? presence.error} />
    </Card>
  )
}
