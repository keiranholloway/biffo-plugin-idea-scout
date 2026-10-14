import { describe, expect, it } from 'vitest'

import { IDEATION_SEED_LIMIT, pressureTestUrl } from './api'

describe('pressureTestUrl', () => {
  it('does not throw when the cut splits a surrogate pair', () => {
    const url = pressureTestUrl('a'.repeat(IDEATION_SEED_LIMIT - 1) + '😀')
    expect(decodeURIComponent(url.split('seed=')[1])).toBe('a'.repeat(IDEATION_SEED_LIMIT - 1))
  })

  it("points at the Ideation Engine's dashboard page on the same origin", () => {
    // Relative, not absolute: same-origin keeps the shared Cognito session
    // (ADR-0007) with no second sign-in. The dashboard page hands ?seed to the
    // embedded plugin. The old /ideation/ path was retired on 2026-10-01 and now
    // serves the portal's home page.
    expect(pressureTestUrl('an idea')).toMatch(/^\/dashboard\/ideation-engine\/\?seed=/)
  })

  it('encodes a pitch that would otherwise break the query string', () => {
    const url = pressureTestUrl('A&B tools: 100% "better"? #1')

    expect(url).not.toContain('&B')
    expect(url).not.toContain('#1')
    const seed = new URL(url, 'https://example.com').searchParams.get('seed')
    expect(seed).toBe('A&B tools: 100% "better"? #1')
  })

  it('truncates to the limit the Ideation Engine actually enforces', () => {
    // Its StartSessionRequest bounds seed_idea at 16,000 characters. Sending
    // more 422s *there*, which is a worse place for a founder to find out.
    const url = pressureTestUrl('x'.repeat(IDEATION_SEED_LIMIT + 500))

    const seed = new URL(url, 'https://example.com').searchParams.get('seed')
    expect(seed).toHaveLength(IDEATION_SEED_LIMIT)
  })

  it('includes the candidate id alongside the seed', () => {
    const url = pressureTestUrl('an idea', 'cand 1&2')
    const params = new URL(url, 'https://example.com').searchParams

    expect(params.get('seed')).toBe('an idea')
    expect(params.get('candidate_id')).toBe('cand 1&2')
  })

  it('omits candidate_id when none is given', () => {
    expect(pressureTestUrl('an idea')).not.toContain('candidate_id')
  })

  it('round-trips a pitch containing newlines', () => {
    const pitch = 'Line one.\n\nLine two.'
    const url = pressureTestUrl(pitch)

    expect(new URL(url, 'https://example.com').searchParams.get('seed')).toBe(pitch)
  })
})

