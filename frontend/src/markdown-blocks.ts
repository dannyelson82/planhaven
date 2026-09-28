// The user guide's Markdown, read into blocks (see markdown.tsx for how they're shown).

export type Block =
  | { kind: 'heading'; level: 1 | 2 | 3; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; items: { text: string; children: string[] }[] }
  | { kind: 'image'; alt: string; src: string }

const HEADING = /^(#{1,3})\s+(.*)$/
const BULLET = /^\s{0,1}[-*]\s+(.*)$/
const NUMBERED = /^\s{0,1}\d+\.\s+(.*)$/
const NESTED = /^\s{2,}[-*]\s+(.*)$/
const IMAGE = /^!\[([^\]]*)\]\(([^)\s]+)\)$/

export function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }
  for (const raw of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    const last = blocks[blocks.length - 1]
    let m: RegExpMatchArray | null
    if (!line.trim()) {
      flush()
    } else if ((m = line.match(HEADING))) {
      flush()
      blocks.push({ kind: 'heading', level: m[1].length as 1 | 2 | 3, text: m[2] })
    } else if ((m = line.trim().match(IMAGE)) && !paragraph.length) {
      blocks.push({ kind: 'image', alt: m[1], src: m[2] })
    } else if ((m = line.match(NESTED)) && last?.kind === 'list' && !paragraph.length) {
      last.items[last.items.length - 1].children.push(m[1])
    } else if ((m = line.match(BULLET)) || line.match(NUMBERED)) {
      flush()
      const ordered = !line.match(BULLET)
      const text = (m ?? line.match(NUMBERED))![1]
      if (last?.kind === 'list' && last.ordered === ordered) last.items.push({ text, children: [] })
      else blocks.push({ kind: 'list', ordered, items: [{ text, children: [] }] })
    } else if (/^\s{2,}\S/.test(line) && last?.kind === 'list' && !paragraph.length) {
      const item = last.items[last.items.length - 1] // a list item's text continued
      if (item.children.length) item.children[item.children.length - 1] += ` ${line.trim()}`
      else item.text += ` ${line.trim()}`
    } else {
      paragraph.push(line.trim())
    }
  }
  flush()
  return blocks
}

export function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}
