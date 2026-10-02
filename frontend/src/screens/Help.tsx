// The user guide, in the app (owner request, 2026-09-28): the pages in docs/user-guide/ with
// their screenshots, phone or computer size to match the screen. Loaded only when opened.
import { type ReactNode, useEffect } from 'react'
import { Markdown } from '../markdown.tsx'
import { Button, Link } from '../ui.tsx'
import { openTour } from '../whatsnew.ts'

const PAGES = import.meta.glob('../../../docs/user-guide/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const SHOTS = import.meta.glob('../../../docs/user-guide/screens/*/*.jpg', { query: '?url', import: 'default', eager: true }) as Record<string, string>

const page = (slug: string) => PAGES[`../../../docs/user-guide/${slug || 'README'}.md`]

function screens(path: string) {
  const name = path.match(/^screens\/(?:phone|desktop)\/([a-z0-9-]+\.jpg)$/)?.[1]
  if (!name) return null
  return {
    phone: SHOTS[`../../../docs/user-guide/screens/phone/${name}`],
    desktop: SHOTS[`../../../docs/user-guide/screens/desktop/${name}`],
  }
}

const options = {
  pageHref: (slug: string, anchor: string) => `/help${slug ? `/${slug}` : ''}${anchor ? `#${anchor}` : ''}`,
  screens,
  link: (href: string, children: ReactNode, key: number) => (
    <Link key={key} to={href} className="text-brand-700 underline dark:text-brand-100">{children}</Link>
  ),
}

export default function HelpScreen({ slug }: { slug: string }) {
  const source = page(slug)
  useEffect(() => {
    const anchor = decodeURIComponent(window.location.hash.slice(1))
    if (anchor) document.getElementById(anchor)?.scrollIntoView()
    else window.scrollTo(0, 0)
  }, [slug])
  if (!source) return <p>This help page doesn't exist. <Link to="/help" className="text-brand-700 dark:text-brand-100">All help</Link></p>
  return (
    <article className="max-w-3xl space-y-4">
      {slug && <Link to="/help" className="text-sm text-brand-700 dark:text-brand-100">← All help</Link>}
      {!slug && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onPress={() => openTour('welcome')}>Take the tour again</Button>
          <Button variant="secondary" onPress={() => openTour('whats-new')}>What's new</Button>
        </div>
      )}
      <Markdown source={source} options={options} />
      {slug && <p className="pt-4"><Link to="/help" className="text-brand-700 dark:text-brand-100">← All help</Link></p>}
    </article>
  )
}
