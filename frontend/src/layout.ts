// A project page's arrangement as tiles, per person (see screens/Arrange.tsx).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext } from 'react'
import { api } from './api.ts'
import { cachedGet } from './offline.ts'

export type Width = 'narrow' | 'wide' | 'full'
export type Group = 'tasks' | 'lists' | 'notes' | 'files' | 'quotes' | 'costs'
export type Single = 'note' | 'list' | 'file'
export type Tile = { kind: Group | Single; id?: string | null; width: Width }
type Layout = { tiles: Tile[]; source: 'mine' | 'owner' | 'default' }

export const GROUP_LABEL: Record<Group, string> = {
  tasks: 'Tasks', lists: 'Lists', notes: 'Notes', files: 'Photos and files', quotes: 'Quotes', costs: 'Costs',
}
export const SINGLE_LABEL: Record<Single, string> = { note: 'Note', list: 'List', file: 'File' }
export const WIDTH_LABEL: Record<Width, string> = { narrow: 'Narrow', wide: 'Wide', full: 'Full' }

/** Grid column span of a tile on a computer (six columns); on a phone tiles stack. */
export const SPAN: Record<Width, string> = { narrow: 'md:col-span-2', wide: 'md:col-span-4', full: 'md:col-span-6' }

const DEFAULT: Layout = { tiles: (['tasks', 'lists', 'notes', 'files', 'quotes', 'costs'] as const).map((kind) => ({ kind, width: 'full' })), source: 'default' }

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

/** Moves a tile (or a card from a group, which then gets its own tile) before or after another
 * tile. A card dropped on its own group goes back into it. */
export function moveTile(tiles: Tile[], key: string, target: string, position: 'before' | 'after'): Tile[] {
  const [kind, id] = key.split(':') as [Tile['kind'], string | undefined]
  if (id && GROUP_OF[kind as Single] === target) return tiles.filter((t) => tileKey(t) !== key)
  if (key === target) return tiles
  const moving: Tile = tiles.find((t) => tileKey(t) === key) ?? { kind, id, width: kind === 'note' ? 'wide' : 'narrow' }
  const rest = tiles.filter((t) => tileKey(t) !== key)
  const found = rest.findIndex((t) => tileKey(t) === target)
  if (found < 0) return tiles
  const at = found + (position === 'after' ? 1 : 0)
  return [...rest.slice(0, at), moving, ...rest.slice(at)]
}

const GROUP_OF: Record<Single, Group> = { note: 'notes', list: 'lists', file: 'files' }

/** Set while the page is being arranged: tiles and cards can then be dragged around it. */
export const ArrangeContext = createContext<{ move: (key: string, target: string, position: 'before' | 'after') => void } | null>(null)

type Named = { id: string; title?: string; filename?: string }

/** Names of tiles ("Notes", "Note: Engine notes"), from the same lists the page shows. Null for
 * a single note, list or file that's gone (or not visible to this person). */
export function useTileNames(projectId: string) {
  const notes = useQuery({ queryKey: ['notes', projectId], queryFn: () => api<Named[]>('GET', `/api/v1/projects/${projectId}/notes`) })
  const lists = useQuery({ queryKey: ['lists', projectId], queryFn: () => cachedGet<Named[]>(`/api/v1/projects/${projectId}/lists`) })
  const files = useQuery({ queryKey: ['attachments', projectId], queryFn: () => api<Named[]>('GET', `/api/v1/projects/${projectId}/attachments`) })
  const sources: Record<Single, Named[]> = { note: notes.data ?? [], list: lists.data ?? [], file: files.data ?? [] }
  const nameOf = (t: Tile): string | null => {
    if (!t.id) return GROUP_LABEL[t.kind as Group]
    const found = sources[t.kind as Single].find((x) => x.id === t.id)
    return found ? `${SINGLE_LABEL[t.kind as Single]}: ${found.title ?? found.filename}` : null
  }
  return { sources, nameOf }
}
