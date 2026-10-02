// Conversations and people for Messages (ADR 0018): shared shapes, and the unread count for
// the Messages tab (kept fresh by the live connection, src/me.ts).
import { useQuery } from '@tanstack/react-query'
import { api } from './api.ts'

export type Person = { id: string; name: string; online: boolean; last_seen: string | null }
export type Conversation = {
  id: string; title: string; is_group: boolean; members: Person[]; unread: number
  last_message_at: string | null; last_preview: string; last_from_me: boolean
}
export type Message = { id: string; sender_id: string; sender_name: string; body: string; created_at: string; deleted: boolean; mine: boolean }

export function useConversations() {
  return useQuery({ queryKey: ['conversations'], queryFn: () => api<Conversation[]>('GET', '/api/v1/conversations'), staleTime: 10_000 })
}

export function useMessagesUnread(): number {
  return (useConversations().data ?? []).reduce((sum, c) => sum + c.unread, 0)
}

/** "Online", "Last seen 5 min ago", "Last seen Oct 2", or "" (hidden or never). */
export function seen(p: Person): string {
  if (p.online) return 'Online'
  if (!p.last_seen) return ''
  const minutes = Math.round((Date.now() - new Date(p.last_seen).getTime()) / 60_000)
  if (minutes < 2) return 'Last seen just now'
  if (minutes < 60) return `Last seen ${minutes} min ago`
  if (minutes < 24 * 60) return `Last seen ${Math.round(minutes / 60)} h ago`
  return `Last seen ${new Date(p.last_seen).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
}
