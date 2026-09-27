import { createHmac } from 'node:crypto'
import type { Page } from '@playwright/test'

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

/** Collects Content-Security-Policy violations and console errors on a page. */
export function watchForProblems(page: Page): string[] {
  const problems: string[] = []
  page.on('console', (msg) => {
    // Failed API calls are expected in some flows (e.g. "am I signed in?" answers 401) and are
    // shown in the UI; everything else logged as an error counts, including CSP violations.
    if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) {
      problems.push(`console: ${msg.text()}`)
    }
  })
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`))
  void page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`)
    })
  })
  return problems
}

export const ADMIN = {
  name: 'Test Admin',
  email: 'admin@example.com',
  password: 'correct horse battery staple 42',
}
