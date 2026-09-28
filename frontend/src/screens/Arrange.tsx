// Arranging a project page (owner request, 2026-09-28): the page is a grid of tiles, the groups
// (tasks, lists, notes, files, quotes and costs) and any single note, list or file given its
// own tile. Each person arranges their own view of each project; until they do, they see the
// owner's. Drag and drop (React Aria: touch, mouse and keyboard), no extra library.
import { useState } from 'react'
import { Button as AriaButton, GridList, GridListItem, useDragAndDrop } from 'react-aria-components'
import { SINGLE_LABEL, type Single, type Tile, tileKey, useLayout, useTileNames, type Width, WIDTH_LABEL } from '../layout.ts'
import { Button, Card, ErrorText } from '../ui.tsx'


/** The Arrange panel: drag tiles into order, pick each one's width, give a single note, list or
 * file its own tile (or put it back in its group). Every change is saved at once. */
export function ArrangePanel({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const { layout, save, reset } = useLayout(projectId)
  const { sources, nameOf } = useTileNames(projectId)
  // Tiles for things since deleted (or not shared with you) aren't listed.
  const tiles = layout.tiles.filter((t) => nameOf(t) !== null)
  const [choice, setChoice] = useState('')
  const placed = new Set(layout.tiles.map(tileKey))
  const choices = (Object.keys(sources) as Single[]).flatMap((kind) =>
    sources[kind].filter((x) => !placed.has(`${kind}:${x.id}`)).map((x) => ({ key: `${kind}:${x.id}`, label: `${SINGLE_LABEL[kind]}: ${x.title ?? x.filename}` })))

  const update = (next: Tile[]) => save.mutate(next)
  const { dragAndDropHooks } = useDragAndDrop({
    getItems: (keys) => [...keys].map((key) => ({ 'text/plain': nameOf(layout.tiles.find((t) => tileKey(t) === key)!) ?? String(key) })),
    onReorder: (e) => {
      const moving = layout.tiles.filter((t) => e.keys.has(tileKey(t)))
      const rest = layout.tiles.filter((t) => !e.keys.has(tileKey(t)))
      const at = rest.findIndex((t) => tileKey(t) === e.target.key) + (e.target.dropPosition === 'after' ? 1 : 0)
      update([...rest.slice(0, at), ...moving, ...rest.slice(at)])
    },
  })
  const setWidth = (tile: Tile, width: Width) => update(layout.tiles.map((t) => (tileKey(t) === tileKey(tile) ? { ...t, width } : t)))
  const putBack = (tile: Tile) => update(layout.tiles.filter((t) => tileKey(t) !== tileKey(tile)))
  const pullOut = () => {
    const [kind, id] = choice.split(':') as [Single, string]
    if (!id) return
    update([{ kind, id, width: 'wide' }, ...layout.tiles]) // at the top; drag it where you like
    setChoice('')
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Arrange this page</h2>
        <Button onPress={onDone}>Done</Button>
      </div>
      <p className="text-sm text-stone-600 dark:text-stone-400">
        Drag tiles by ≡ to reorder (or focus one and use the keyboard). Narrow, wide and full set how much of the row a tile
        takes on a computer; on a phone tiles stack in this order. Only your view changes.
      </p>
      <GridList aria-label="Tiles on this page" items={tiles.map((t) => ({ ...t, key: tileKey(t) }))} dragAndDropHooks={dragAndDropHooks}
        className="divide-y divide-stone-200 rounded-xl ring-1 ring-stone-200 dark:divide-stone-800 dark:ring-stone-800">
        {(t) => (
          <GridListItem id={t.key} textValue={nameOf(t) ?? t.key}
            className="flex flex-wrap items-center gap-2 bg-white px-2 py-1 outline-none data-[dragging]:opacity-50 data-[drop-target]:bg-brand-50 data-[focus-visible]:ring-2 data-[focus-visible]:ring-brand-600 dark:bg-stone-900">
            <AriaButton slot="drag" aria-label={`Move ${nameOf(t)}`} className="flex min-h-11 min-w-11 cursor-grab items-center justify-center rounded-lg text-xl text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800">≡</AriaButton>
            <span className="min-w-0 flex-1 truncate font-medium">{nameOf(t)}</span>
            <span className="flex gap-1" role="group" aria-label={`Width of ${nameOf(t)}`}>
              {(Object.keys(WIDTH_LABEL) as Width[]).map((w) => (
                <AriaButton key={w} aria-pressed={t.width === w} onPress={() => setWidth(t, w)}
                  className={`min-h-11 rounded-lg px-2 text-sm ${t.width === w ? 'bg-brand-100 font-semibold text-brand-700 dark:bg-stone-800 dark:text-brand-100' : 'text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800'}`}>
                  {WIDTH_LABEL[w]}
                </AriaButton>
              ))}
            </span>
            {t.id && (
              <AriaButton onPress={() => putBack(t)} aria-label={`Put ${nameOf(t)} back in its group`}
                className="min-h-11 rounded-lg px-2 text-sm text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800">Put back</AriaButton>
            )}
          </GridListItem>
        )}
      </GridList>
      {choices.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Give its own tile" value={choice} onChange={(e) => setChoice(e.target.value)}
            className="min-h-11 min-w-0 flex-1 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900">
            <option value="">Give a note, list or file its own tile…</option>
            {choices.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
          <Button variant="secondary" onPress={pullOut} isDisabled={!choice}>Add tile</Button>
        </div>
      )}
      {layout.source === 'mine' && (
        <Button variant="ghost" onPress={() => reset.mutate()} isDisabled={reset.isPending}>Go back to the shared arrangement</Button>
      )}
      <ErrorText error={save.error ?? reset.error} />
    </Card>
  )
}
