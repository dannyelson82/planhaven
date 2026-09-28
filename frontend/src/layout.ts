// A project page's arrangement as tiles, per person (see screens/Arrange.tsx).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api.ts'
import { cachedGet } from './offline.ts'

export type Width = 'narrow' | 'wide' | 'full'
export type Group = 'tasks' | 'lists' | 'notes' | 'files' | 'money'
export type Single = 'note' | 'list' | 'file'
export type Tile = { kind: Group | Single; id?: string | null; width: Width }
type Layout = { tiles: Tile[]; source: 'mine' | 'owner' | 'default' }

export const GROUP_LABEL: Record<Group, string> = {
  tasks: 'Tasks', lists: 'Lists', notes: 'Notes', files: 'Photos and files', money: 'Quotes and costs',
}
export const SINGLE_LABEL: Record<Single, string> = { note: 'Note', list: 'List', file: 'File' }
export const WIDTH_LABEL: Record<Width, string> = { narrow: 'Narrow', wide: 'Wide', full: 'Full' }

/** Grid column span of a tile on a computer (six columns); on a phone tiles stack. */
export const SPAN: Record<Width, string> = { narrow: 'md:col-span-2', wide: 'md:col-span-4', full: 'md:col-span-6' }

const DEFAULT: Layout = { tiles: (['tasks', 'lists', 'notes', 'files', 'money'] as const).map((kind) => ({ kind, width: 'full' })), source: 'default' }

export const tileKey = (t: Tile) => (t.id ? `${t.kind}:${t.id}` : t.kind)

export function useLayout(projectId: string) {
  const client = useQueryClient()
  const key = ['layout', projectId]
  const layout = useQuery({ queryKey: key, queryFn: () => cachedGet<Layout>(`/api/v1/projects/${projectId}/layout`) })
  const save = useMutation({
    mutationFn: (tiles: Tile[]) => api<Layout>('PUT', `/api/v1/projects/${projectId}/layout`,
      { tiles: tiles.map((t) => (t.id ? { kind: t.kind, id: t.id, width: t.width } : { kind: t.kind, width: t.width })) }),
    // Shown at once; the server's answer (cleaned) replaces it.
    onMutate: (tiles) => client.setQueryData<Layout>(key, { tiles, source: 'mine' }),
    onSuccess: (saved) => client.setQueryData(key, saved),
    onError: () => client.invalidateQueries({ queryKey: key }),
  })
  const reset = useMutation({
    mutationFn: () => api<Layout>('DELETE', `/api/v1/projects/${projectId}/layout`),
    onSuccess: (saved) => client.setQueryData(key, saved),
  })
  return { layout: layout.data ?? DEFAULT, save, reset }
}
