import { describe, expect, it } from 'vitest'
import { type Folder, folderChoices, trail } from './folders.ts'

const f = (id: string, name: string, parent: string | null = null, position = 0): Folder =>
  ({ id, name, parent_id: parent, position, projects: 0, version: 1 })
const all = [f('b', 'House'), f('a', 'Cars', null, -1), f('c', 'Corolla', 'a'), f('d', 'Tires', 'c')]

describe('folders', () => {
  it('lists folders as paths in tree order', () => {
    expect(folderChoices(all).map((c) => c.label)).toEqual(['Cars', 'Cars › Corolla', 'Cars › Corolla › Tires', 'House'])
  })
  it("leaves out a folder and what's inside it (it can't move into itself)", () => {
    expect(folderChoices(all, 'c').map((c) => c.id)).toEqual(['a', 'b'])
  })
  it('gives the path from the top', () => {
    const byId = new Map(all.map((x) => [x.id, x]))
    expect(trail(byId, 'd').map((x) => x.name)).toEqual(['Cars', 'Corolla', 'Tires'])
    expect(trail(byId, null)).toEqual([])
  })
})
