import { describe, expect, it, vi } from 'vitest'

import { createApi, forDisplay, isBaseModelId, type BuildType } from './api'

function type(over: Partial<BuildType> = {}): BuildType {
  return {
    id: 'x',
    key: 'k',
    label: 'L',
    description: null,
    active: true,
    sort_order: null,
    ...over,
  }
}

describe('forDisplay', () => {
  it('orders by sort_order ascending', () => {
    const out = forDisplay([
      type({ id: 'b', label: 'B', sort_order: 2 }),
      type({ id: 'a', label: 'A', sort_order: 1 }),
    ])
    expect(out.map((t) => t.id)).toEqual(['a', 'b'])
  })

  it('sorts a null sort_order LAST, not as zero', () => {
    // The column is nullable because the generated migration DDL does not apply
    // declared defaults. Treating null as 0 would jump every unordered row to
    // the top of the founder's picker — the opposite of "unspecified".
    const out = forDisplay([
      type({ id: 'none', label: 'Zed', sort_order: null }),
      type({ id: 'first', label: 'Alpha', sort_order: 5 }),
    ])
    expect(out.map((t) => t.id)).toEqual(['first', 'none'])
  })

  it('breaks ties on label so the order is stable between loads', () => {
    const out = forDisplay([
      type({ id: 'z', label: 'Zed', sort_order: 1 }),
      type({ id: 'a', label: 'Alpha', sort_order: 1 }),
    ])
    expect(out.map((t) => t.id)).toEqual(['a', 'z'])
  })

  it('does not mutate its input', () => {
    // The caller holds this array in React state; sorting in place would mutate
    // state and skip a re-render.
    const input = [type({ id: 'b', sort_order: 2 }), type({ id: 'a', sort_order: 1 })]
    forDisplay(input)
    expect(input.map((t) => t.id)).toEqual(['b', 'a'])
  })
})

describe('model selection', () => {
  function withFetch(payload: unknown) {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
      text: async () => JSON.stringify(payload),
    }))
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('getModelSelection reads GET /model on the admin app', async () => {
    const fetchMock = withFetch({ selected_model_id: 'a/b', options: [], agents: [] })
    const got = await createApi(() => 'tok').getModelSelection()

    expect(got.selected_model_id).toBe('a/b')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/api\/v1\/plugins\/idea-scout\/admin\/model$/)
    expect(init.method).toBe('GET')
    vi.unstubAllGlobals()
  })

  it('setModelSelection sends PUT /model with only the base model id', async () => {
    const fetchMock = withFetch({ selected_model_id: 'a/b', options: [], agents: [] })
    await createApi(() => 'tok').setModelSelection('a/b')

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/admin\/model$/)
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body as string)).toEqual({ model_id: 'a/b' })
    vi.unstubAllGlobals()
  })

  it('isBaseModelId rejects any colon suffix', () => {
    expect(isBaseModelId('anthropic/claude-sonnet-5.5')).toBe(true)
    expect(isBaseModelId('foo/bar:online')).toBe(false)
    expect(isBaseModelId('foo/bar:free')).toBe(false)
    expect(isBaseModelId('  ')).toBe(false)
  })
})
