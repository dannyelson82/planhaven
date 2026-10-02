// Small per-device view choices (e.g. which note cards are opened up), kept in this browser only.
// Never content: only ids and on/off. Storage can be missing or blocked (private windows), so
// every read and write falls back quietly to the default.
import { useState } from 'react'

const PREFIX = 'planhaven:view:'

export function useRemembered(key: string, fallback: boolean): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      const saved = window.localStorage.getItem(PREFIX + key)
      return saved === null ? fallback : saved === '1'
    } catch {
      return fallback
    }
  })
  const set = (next: boolean) => {
    setOn(next)
    try {
      if (next === fallback) window.localStorage.removeItem(PREFIX + key)
      else window.localStorage.setItem(PREFIX + key, next ? '1' : '0')
    } catch {
      // not remembered on this device; the choice still applies until the page is left
    }
  }
  return [on, set]
}

/** Forgets every remembered view choice (on sign-out, so the next person starts fresh). */
export function forgetViewChoices(): void {
  try {
    for (const k of Object.keys(window.localStorage)) if (k.startsWith(PREFIX)) window.localStorage.removeItem(k)
  } catch {
    // nothing stored
  }
}
