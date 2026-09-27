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
  const response = await fetch(path, init)
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
export type Session = { user: User; csrf_token: string; mfa_verified: boolean }
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
}
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
