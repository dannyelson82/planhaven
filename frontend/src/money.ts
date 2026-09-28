// Money is kept in cents. Canadian dollars by default (owner's choice, 2026-09-28).
export const CURRENCY = 'CAD'

export type QuoteStatus = 'requested' | 'received' | 'accepted' | 'declined'
export const STATUS_LABEL: Record<QuoteStatus, string> = {
  requested: 'Requested', received: 'Received', accepted: 'Accepted', declined: 'Declined',
}
const format = new Intl.NumberFormat('en-CA', { style: 'currency', currency: CURRENCY })

export function formatCents(cents: number): string {
  return format.format(cents / 100)
}

/** "1,850.50" or "$1850" → 185050; null when it isn't an amount. */
export function parseAmount(text: string): number | null {
  const cleaned = text.replace(/[$,\s]/g, '')
  if (!/^-?\d+(\.\d{1,2})?$/.test(cleaned)) return null
  return Math.round(Number(cleaned) * 100)
}
