import { describe, expect, it } from 'vitest'
import { match } from './router.ts'
import { toMarkdown } from './markdown.ts'

describe('notes', () => {
  it('routes to a note', () => {
    const id = '0192a0e1-0000-7000-8000-000000000000'
    expect(match(`/notes/${id}`)).toEqual({ name: 'note', id })
    expect(match('/notes/nope')).toEqual({ name: 'not-found' })
  })

  it('keeps a Markdown copy of the note', () => {
    const doc = {
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Deck' }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'Use ' }, { type: 'text', text: 'cedar', marks: [{ type: 'bold' }] }] },
        {
          type: 'taskList',
          content: [
            { type: 'taskItem', attrs: { checked: true }, content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Measure' }] }] },
            { type: 'taskItem', attrs: { checked: false }, content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Buy screws' }] }] },
          ],
        },
        { type: 'bulletList', content: [{ type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a' }] }] }] },
      ],
    }
    expect(toMarkdown(doc)).toBe('## Deck\n\nUse **cedar**\n\n- [x] Measure\n- [ ] Buy screws\n\n- a')
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
