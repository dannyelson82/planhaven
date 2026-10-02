// The signed-in person's live connection (ADR 0018): told when messages or notifications
// change (never their content), and the server counts the person as online while it's open.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

const KINDS: Record<string, unknown[][]> = {
  messages: [['conversations'], ['messages']],
  notifications: [['notifications'], ['chores']],
}

export function useLiveMe(): void {
  const client = useQueryClient()
  useEffect(() => {
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let retries = 0
    let stopped = false
    const connect = () => {
      if (stopped) return
      // Offline (no signal): wait until the device is back online.
      if (!navigator.onLine) {
        window.addEventListener('online', connect, { once: true })
        return
      }
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/live/me`)
      socket.onopen = () => {
        for (const keys of Object.values(KINDS)) for (const k of keys) void client.invalidateQueries({ queryKey: k })
        retries = 0
      }
      socket.onmessage = (event: MessageEvent<string>) => {
        let kind: unknown
        try {
          kind = (JSON.parse(event.data) as { kind?: unknown }).kind
        } catch {
          return
        }
        if (typeof kind === 'string' && Object.hasOwn(KINDS, kind)) {
          for (const k of KINDS[kind]) void client.invalidateQueries({ queryKey: k })
        }
      }
      socket.onclose = (event) => {
        socket = null
        if (stopped || event.code === 4401) return
        retries += 1
        timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** retries) * (0.5 + Math.random() / 2))
      }
    }
    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      window.removeEventListener('online', connect)
      socket?.close()
    }
  }, [client])
}
