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

export function navigate(path: string): void {
  window.history.pushState(null, '', path)
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
  | { name: 'account' }
  | { name: 'invite' }
  | { name: 'not-found' }

const UUID = /^[0-9a-f-]{36}$/i

export function match(path: string): Route {
  const parts = path.split('/').filter(Boolean)
  if (parts.length === 0 || (parts.length === 1 && parts[0] === 'projects'))
    return { name: 'projects' }
  if (parts.length === 2 && parts[0] === 'projects' && UUID.test(parts[1]))
    return { name: 'project', id: parts[1] }
  if (parts.length === 2 && parts[0] === 'lists' && UUID.test(parts[1])) return { name: 'list', id: parts[1] }
  if (parts.length === 1 && parts[0] === 'account') return { name: 'account' }
  if (parts.length === 1 && parts[0] === 'invite') return { name: 'invite' }
  return { name: 'not-found' }
}
