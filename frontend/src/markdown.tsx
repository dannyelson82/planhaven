// A small Markdown reader for the user guide (docs/user-guide/), turned into React elements:
// never HTML strings, so nothing in a page can run as code (and the strict CSP holds).
// Only what the guide uses: headings, paragraphs, bulleted and numbered lists (one level of
// nesting), **bold**, `code`, links, and screenshots on a line of their own.
import { type ReactNode } from 'react'
import { parseBlocks, slugify } from './markdown-blocks.ts'

export type Screens = (path: string) => { phone?: string; desktop?: string } | null

type Options = {
  /** Where a link to another guide page (other-page.md#part) goes in the app. */
  pageHref: (slug: string, anchor: string) => string
  /** Screenshots by their path in the guide, in phone and computer sizes. */
  screens: Screens
  link: (href: string, children: ReactNode, key: number) => ReactNode
}

const INLINE = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g

function inline(text: string, options: Options): ReactNode[] {
  const out: ReactNode[] = []
  let at = 0
  let key = 0
  for (const m of text.matchAll(INLINE)) {
    if (m.index > at) out.push(text.slice(at, m.index))
    if (m[1] !== undefined) out.push(<strong key={key++}>{inline(m[1], options)}</strong>)
    else if (m[2] !== undefined) out.push(<code key={key++} className="rounded bg-stone-100 px-1 text-sm dark:bg-stone-800">{m[2]}</code>)
    else out.push(linkTo(m[3], m[4], options, key++))
    at = m.index + m[0].length
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}

function linkTo(label: string, href: string, options: Options, key: number): ReactNode {
  const page = href.match(/^([a-z0-9-]+)\.md(?:#([a-z0-9-]+))?$/)
  if (page) return options.link(options.pageHref(page[1] === 'README' ? '' : page[1], page[2] ?? ''), label, key)
  if (/^https:\/\//.test(href)) {
    return <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="text-brand-700 underline dark:text-brand-100">{label}</a>
  }
  return label // anything else stays plain text
}

export function Markdown({ source, options }: { source: string; options: Options }) {
  return (
    <div className="space-y-3 leading-relaxed">
      {parseBlocks(source).map((b, i) => {
        if (b.kind === 'heading') {
          const Tag = (['h1', 'h2', 'h3'] as const)[b.level - 1]
          const size = ['text-2xl font-bold', 'pt-3 text-xl font-semibold', 'pt-2 text-lg font-semibold'][b.level - 1]
          return <Tag key={i} id={slugify(b.text)} className={size}>{inline(b.text, options)}</Tag>
        }
        if (b.kind === 'paragraph') return <p key={i}>{inline(b.text, options)}</p>
        if (b.kind === 'image') return <Screenshot key={i} alt={b.alt} src={b.src} screens={options.screens} />
        const List = b.ordered ? 'ol' : 'ul'
        return (
          <List key={i} className={`space-y-1 pl-6 ${b.ordered ? 'list-decimal' : 'list-disc'}`}>
            {b.items.map((item, j) => (
              <li key={j}>
                {inline(item.text, options)}
                {item.children.length > 0 && (
                  <ul className="mt-1 list-[circle] space-y-1 pl-6">
                    {item.children.map((c, k) => <li key={k}>{inline(c, options)}</li>)}
                  </ul>
                )}
              </li>
            ))}
          </List>
        )
      })}
    </div>
  )
}

/** A screenshot: the phone one on a phone, the computer one on a computer (whichever exists). */
function Screenshot({ alt, src, screens }: { alt: string; src: string; screens: Screens }) {
  const found = screens(src)
  if (!found || (!found.phone && !found.desktop)) return null
  const img = (url: string, className: string) => (
    <img src={url} alt={alt} loading="lazy" className={`max-w-full rounded-xl ring-1 ring-stone-200 dark:ring-stone-800 ${className}`} />
  )
  return (
    <figure className="space-y-1">
      {found.phone && img(found.phone, found.desktop ? 'max-h-[36rem] md:hidden' : 'max-h-[36rem]')}
      {found.desktop && img(found.desktop, found.phone ? 'hidden md:block' : '')}
      <figcaption className="text-sm text-stone-500">{alt}</figcaption>
    </figure>
  )
}
