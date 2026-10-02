import { createHmac } from 'node:crypto'
import type { Locator, Page } from '@playwright/test'

/** RFC 6238 TOTP (SHA-1, 6 digits, 30 s): a test stand-in for an authenticator app. */
export function totp(secretBase32: string, offsetSteps = 0): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const c of secretBase32.replace(/=+$/, '').toUpperCase()) {
    bits += alphabet.indexOf(c).toString(2).padStart(5, '0')
  }
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000) + offsetSteps))
  const hmac = createHmac('sha1', key).update(counter).digest()
  const offset = hmac[hmac.length - 1] & 0xf
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000
  return code.toString().padStart(6, '0')
}

/** Collects Content-Security-Policy violations and console errors on a page.
 *
 * allowBrowserEditingStyles: ignore inline-style violations raised by the browser itself (no
 * script behind them), which Chrome's contenteditable editing can cause. Any violation caused
 * by a script still counts. */
export function watchForProblems(page: Page, options: { allowBrowserEditingStyles?: boolean } = {}): string[] {
  const problems: string[] = []
  page.on('console', (msg) => {
    const text = msg.text()
    // Failed API calls are expected in some flows (e.g. "am I signed in?" answers 401) and are
    // shown in the UI; everything else logged as an error counts, including CSP violations.
    if (msg.type() !== 'error' || text.startsWith('Failed to load resource')) return
    // Chrome's own message for every inline-style violation; the listener below reports each
    // violation with where it came from, and decides.
    if (options.allowBrowserEditingStyles && text.startsWith('Applying inline style violates')) return
    if (options.allowBrowserEditingStyles && text === 'CSP violation: style-src-attr inline (browser)') return
    problems.push(`console: ${text}`)
  })
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`))
  void page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI} ${e.sourceFile || '(browser)'}`)
    })
  })
  return problems
}

export const ADMIN = {
  name: 'Test Admin',
  email: 'admin@example.com',
  password: 'correct horse battery staple 42',
}

/** Tick a task or list item: its box only (tapping the words opens its details). */
export function tick(page: Page, name: string): Promise<void> {
  return page.locator('label').filter({ has: page.getByRole('checkbox', { name, exact: true }) }).click()
}

/** A task or list item's row (the words; it opens the details). */
export function row(page: Page, name: string): Locator {
  return page.getByRole('button', { name: `Details: ${name}`, exact: true })
}
