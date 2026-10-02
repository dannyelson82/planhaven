// The unread count for the bell (ADR 0018): checked every minute and when the app comes back
// to the screen.
import { useQuery } from '@tanstack/react-query'
import { api } from './api.ts'

export type Notice = { id: string; kind: string; title: string; body: string; url: string; created_at: string; read: boolean }

export function useUnread(): number {
  const unread = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => api<{ count: number }>('GET', '/api/v1/notifications/unread'),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
  })
  return unread.data?.count ?? 0
}

type TzSettings = { prefs: Record<string, string>; quiet_from: string | null; quiet_to: string | null; time_zone: string; previews: boolean }

/** Due dates and quiet hours follow this device's time zone: saved when it differs. */
export async function syncTimeZone(): Promise<void> {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
  if (!zone) return
  const s = await api<TzSettings>('GET', '/api/v1/notification-settings')
  if (s.time_zone !== zone) await api('PUT', '/api/v1/notification-settings', { ...s, time_zone: zone })
}
