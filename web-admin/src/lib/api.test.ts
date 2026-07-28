import { describe, expect, it } from 'vitest'

import { forDisplay, type BuildType } from './api'

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
