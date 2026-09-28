import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { Button, Card, ErrorText, Link } from '../ui.tsx'

type Kind = 'project' | 'task' | 'list' | 'note' | 'attachment' | 'quote' | 'cost' | 'asset' | 'contact'
type Item = { kind: Kind; id: string; title: string; project_id: string | null; project_title: string | null; deleted_at: string }

const KIND_LABEL: Record<Kind, string> = {
  project: 'Project', task: 'Task', list: 'List', note: 'Note', attachment: 'File',
  quote: 'Quote', cost: 'Cost', asset: 'Asset', contact: 'Contact',
}

function restoredPath(i: Item): string {
  if (i.kind === 'project') return `/projects/${i.id}`
  if (i.kind === 'asset') return `/assets/${i.id}`
  if (i.kind === 'contact') return `/contacts/${i.id}`
  if (i.kind === 'list') return `/lists/${i.id}`
  if (i.kind === 'note') return `/notes/${i.id}`
  return `/projects/${i.project_id}`
}

/** Deleted things you can bring back, for 30 days. */
export function TrashScreen() {
  const client = useQueryClient()
  const items = useQuery({ queryKey: ['trash'], queryFn: () => api<Item[]>('GET', '/api/v1/trash') })
  const [restored, setRestored] = useState<Item | null>(null)
  const restore = useMutation({
    mutationFn: (i: Item) => api('POST', `/api/v1/trash/${i.kind}/${i.id}/restore`),
    onSuccess: (_d, i) => setRestored(i),
    // Everything could show the restored item again.
    onSettled: () => client.invalidateQueries(),
  })
  // Counted from when the list was fetched (render stays pure).
  const daysLeft = (i: Item) => Math.max(0, 30 - Math.floor((items.dataUpdatedAt - new Date(i.deleted_at).getTime()) / 86_400_000))
  return (
    <div className="space-y-4">
      <Link to="/account" className="text-sm text-brand-700 dark:text-brand-100">← Account</Link>
      <h1 className="text-2xl font-bold">Trash</h1>
      <p className="text-stone-600 dark:text-stone-400">Deleted things stay here for 30 days, then they're gone for good.</p>
      {restored && (
        <p role="status" className="rounded-xl bg-brand-50 p-3 dark:bg-stone-800">
          Restored “{restored.title}”. <Link to={restoredPath(restored)} className="font-medium text-brand-700 dark:text-brand-100">Open</Link>
        </p>
      )}
      {items.data?.length === 0 && <p className="text-sm text-stone-500">The trash is empty.</p>}
      <ul className="space-y-2">
        {(items.data ?? []).map((i) => (
          <li key={`${i.kind}-${i.id}`}>
            <Card className="flex flex-wrap items-center gap-2 py-3">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{i.title}</span>
                <span className="block text-sm text-stone-500">
                  {KIND_LABEL[i.kind]}{i.project_title && ` in ${i.project_title}`} · {daysLeft(i)} days left
                </span>
              </span>
              <Button variant="secondary" onPress={() => restore.mutate(i)} isDisabled={restore.isPending}>Restore</Button>
            </Card>
          </li>
        ))}
      </ul>
      <ErrorText error={restore.error ?? items.error} />
    </div>
  )
}
