import { describe, expect, it } from 'vitest'
import { match } from './router.ts'

describe('notes', () => {
  it('routes to a note', () => {
    const id = '0192a0e1-0000-7000-8000-000000000000'
    expect(match(`/notes/${id}`)).toEqual({ name: 'note', id })
    expect(match('/notes/nope')).toEqual({ name: 'not-found' })
  })

})

describe('money', async () => {
  const { formatCents, parseAmount } = await import('./money.ts')
  it('reads and shows amounts in cents', () => {
    expect(parseAmount('1,850.50')).toBe(185050)
    expect(parseAmount('$12')).toBe(1200)
    expect(parseAmount('-3.5')).toBe(-350)
    expect(parseAmount('abc')).toBeNull()
    expect(parseAmount('1.234')).toBeNull()
    expect(formatCents(185050)).toContain('1,850.50')
  })
})

describe('note preview', async () => {
  const { notePreview } = await import('./preview.ts')
  it('leaves out checkbox lines when the card shows them', () => {
    const md = '## Deck\n\nUse **cedar**\n\n- [x] test 1\n- [ ] test2\n- [ ] '
    expect(notePreview(md, true)).toBe('Deck · Use cedar')
    expect(notePreview('- [x] test 1\n- [ ] test2', true)).toBe('')
    expect(notePreview('- a\n- b', false)).toBe('a · b')
    // A checkbox holding two paragraphs: its second line isn't repeated under the title.
    expect(notePreview('Intro\n\n- [ ] one\ncontinued\n- [ ] two\n\nAfter', true)).toBe('Intro · After')
  })
})
