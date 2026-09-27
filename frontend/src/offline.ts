// Offline support for the phone (phase 0.2, M6). Two things are kept in IndexedDB on this
// device only:
//  - a copy of what you last saw of lists, open tasks and your project list, so they open
//    without a connection (a shop with no signal);
//  - list changes made while offline (add, check off), sent in order when back online.
// Everything is wiped on sign-out, when the session ends, and when a different person signs
// in (SECURITY.md §7.12). No passwords, tokens or CSRF values are stored.
import { ApiError, api } from './api.ts'

const DB_NAME = 'planhaven-offline'
const CACHE = 'cache'
const OUTBOX = 'outbox'
const META = 'meta'

// `label` says what the change was, in words, in case the server refuses it later.
type Entry = { id?: number; method: 'POST' | 'PATCH'; path: string; body: unknown; headers: Record<string, string>; label: string }
export type OfflineUser = { id: string; email: string; display_name: string; is_admin: boolean }

let dbPromise: Promise<IDBDatabase> | null = null

function open(): Promise<IDBDatabase> {
  dbPromise ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      const db = request.result
      db.createObjectStore(CACHE)
      db.createObjectStore(OUTBOX, { keyPath: 'id', autoIncrement: true })
      db.createObjectStore(META)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB unavailable'))
  })
  return dbPromise
}

function run<T>(store: string, mode: IDBTransactionMode, action: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(store, mode)
        const request = action(tx.objectStore(store))
        tx.oncomplete = () => resolve(request.result)
        tx.onerror = () => reject(tx.error ?? new Error('IndexedDB error'))
      }),
  )
}

/** A network failure (as opposed to an answer from the server). */
export function isOffline(error: unknown): boolean {
  return error instanceof TypeError || (error instanceof ApiError && error.status === 0)
}

/** Fetch from the server, keeping a copy; without a connection, answer from the copy. */
export async function withOfflineCopy<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  try {
    const value = await fetcher()
    void run(CACHE, 'readwrite', (s) => s.put(value, key)).catch(() => undefined)
    return value
  } catch (error) {
    if (!isOffline(error)) throw error
    const copy = await run<unknown>(CACHE, 'readonly', (s) => s.get(key)).catch(() => undefined)
    if (copy === undefined) throw error
    return copy as T
  }
}

/** Change the offline copy too, so a change made offline survives reopening the app. */
export async function updateOfflineCopy<T>(key: string, change: (value: T) => T): Promise<void> {
  const copy = await run<unknown>(CACHE, 'readonly', (s) => s.get(key)).catch(() => undefined)
  if (copy !== undefined) await run(CACHE, 'readwrite', (s) => s.put(change(copy as T), key))
}

/** Send a list change now, or keep it for later when there's no connection.
 * Returns true if it was queued. */
export async function sendOrQueue(entry: Entry): Promise<boolean> {
  if (navigator.onLine) {
    try {
      await api(entry.method, entry.path, entry.body, entry.headers)
      return false
    } catch (error) {
      if (!isOffline(error)) throw error
    }
  }
  await run(OUTBOX, 'readwrite', (s) => s.add(entry))
  return true
}

export async function pendingChanges(): Promise<number> {
  return run(OUTBOX, 'readonly', (s) => s.count()).catch(() => 0)
}

let flushing = false

/** Send queued changes in order. Stops at the first network failure. A change the server
 * refuses (for example, the item was deleted meanwhile) is dropped and reported back. */
export async function flushOutbox(): Promise<{ sent: number; refused: string[] }> {
  const refused: string[] = []
  if (flushing) return { sent: 0, refused }
  flushing = true
  let sent = 0
  try {
    const entries = await run<Entry[]>(OUTBOX, 'readonly', (s) => s.getAll())
    for (const entry of entries) {
      try {
        await api(entry.method, entry.path, entry.body, entry.headers)
        sent += 1
      } catch (error) {
        if (isOffline(error)) break
        refused.push(entry.label)
      }
      await run(OUTBOX, 'readwrite', (s) => s.delete(entry.id as number))
    }
  } finally {
    flushing = false
  }
  return { sent, refused }
}

/** Who was signed in on this device (to open the app offline), or null. */
export async function offlineUser(): Promise<OfflineUser | null> {
  return (await run<OfflineUser | undefined>(META, 'readonly', (s) => s.get('user')).catch(() => undefined)) ?? null
}

/** Remember the signed-in person; a different person clears everything first. */
export async function rememberUser(user: OfflineUser): Promise<void> {
  const previous = await offlineUser()
  if (previous && previous.id !== user.id) await wipeOfflineData()
  const { id, email, display_name, is_admin } = user
  await run(META, 'readwrite', (s) => s.put({ id, email, display_name, is_admin }, 'user')).catch(() => undefined)
}

/** Remove everything kept on this device (sign-out, session ended). */
export async function wipeOfflineData(): Promise<void> {
  await Promise.all(
    [CACHE, OUTBOX, META].map((store) => run(store, 'readwrite', (s) => s.clear()).catch(() => undefined)),
  )
}

/** GET with an offline copy (lists, tasks, projects). */
export function cachedGet<T>(path: string): Promise<T> {
  return withOfflineCopy(`GET ${path}`, () => api<T>('GET', path))
}
