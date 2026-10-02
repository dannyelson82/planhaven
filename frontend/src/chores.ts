// Chores (ADR 0013): shared shapes and helpers for the Chores page and task details.
import { useQuery } from '@tanstack/react-query'
import { api } from './api.ts'

export type Proof = 'none' | 'photo' | 'note'
export type Freq = 'daily' | 'weekly' | 'monthly'
export type Chore = {
  id: string; project_id: string; project_title: string | null; title: string; notes: string
  due_at: string | null; due_all_day: boolean; done: boolean; assignee_id: string | null; assigned_by: string | null
  proof: Proof; repeat_freq: Freq | null; repeat_interval: number; repeat_days: number[] | null; version: number
  status: 'awaiting_photo' | 'pending' | 'approved' | 'sent_back' | null; comment: string
}

export const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function repeatText(c: Pick<Chore, 'repeat_freq' | 'repeat_interval' | 'repeat_days'>): string | null {
  if (!c.repeat_freq) return null
  const n = c.repeat_interval
  if (c.repeat_freq === 'daily') return n === 1 ? 'Every day' : `Every ${n} days`
  if (c.repeat_freq === 'monthly') return n === 1 ? 'Every month' : `Every ${n} months`
  const days = (c.repeat_days ?? []).map((d) => DAYS[d]).join(', ')
  return `${n === 1 ? 'Every week' : `Every ${n} weeks`}${days ? ` on ${days}` : ''}`
}


export function useMyChores() {
  return useQuery({ queryKey: ['chores'], queryFn: () => api<Chore[]>('GET', '/api/v1/chores'), staleTime: 15_000 })
}

