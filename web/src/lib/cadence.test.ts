import { describe, expect, it } from 'vitest'

import { DEFAULT_CADENCE_DAYS, ageInDays, isStale } from './cadence'

const NOW = new Date('2026-09-09T12:00:00.000Z')

describe('isStale', () => {
  it('is not stale just under the cadence', () => {
    const created = new Date(NOW.getTime() - (DEFAULT_CADENCE_DAYS * 24 * 60 * 60 * 1000 - 1))
    expect(isStale(created.toISOString(), NOW)).toBe(false)
  })

  it('is stale at exactly the cadence boundary', () => {
    const created = new Date(NOW.getTime() - DEFAULT_CADENCE_DAYS * 24 * 60 * 60 * 1000)
    expect(isStale(created.toISOString(), NOW)).toBe(true)
  })

  it('is stale well past the cadence', () => {
    const created = new Date(NOW.getTime() - 30 * 24 * 60 * 60 * 1000)
    expect(isStale(created.toISOString(), NOW)).toBe(true)
  })

  it('treats a missing timestamp as stale', () => {
    expect(isStale(null, NOW)).toBe(true)
  })

  it('treats an unparseable timestamp as stale', () => {
    expect(isStale('not-a-date', NOW)).toBe(true)
  })

  it('honours a custom cadence', () => {
    const created = new Date(NOW.getTime() - 2 * 24 * 60 * 60 * 1000)
    expect(isStale(created.toISOString(), NOW, 1)).toBe(true)
    expect(isStale(created.toISOString(), NOW, 3)).toBe(false)
  })
})

describe('ageInDays', () => {
  it('floors to whole days', () => {
    const created = new Date(NOW.getTime() - 2.9 * 24 * 60 * 60 * 1000)
    expect(ageInDays(created.toISOString(), NOW)).toBe(2)
  })

  it('is null for a missing timestamp', () => {
    expect(ageInDays(null, NOW)).toBeNull()
  })

  it('is null for an unparseable timestamp', () => {
    expect(ageInDays('not-a-date', NOW)).toBeNull()
  })
})
