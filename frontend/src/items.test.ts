import { describe, expect, it } from 'vitest'
import { changes, type Item } from './items.ts'

const item: Item = { id: 'i', text: 'Clamps', quantity: '2.000', unit: null, price_cents: 150, notes: '', website: '', checked: false, version: 3 }
const same = { text: 'Clamps', quantity: '2', price_cents: 150, website: '', notes: '' }

describe('changes (merge when safe)', () => {
  it('sends nothing when nothing changed', () => {
    expect(changes(item, same)).toEqual({})
  })
  it('sends only the fields that changed', () => {
    expect(changes(item, { ...same, notes: 'Stainless', quantity: '3' })).toEqual({ notes: 'Stainless', quantity: '3' })
  })
  it('treats clearing a value as a change', () => {
    expect(changes(item, { ...same, quantity: null, price_cents: null })).toEqual({ quantity: null, price_cents: null })
  })
})
