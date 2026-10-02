// A minimal client-side router: the path is the state; links use history.pushState.
import { useSyncExternalStore } from 'react'

const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  window.addEventListener('popstate', listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('popstate', listener)
  }
}

// A page with unsaved work can hold navigation (links, the menu, the browser's back button)
// until the person decides. The guard returns true to let the navigation happen.
type Guard = (to: string) => boolean
let guard: Guard | null = null
let lastPath = typeof window === 'undefined' ? '/' : window.location.pathname

export function setNavigationGuard(next: Guard | null): void {
  guard = next
}

if (typeof window !== 'undefined') {
  // Registered before any page subscribes, so it runs first on the browser's back/forward.
  window.addEventListener('popstate', () => {
    const to = window.location.pathname
    if (guard && !guard(to)) {
      // Stay: put the current page back in the address bar before anything re-renders.
      window.history.pushState(null, '', lastPath)
      return
    }
    lastPath = to
  })
}

export function navigate(path: string, options: { force?: boolean } = {}): void {
  if (!options.force && guard && !guard(path)) return
  window.history.pushState(null, '', path)
  lastPath = window.location.pathname
  listeners.forEach((l) => l())
}

export function usePath(): string {
  return useSyncExternalStore(
    subscribe,
    () => window.location.pathname,
    () => '/',
  )
}

export type Route =
  | { name: 'projects' }
  | { name: 'project'; id: string }
  | { name: 'list'; id: string }
  | { name: 'cost'; id: string }
  | { name: 'note'; id: string }
  | { name: 'assets' }
  | { name: 'trash' }
  | { name: 'templates' }
  | { name: 'template'; id: string }
  | { name: 'help'; slug: string }
  | { name: 'project-trash'; id: string }
  | { name: 'project-links'; id: string }
  | { name: 'share' }
  | { name: 'contacts' }
  | { name: 'suppliers' }
  | { name: 'notifications' }
  | { name: 'messages' }
  | { name: 'chores' }
  | { name: 'item'; id: string }
  | { name: 'conversation'; id: string }
  | { name: 'contact'; id: string }
  | { name: 'asset'; id: string }
  | { name: 'account' }
  | { name: 'invite' }
  | { name: 'reset' }
  | { name: 'admin' }
  | { name: 'not-found' }

const UUID = /^[0-9a-f-]{36}$/i

export function match(path: string): Route {
  const parts = path.split('/').filter(Boolean)
  if (parts.length === 0 || (parts.length === 1 && parts[0] === 'projects'))
    return { name: 'projects' }
  if (parts.length === 2 && parts[0] === 'projects' && UUID.test(parts[1]))
    return { name: 'project', id: parts[1] }
  if (parts.length === 3 && parts[0] === 'projects' && UUID.test(parts[1]) && parts[2] === 'trash')
    return { name: 'project-trash', id: parts[1] }
  if (parts.length === 3 && parts[0] === 'projects' && UUID.test(parts[1]) && parts[2] === 'links')
    return { name: 'project-links', id: parts[1] }
  if (parts.length === 1 && parts[0] === 's') return { name: 'share' }
  if (parts.length === 2 && parts[0] === 'lists' && UUID.test(parts[1])) return { name: 'list', id: parts[1] }
  if (parts.length === 2 && parts[0] === 'notes' && UUID.test(parts[1])) return { name: 'note', id: parts[1] }
  if (parts.length === 2 && parts[0] === 'costs' && UUID.test(parts[1])) return { name: 'cost', id: parts[1] }
  if (parts.length === 1 && parts[0] === 'assets') return { name: 'assets' }
  if (parts.length === 2 && parts[0] === 'assets' && UUID.test(parts[1])) return { name: 'asset', id: parts[1] }
  if (parts.length === 1 && parts[0] === 'contacts') return { name: 'contacts' }
  if (parts.length === 1 && parts[0] === 'suppliers') return { name: 'suppliers' }
  if (parts.length === 1 && parts[0] === 'notifications') return { name: 'notifications' }
  if (parts.length === 1 && parts[0] === 'messages') return { name: 'messages' }
  if (parts.length === 1 && parts[0] === 'chores') return { name: 'chores' }
  if (parts.length === 2 && parts[0] === 'i' && UUID.test(parts[1])) return { name: 'item', id: parts[1] }
  if (parts.length === 2 && parts[0] === 'messages' && UUID.test(parts[1])) return { name: 'conversation', id: parts[1] }
  if (parts.length === 2 && parts[0] === 'contacts' && UUID.test(parts[1])) return { name: 'contact', id: parts[1] }
  if (parts.length === 1 && parts[0] === 'trash') return { name: 'trash' }
  if (parts.length === 1 && parts[0] === 'templates') return { name: 'templates' }
  if (parts.length === 2 && parts[0] === 'templates' && UUID.test(parts[1])) return { name: 'template', id: parts[1] }
  if (parts[0] === 'help' && parts.length <= 2 && (parts.length === 1 || /^[a-z0-9-]{1,60}$/.test(parts[1])))
    return { name: 'help', slug: parts[1] ?? '' }
  if (parts.length === 1 && parts[0] === 'account') return { name: 'account' }
  if (parts.length === 1 && parts[0] === 'invite') return { name: 'invite' }
  if (parts.length === 1 && parts[0] === 'reset') return { name: 'reset' }
  if (parts.length === 1 && parts[0] === 'admin') return { name: 'admin' }
  return { name: 'not-found' }
}
