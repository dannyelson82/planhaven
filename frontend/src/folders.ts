// Each person's project folders (ADR 0022): paths and pickers.

export type Folder = { id: string; parent_id: string | null; name: string; position: number; projects: number; version: number }

export const folderUrl = (id: string | null) => (id ? `/projects/folders/${id}` : '/projects')
export const byOrder = (a: Folder, b: Folder) => a.position - b.position || a.name.localeCompare(b.name)

/** The folders from the top down to `id` (empty at the top level). */
export function trail(folders: Map<string, Folder>, id: string | null): Folder[] {
  const out: Folder[] = []
  let at = id ? folders.get(id) : undefined
  while (at && out.length < 10) {
    out.unshift(at)
    at = at.parent_id ? folders.get(at.parent_id) : undefined
  }
  return out
}

/** Every folder as "Cars › Corolla", in tree order, for a picker. Leaves out `skip` and the
 * folders inside it (a folder can't move into itself). */
export function folderChoices(all: Folder[], skip: string | null = null): { id: string; label: string }[] {
  const out: { id: string; label: string }[] = []
  const walk = (parent: string | null, path: string) => {
    for (const f of all.filter((x) => x.parent_id === parent).sort(byOrder)) {
      if (f.id === skip) continue
      const label = path ? `${path} › ${f.name}` : f.name
      out.push({ id: f.id, label })
      walk(f.id, label)
    }
  }
  walk(null, '')
  return out
}
