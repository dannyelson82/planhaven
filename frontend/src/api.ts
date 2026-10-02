// Thin API client. Cookies carry the session (HttpOnly); the CSRF token is kept in memory
// only and sent on every unsafe request (SECURITY.md §7.2).

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export async function api<T>(
  method: Method,
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...headers },
  }
  if (method !== 'GET' && csrfToken) {
    ;(init.headers as Record<string, string>)['X-CSRF-Token'] = csrfToken
  }
  if (body !== undefined) {
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    // No connection (status 0; see offline.ts).
    throw new ApiError(0, "You're offline, so this wasn't saved. Try again when you're back online.")
  }
  if (response.status === 204) return undefined as T
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string'
        ? data.detail
        : data && typeof data === 'object' && 'title' in data && typeof data.title === 'string'
          ? data.title
          : 'Something went wrong.'
    throw new ApiError(response.status, detail)
  }
  return data as T
}

export type User = { id: string; email: string; display_name: string; is_admin: boolean }
export type Session = { user: User; csrf_token: string; mfa_verified: boolean; offline?: boolean }
export type Project = {
  id: string
  title: string
  description: string
  stage: Stage
  local_ai_only: boolean
  role: 'owner' | 'editor' | 'viewer' | null
  open_tasks: number
  updated_at: string
  version: number
  asset_id?: string | null
  asset_name?: string | null
  asset_kind?: string | null
}
export type Task = {
  id: string
  project_id: string
  title: string
  notes: string
  due_at: string | null
  due_all_day: boolean
  done: boolean
  version: number
  // Chores (ADR 0013)
  assignee_id?: string | null
  assigned_by?: string | null
  proof?: 'none' | 'photo' | 'note'
  repeat_freq?: 'daily' | 'weekly' | 'monthly' | null
  repeat_interval?: number
  repeat_days?: number[] | null
  waiting?: boolean
}
/** "Oct 15" (or "Wed, Oct 15, 2026" when long); all-day dates are shown as the day they are. */
export function dueLabel(t: Pick<Task, 'due_at' | 'due_all_day'>, long = false): string | null {
  if (!t.due_at) return null
  const date = new Date(t.due_at).toLocaleDateString(undefined, {
    ...(long ? { weekday: 'short', year: 'numeric' } : {}), month: 'short', day: 'numeric', ...(t.due_all_day ? { timeZone: 'UTC' } : {}),
  })
  if (t.due_all_day) return date
  // A due time (chores): shown too.
  return `${date}, ${new Date(t.due_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
}

/** A list item a task needs (from the project's lists). */
export type Need = { task_id: string; list_item_id: string; text: string; quantity: string | null; unit: string | null; checked: boolean; list_id: string; list_title: string }
export type Stage = 'idea' | 'planning' | 'ready' | 'in_progress' | 'done' | 'archived'

export const STAGES: { id: Stage; label: string }[] = [
  { id: 'idea', label: 'Idea' },
  { id: 'planning', label: 'Planning' },
  { id: 'ready', label: 'Ready' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'done', label: 'Done' },
  { id: 'archived', label: 'Archived' },
]

export function stageLabel(stage: string): string {
  return STAGES.find((s) => s.id === stage)?.label ?? stage
}

/** Upload a file as the raw request body (the server detects its type from the bytes). */
export async function uploadFile<T>(path: string, file: Blob, method: 'POST' | 'PUT' = 'POST'): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: { Accept: 'application/json', 'Content-Type': 'application/octet-stream', ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}) },
    body: file,
  })
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string' ? data.detail : 'Upload failed.'
    throw new ApiError(response.status, response.status === 413 ? 'This file is larger than the upload limit.' : detail)
  }
  return data as T
}
