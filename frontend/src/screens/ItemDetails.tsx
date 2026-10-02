// A list item's details (owner request, 2026-10-02): tapping an item's name opens its quantity,
// price, website, notes and photos or files, with Edit from there. Ticking stays on the circle.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { Button as AriaButton, Dialog, DialogTrigger, Heading, Modal } from 'react-aria-components'
import { ApiError } from '../api.ts'
import { changes, type Item, saveItem } from '../items.ts'
import { formatCents, parseAmount } from '../money.ts'
import { Button, ErrorText, Field, Form } from '../ui.tsx'
import { ItemFiles } from './Attachments.tsx'


export function ItemDetails({ item, listId, projectId, priced, summary }: {
  item: Item; listId: string; projectId: string; priced: boolean; summary: ReactNode
}) {
  const [editing, setEditing] = useState(false)
  return (
    <DialogTrigger onOpenChange={(open) => { if (!open) setEditing(false) }}>
      <AriaButton aria-label={`Details: ${item.text}`} className="flex min-h-14 min-w-0 flex-1 cursor-pointer items-center gap-3 text-left outline-none data-[focus-visible]:ring-2 data-[focus-visible]:ring-brand-600">
        {summary}
      </AriaButton>
      <Modal isDismissable className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 sm:items-center">
        <Dialog className="max-h-[85dvh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
          {({ close }) => editing
            ? <EditItem item={item} listId={listId} priced={priced} done={() => setEditing(false)} />
            : <ViewItem item={item} projectId={projectId} priced={priced} onEdit={() => setEditing(true)} close={close} />}
        </Dialog>
      </Modal>
    </DialogTrigger>
  )
}

function ViewItem({ item: i, projectId, priced, onEdit, close }: { item: Item; projectId: string; priced: boolean; onEdit: () => void; close: () => void }) {
  const qty = i.quantity ? `${Number(i.quantity)}${i.unit ? ` ${i.unit}` : ''}` : null
  return (
    <div className="space-y-4">
      <Heading slot="title" className={`text-lg font-semibold ${i.checked ? 'text-stone-500 line-through' : ''}`}>{i.text}</Heading>
      <dl className="space-y-3 text-sm">
        <div><dt className="font-medium text-stone-500">Quantity</dt><dd>{qty ?? 'Not set'}</dd></div>
        {priced && <div><dt className="font-medium text-stone-500">Price each</dt><dd>{i.price_cents === null ? 'Not set' : formatCents(i.price_cents)}</dd></div>}
        <div>
          <dt className="font-medium text-stone-500">Website</dt>
          <dd className="break-all">
            {i.website ? <a href={i.website} target="_blank" rel="noopener noreferrer nofollow" className="text-brand-700 underline dark:text-brand-100">{i.website}</a> : 'None'}
          </dd>
        </div>
        <div><dt className="font-medium text-stone-500">Notes</dt><dd className="whitespace-pre-wrap">{i.notes || 'No notes'}</dd></div>
        <div><dt className="font-medium text-stone-500">Photos and files</dt><dd className="pt-1"><ItemFiles projectId={projectId} itemId={i.id} canEdit /></dd></div>
      </dl>
      <div className="flex gap-2">
        <Button onPress={onEdit} className="flex-1">Edit</Button>
        <Button variant="ghost" onPress={close}>Close</Button>
      </div>
    </div>
  )
}

function EditItem({ item: i, listId, priced, done }: { item: Item; listId: string; priced: boolean; done: () => void }) {
  const client = useQueryClient()
  const [text, setText] = useState(i.text)
  const [qty, setQty] = useState(i.quantity ? String(Number(i.quantity)) : '')
  const [price, setPrice] = useState(i.price_cents === null ? '' : (i.price_cents / 100).toFixed(2))
  const [website, setWebsite] = useState(i.website)
  const [notes, setNotes] = useState(i.notes)
  const cents = price.trim() ? parseAmount(price) : null
  const priceOk = !price.trim() || (cents !== null && cents >= 0)
  const webOk = !website.trim() || /^https?:\/\/\S+$/.test(website.trim())
  const save = useMutation({
    mutationFn: (force: boolean) => {
      const changed = changes(i, { text: text.trim(), quantity: qty.trim() || null, price_cents: priced ? cents : i.price_cents, website: website.trim(), notes })
      return saveItem(i, changed, force, listId)
    },
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['list', listId] }); done() },
  })
  const conflict = save.error instanceof ApiError && save.error.status === 409
  return (
    <Form onSubmit={(e) => { e.preventDefault(); if (text.trim() && priceOk && webOk) save.mutate(false) }}>
      <Heading slot="title" className="text-lg font-semibold">Edit item</Heading>
      <Field label="Name" isRequired maxLength={500} value={text} onChange={setText} />
      <div className="flex gap-2">
        <div className="w-24"><Field label="Qty" inputMode="decimal" maxLength={12} value={qty} onChange={setQty} /></div>
        {priced && <div className="min-w-0 flex-1"><Field label="Price each" inputMode="decimal" maxLength={16} value={price} onChange={setPrice} isInvalid={!priceOk} /></div>}
      </div>
      <Field label="Website" type="url" maxLength={500} value={website} onChange={setWebsite} isInvalid={!webOk}
        description="Starts with https://" />
      <Field label="Notes" multiline maxLength={4000} value={notes} onChange={setNotes} />
      {conflict ? (
        <div role="alert" className="space-y-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <p>Someone changed the same thing on this item (maybe you, on another device) while you were editing.</p>
          <div className="flex flex-wrap gap-2">
            <Button onPress={() => save.mutate(true)} isDisabled={save.isPending}>Keep mine</Button>
            <Button variant="secondary" onPress={async () => { await client.invalidateQueries({ queryKey: ['list', listId] }); done() }}>Keep theirs</Button>
          </div>
        </div>
      ) : <ErrorText error={save.error} />}
      <div className="flex gap-2">
        <Button type="submit" isDisabled={save.isPending || !text.trim() || !priceOk || !webOk} className="flex-1">Save</Button>
        <Button variant="ghost" onPress={done}>Cancel</Button>
      </div>
    </Form>
  )
}
