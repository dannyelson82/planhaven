// Dragging tiles and cards straight around a project page while it's being arranged
// (ADR 0017). React Aria's drag and drop: mouse, touch, and keyboard (Move handle, then Tab to
// a tile and Enter). Outside Arrange mode these render their children unchanged.
import { type ReactNode, useContext, useRef } from 'react'
import { Button as AriaButton, useDrag, useDrop } from 'react-aria-components'
import { ArrangeContext } from '../layout.ts'

const TYPE = 'application/x-planhaven-tile'

/** A card (a note, list or file in its group) that can be dragged out onto the page. */
export function Movable({ dragKey, label, children }: { dragKey: string; label: string; children: ReactNode }) {
  const arrange = useContext(ArrangeContext)
  if (!arrange) return <>{children}</>
  return <DragSource dragKey={dragKey} label={label}>{children}</DragSource>
}

function DragSource({ dragKey, label, children, className = '' }: { dragKey: string; label: string; children: ReactNode; className?: string }) {
  const { dragProps, dragButtonProps, isDragging } = useDrag({
    hasDragButton: true,
    getItems: () => [{ [TYPE]: dragKey, 'text/plain': label }],
  })
  return (
    <div {...dragProps} data-movable={dragKey}
      className={`relative cursor-grab rounded-2xl outline-2 outline-offset-2 outline-dashed outline-stone-300 dark:outline-stone-700 ${isDragging ? 'opacity-40' : ''} ${className}`}>
      <AriaButton {...dragButtonProps} aria-label={`Move ${label}`}
        className="absolute -left-2 -top-3 z-10 flex min-h-8 items-center gap-1 rounded-full bg-brand-600 px-2 text-sm font-medium text-white shadow">
        <span aria-hidden="true">≡</span> Move
      </AriaButton>
      {children}
    </div>
  )
}

/** A tile on the page: while arranging, it can be dragged, and things can be dropped on it
 * (top half: before it; bottom half: after it; a card on its own group: back into it). */
export function TileSlot({ tileKey, label, className, children }: { tileKey: string; label: string; className: string; children: ReactNode }) {
  const arrange = useContext(ArrangeContext)
  const ref = useRef<HTMLDivElement>(null)
  const { dropProps, isDropTarget } = useDrop({
    ref,
    getDropOperation: (types) => (arrange && types.has(TYPE) ? 'move' : 'cancel'),
    onDrop: async (e) => {
      const item = e.items.find((i) => i.kind === 'text' && i.types.has(TYPE))
      if (!arrange || !item || item.kind !== 'text') return
      const key = await item.getText(TYPE)
      const height = ref.current?.getBoundingClientRect().height ?? 0
      arrange.move(key, tileKey, e.y < height / 2 ? 'before' : 'after')
    },
  })
  if (!arrange) return <div className={className}>{children}</div>
  return (
    <div ref={ref} {...dropProps} aria-label={`Tile: ${label}`} role="group"
      className={`${className} rounded-2xl ${isDropTarget ? 'ring-4 ring-brand-500' : ''}`}>
      <DragSource dragKey={tileKey} label={label} className="h-full p-2">{children}</DragSource>
    </div>
  )
}
