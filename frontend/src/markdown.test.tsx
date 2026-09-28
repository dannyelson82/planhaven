import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { parseBlocks } from './markdown-blocks.ts'
import { Markdown } from './markdown.tsx'

const options = {
  pageHref: (slug: string, anchor: string) => `/help/${slug}${anchor ? `#${anchor}` : ''}`,
  screens: (path: string) => (path === 'screens/desktop/lists.jpg' ? { phone: '/p.jpg', desktop: '/d.jpg' } : null),
  link: (href: string, children: React.ReactNode, key: number) => <a key={key} href={href}>{children}</a>,
}
const html = (md: string) => renderToString(<Markdown source={md} options={options} />)

describe('user guide Markdown', () => {
  it('reads headings, lists with nesting and continued lines, paragraphs', () => {
    const blocks = parseBlocks('# Lists\n\nSome text\nmore text.\n\n1. First\n2. Second\n   continued\n\n- A\n  - nested\n- B\n')
    expect(blocks).toEqual([
      { kind: 'heading', level: 1, text: 'Lists' },
      { kind: 'paragraph', text: 'Some text more text.' },
      { kind: 'list', ordered: true, items: [{ text: 'First', children: [] }, { text: 'Second continued', children: [] }] },
      { kind: 'list', ordered: false, items: [{ text: 'A', children: ['nested'] }, { text: 'B', children: [] }] },
    ])
  })

  it('renders bold, code and links; guide links stay in the app', () => {
    const out = html('Tap **Edit**, type `phv_`, see [Lists](lists.md#edit-mode) or [site](https://example.com).')
    expect(out).toContain('<strong>Edit</strong>')
    expect(out).toContain('phv_</code>')
    expect(out).toContain('href="/help/lists#edit-mode"')
    expect(out).toContain('href="https://example.com" target="_blank" rel="noopener noreferrer"')
  })

  it('never produces HTML from the text, and drops unsafe links', () => {
    const out = html('<img src=x onerror=alert(1)> [x](javascript:alert(1)) [y](http://plain.example)')
    expect(out).not.toContain('<img')
    expect(out).toContain('&lt;img')
    expect(out).not.toContain('javascript:')
    expect(out).not.toContain('href="http://plain')
  })

  it('shows the phone screenshot on phones and the computer one on computers', () => {
    const out = html('![Edit mode](screens/desktop/lists.jpg)\n\n![Missing](screens/desktop/none.jpg)')
    expect(out).toContain('src="/p.jpg"')
    expect(out).toContain('md:hidden')
    expect(out).toContain('src="/d.jpg"')
    expect(out).not.toContain('Missing')
  })
})
