import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Dialog, DialogTrigger, Heading, Modal } from 'react-aria-components'
import { api } from '../api.ts'
import { navigate } from '../router.ts'
import { useStepUp } from '../stepupContext.ts'
import { Button, ErrorText } from '../ui.tsx'

type Member = { user_id: string; display_name: string; email: string; role: Role }
type Person = { id: string; display_name: string; email: string }
type Role = 'owner' | 'editor' | 'viewer'

const ROLE_LABEL: Record<Role, string> = { owner: 'Owner', editor: 'Can edit', viewer: 'Can view' }
const select =
  'min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900'

type Kind = 'project' | 'asset' | 'contact' | 'template'

/** Members of a project or asset; owners can add people, change roles and remove them. */
export function ShareButton({ kind, id, isOwner, myId }: { kind: Kind; id: string; isOwner: boolean; myId: string }) {
  return (
    <DialogTrigger>
      <Button variant="secondary">{isOwner ? 'Share' : 'Members'}</Button>
      <Modal isDismissable className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 sm:items-center">
        <Dialog className="max-h-[85dvh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
          {({ close }) => <SharePanel kind={kind} id={id} isOwner={isOwner} myId={myId} close={close} />}
        </Dialog>
      </Modal>
    </DialogTrigger>
  )
}

function SharePanel({ kind, id, isOwner, myId, close }: { kind: Kind; id: string; isOwner: boolean; myId: string; close: () => void }) {
  const client = useQueryClient()
  const stepUp = useStepUp()
  const base = `/api/v1/${kind}s/${id}/members`
  const members = useQuery({ queryKey: ['members', kind, id], queryFn: () => api<Member[]>('GET', base) })
  const people = useQuery({ queryKey: ['people'], queryFn: () => api<Person[]>('GET', '/api/v1/people'), enabled: isOwner })
  const [personId, setPersonId] = useState('')
  const [role, setRole] = useState<Role>('editor')
  const refresh = () => client.invalidateQueries({ queryKey: ['members', kind, id] })
  const add = useMutation({
    mutationFn: () => stepUp(() => api('POST', base, { user_id: personId, role })),
    onSuccess: async () => { setPersonId(''); await refresh() },
  })
  const change = useMutation({
    mutationFn: (m: { id: string; role: Role }) => stepUp(() => api('PATCH', `${base}/${m.id}`, { role: m.role })),
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: string) => stepUp(() => api('DELETE', `${base}/${id}`)),
    onSuccess: async (_d, id) => {
      if (id === myId) { close(); navigate(`/${kind}s`); await client.invalidateQueries() } else await refresh()
    },
  })
  const memberIds = new Set((members.data ?? []).map((m) => m.user_id))
  const candidates = (people.data ?? []).filter((p) => !memberIds.has(p.id))

  return (
    <div className="space-y-4">
      <Heading slot="title" className="text-lg font-semibold">{isOwner ? `Share this ${kind}` : 'Members'}</Heading>
      <ul className="space-y-2">
        {(members.data ?? []).map((m) => (
          <li key={m.user_id} className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{m.display_name}{m.user_id === myId && ' (you)'}</span>
              <span className="block truncate text-xs text-stone-500">{m.email}</span>
            </span>
            {isOwner ? (
              <select aria-label={`Role for ${m.display_name}`} className={select} value={m.role}
                onChange={(e) => change.mutate({ id: m.user_id, role: e.target.value as Role })}>
                {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            ) : (
              <span className="text-sm text-stone-500">{ROLE_LABEL[m.role]}</span>
            )}
            {(isOwner || m.user_id === myId) && (
              <Button variant="danger-ghost" aria-label={m.user_id === myId ? `Leave ${kind}` : `Remove ${m.display_name}`}
                onPress={() => remove.mutate(m.user_id)}>
                {m.user_id === myId ? 'Leave' : 'Remove'}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {isOwner && (
        <form className="space-y-2 border-t border-stone-200 pt-4 dark:border-stone-800"
          onSubmit={(e) => { e.preventDefault(); if (personId) add.mutate() }}>
          <p className="text-sm font-medium">Add someone from your household</p>
          {candidates.length === 0 ? (
            <p className="text-sm text-stone-500">Everyone is already a member. Invite new people from the admin area.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              <select aria-label="Person" className={`${select} min-w-0 flex-1`} value={personId} onChange={(e) => setPersonId(e.target.value)}>
                <option value="">Choose a person…</option>
                {candidates.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
              </select>
              <select aria-label="Their role" className={select} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                <option value="editor">Can edit</option>
                <option value="viewer">Can view</option>
                <option value="owner">Owner</option>
              </select>
              <Button type="submit" isDisabled={!personId || add.isPending}>Add</Button>
            </div>
          )}
        </form>
      )}
      <ErrorText error={add.error ?? change.error ?? remove.error ?? members.error} />
      <Button variant="ghost" className="w-full" onPress={close}>Done</Button>
    </div>
  )
}
