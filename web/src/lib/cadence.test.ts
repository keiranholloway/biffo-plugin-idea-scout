/**
 * These cover phrasing only, and that is the point.
 *
 * This module used to own `isStale`, which compared a run's `created_at`
 * against a hardcoded `DEFAULT_CADENCE_DAYS = 7`. Once the interval became an
 * owner-scoped preference (#50) that comparison had to move to the server —
 * see `service._derive_cadence_state` and `tests/test_idea_scout_cadence.py`,
 * which is where the staleness rule is now asserted. Keeping a copy here would
 * have meant deciding a founder's cadence against a constant they may never
 * have chosen.
 *
 * So there is deliberately nothing below that decides whether a scout runs.
 */

import { describe, expect, it } from 'vitest'

import { ageInDays, nextDueLabel } from './cadence'

const NOW = new Date('2026-09-09T12:00:00.000Z')
const DAY_MS = 24 * 60 * 60 * 1000

describe('ageInDays', () => {
  it('floors to whole days', () => {
    const created = new Date(NOW.getTime() - 2.9 * DAY_MS)
    expect(ageInDays(created.toISOString(), NOW)).toBe(2)
  })

  it('is null for a missing timestamp', () => {
    expect(ageInDays(null, NOW)).toBeNull()
  })

  it('is null for an unparseable timestamp', () => {
    expect(ageInDays('not-a-date', NOW)).toBeNull()
  })
})

describe('nextDueLabel', () => {
  it('says how many whole days are left', () => {
    const due = new Date(NOW.getTime() + 6 * DAY_MS)
    expect(nextDueLabel(due.toISOString(), NOW)).toBe('due in 6 days')
  })

  it('rounds a part-day up rather than down', () => {
    // 5.2 days out is "in 6 days", never "in 5" — the label must not claim a
    // scout is closer than it is, and must never read "in 0 days".
    const due = new Date(NOW.getTime() + 5.2 * DAY_MS)
    expect(nextDueLabel(due.toISOString(), NOW)).toBe('due in 6 days')
  })

  it('reads as tomorrow inside the last day', () => {
    const due = new Date(NOW.getTime() + 0.5 * DAY_MS)
    expect(nextDueLabel(due.toISOString(), NOW)).toBe('due tomorrow')
  })

  it('is due now at the boundary', () => {
    expect(nextDueLabel(NOW.toISOString(), NOW)).toBe('due now')
  })

  it('is due now once the date has passed', () => {
    const due = new Date(NOW.getTime() - 30 * DAY_MS)
    expect(nextDueLabel(due.toISOString(), NOW)).toBe('due now')
  })

  it('is null when there is no due date — cadence is off, or there are no runs', () => {
    expect(nextDueLabel(null, NOW)).toBeNull()
  })

  it('is null for an unparseable due date rather than rendering NaN', () => {
    expect(nextDueLabel('not-a-date', NOW)).toBeNull()
  })
})
