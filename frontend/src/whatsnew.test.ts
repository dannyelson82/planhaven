import { describe, expect, it } from 'vitest'
import { isNewAccount, RELEASES, unseen } from './whatsnew.ts'

describe("What's new is cumulative", () => {
  it('shows every release newer than the last one seen', () => {
    const oldest = RELEASES[RELEASES.length - 1].version
    expect(unseen(oldest, null).map((r) => r.version)).toEqual(RELEASES.slice(0, -1).map((r) => r.version))
    expect(unseen(RELEASES[0].version, null)).toEqual([])
  })
  it('with none seen yet, shows everything since the account was made', () => {
    expect(unseen(null, '2020-01-01T00:00:00Z')).toEqual(RELEASES)
    expect(unseen(null, '2999-01-01T00:00:00Z')).toEqual([])
  })
  it('a brand-new account has nothing to catch up on', () => {
    expect(isNewAccount('2999-01-01T00:00:00Z')).toBe(true)
    expect(isNewAccount('2020-01-01T00:00:00Z')).toBe(false)
  })
})
