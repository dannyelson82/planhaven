// List items: their shape and saving only what changed ("merge when safe").
import { api, ApiError } from './api.ts'

export type Item = {
  id: string; text: string; quantity: string | null; unit: string | null; price_cents: number | null
  notes: string; website: string; checked: boolean; version: number
}

type Fields = Partial<Pick<Item, 'text' | 'quantity' | 'price_cents' | 'website' | 'notes'>>

/** Only what changed, compared with what the item held when editing started. */
export function changes(i: Item, next: Required<Fields>): Fields {
  const out: Fields = {}
  if (next.text !== i.text) out.text = next.text
  if ((next.quantity === null ? null : Number(next.quantity)) !== (i.quantity === null ? null : Number(i.quantity))) out.quantity = next.quantity
  if (next.price_cents !== i.price_cents) out.price_cents = next.price_cents
  if (next.website !== i.website) out.website = next.website
  if (next.notes !== i.notes) out.notes = next.notes
  return out
}

/**
 * Saves the changed fields. "Merge when safe" (owner decision, 2026-10-02): `base` carries what
 * those fields held when editing started, so the server keeps someone else's change to other
 * fields instead of refusing. `force` (after a conflict, "Keep mine") saves over the newest copy.
 */
export async function saveItem(i: Item, changed: Fields, force: boolean, listId: string): Promise<Item | null> {
  if (Object.keys(changed).length === 0) return null
  const base = Object.fromEntries(Object.keys(changed).map((k) => [k, i[k as keyof Fields]]))
  let version = i.version
  if (force) {
    const latest = (await api<{ items: Item[] }>('GET', `/api/v1/lists/${listId}`)).items.find((x) => x.id === i.id)
    if (!latest) throw new ApiError(404, 'This item was deleted meanwhile.')
    version = latest.version
  }
  return api<Item>('PATCH', `/api/v1/list-items/${i.id}`, { ...changed, ...(force ? {} : { base }) }, { 'If-Match': `"${version}"` })
}
