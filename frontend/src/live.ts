// Live updates for an open project (ADR 0011): the server says only what kind of thing changed
// ("tasks", "lists", ...) and the page refetches it through the normal, permission-checked API.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

const KINDS: Record<string, (id: string) => unknown[][]> = {
  project: (id) => [['project', id], ['projects']],
  tasks: (id) => [['tasks', id], ['project', id], ['projects']],
  lists: (id) => [['lists', id], ['list']],
  notes: (id) => [['notes', id]],
  attachments: (id) => [['attachments', id]],
}

export function useLiveProject(projectId: string | undefined): void {
  const client = useQueryClient()
  useEffect(() => {
    if (!projectId) return
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let retries = 0
    let stopped = false
    const connect = () => {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/live/projects/${projectId}`)
      socket.onopen = () => {
        // Anything could have changed while this page was closed or offline.
        for (const keys of Object.values(KINDS)) for (const k of keys(projectId)) void client.invalidateQueries({ queryKey: k })
        retries = 0
      }
      socket.onmessage = (event: MessageEvent<string>) => {
        let kind: unknown
        try {
          kind = (JSON.parse(event.data) as { kind?: unknown }).kind
        } catch {
          return
        }
        const keys = typeof kind === 'string' && Object.hasOwn(KINDS, kind) ? KINDS[kind](projectId) : []
        for (const k of keys) void client.invalidateQueries({ queryKey: k })
      }
      socket.onclose = (event) => {
        socket = null
        if (stopped || [4401, 4403, 4404].includes(event.code)) return
        retries += 1
        timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** retries) * (0.5 + Math.random() / 2))
      }
    }
    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [projectId, client])
}
