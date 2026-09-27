import type { JSONContent } from '@tiptap/react'

/** A Markdown copy of the note for previews, search, AI and export. */
export function toMarkdown(node: JSONContent, depth = 0): string {
  const inline = (n: JSONContent): string =>
    (n.content ?? []).map((c) => {
      if (c.type === 'hardBreak') return '\n'
      let text = c.text ?? inline(c)
      for (const mark of c.marks ?? []) {
        if (mark.type === 'bold') text = `**${text}**`
        else if (mark.type === 'italic') text = `*${text}*`
        else if (mark.type === 'strike') text = `~~${text}~~`
        else if (mark.type === 'code') text = `\`${text}\``
      }
      return text
    }).join('')
  const indent = '  '.repeat(depth)
  const blocks = (n: JSONContent, d: number) => (n.content ?? []).map((c) => toMarkdown(c, d))
  switch (node.type) {
    case 'doc':
      return blocks(node, 0).join('\n\n').trim()
    case 'paragraph':
      return inline(node)
    case 'heading':
      return `${'#'.repeat(Number(node.attrs?.level ?? 2))} ${inline(node)}`
    case 'blockquote':
      return blocks(node, depth).map((b) => `> ${b}`).join('\n')
    case 'codeBlock':
      return `\`\`\`\n${inline(node)}\n\`\`\``
    case 'horizontalRule':
      return '---'
    case 'bulletList':
    case 'orderedList':
    case 'taskList':
      return (node.content ?? []).map((item, i) => {
        const marker = node.type === 'orderedList' ? `${i + 1}.` : node.type === 'taskList' ? `- [${item.attrs?.checked ? 'x' : ' '}]` : '-'
        const [first, ...rest] = blocks(item, depth + 1)
        return [`${indent}${marker} ${first ?? ''}`, ...rest].join('\n')
      }).join('\n')
    default:
      return inline(node)
  }
}
