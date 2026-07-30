import { describe, expect, it } from 'vitest'

import { createApi, IDEATION_SEED_LIMIT, pressureTestUrl } from './api'

describe('pressureTestUrl', () => {
  it('points at the Ideation Engine on the same origin', () => {
    // Relative, not absolute: same-origin keeps the shared Cognito session
    // (ADR-0007) with no second sign-in.
    expect(pressureTestUrl('an idea')).toMatch(/^\/ideation\/\?seed=/)
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

  it('round-trips a pitch containing newlines', () => {
    const pitch = 'Line one.\n\nLine two.'
    const url = pressureTestUrl(pitch)

    expect(new URL(url, 'https://example.com').searchParams.get('seed')).toBe(pitch)
  })
})

describe('getLastUsedModel unwraps the shape the server actually returns', () => {
  // The server returns an OBJECT: `{"research_model": "…"}` or
  // `{"research_model": null}` (see app.py's /models/last-used). This was typed
  // as a bare `string | null`, and `request<T>` casts blindly (`as T`), so
  // TypeScript had nothing to compare against and the mismatch reached a
  // founder: an object is truthy, so `modelId` became the object, no
  // `<option value>` matched it, the browser displayed the FIRST model as if it
  // were chosen, and pressing Run now sent the object — 422 `string_type`,
  // `"input":{"research_model":null}`. The form looked complete and could not be
  // submitted at all.
  const withFetch = async (payload: unknown, run: (api: ReturnType<typeof createApi>) => Promise<unknown>) => {
    const original = globalThis.fetch
    globalThis.fetch = (async () =>
      ({ ok: true, status: 200, json: async () => payload, text: async () => '' }) as Response) as typeof fetch
    try {
      return await run(createApi(() => 'tok'))
    } finally {
      globalThis.fetch = original
    }
  }

  it('returns the slug as a string, not the envelope', async () => {
    const got = await withFetch({ research_model: 'anthropic/claude-sonnet-4:online' }, (api) =>
      api.getLastUsedModel(),
    )

    expect(got).toBe('anthropic/claude-sonnet-4:online')
    expect(typeof got).toBe('string')
  })

  it('returns null when the founder has no prior run, rather than a truthy envelope', async () => {
    // The failure mode exactly: `{research_model: null}` is truthy, so every
    // downstream `if (selectedModel)` took the wrong branch.
    const got = await withFetch({ research_model: null }, (api) => api.getLastUsedModel())

    expect(got).toBeNull()
  })
})
