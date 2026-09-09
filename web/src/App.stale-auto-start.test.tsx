/**
 * Pull-based cadence (#50, option A): a founder returning to the surface with
 * a stale last run gets a fresh one started for them, instead of the empty
 * "Run now" form. This is the correctness-critical half of that feature: the
 * trigger must fire exactly once per genuinely-stale return, and must never
 * fire a second time behind it — a refresh, a second tab, or a
 * back-navigation moments later must see the just-started run as the reason
 * not to start another one, not as a fresh occasion to.
 *
 * Every scenario reads `listRuns` fresh, the same way two real tabs would —
 * there is no shared client-side lock between them. The guard that has to
 * hold is server-truth: once a run is `in_flight`, no read of it looks stale
 * enough to re-trigger, regardless of how old its `created_at` is.
 */

import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listRuns = vi.fn()
const startRun = vi.fn()

vi.mock('./lib/auth', () => ({
  getCurrentSession: () =>
    Promise.resolve({
      getIdToken: () => ({ getJwtToken: () => 'test-token' }),
    }),
  getFreshIdToken: () => Promise.resolve('test-token'),
}))

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    createApi: () => ({
      getFormOptions: () =>
        Promise.resolve({
          build_types: [{ key: 'micro-saas', label: 'MicroSaaS', description: null }],
          business_models: [],
          models: [],
          preferences: [],
          complexity_levels: [{ value: 3, label: 'moderate' }],
        }),
      getLastUsedModel: () => Promise.resolve(null),
      listRuns,
      getRun: vi.fn(),
      startRun,
      deleteRun: vi.fn(),
      getCandidates: vi.fn(),
    }),
  }
})

const { default: App } = await import('./App')

const DAY_MS = 24 * 60 * 60 * 1000

function run(overrides: Record<string, unknown> = {}) {
  return {
    run_id: 'r1',
    status: 'complete',
    build_type: 'micro-saas',
    complexity: 3,
    complexity_label: 'moderate',
    preferences: [],
    research_model: undefined,
    business_model: null,
    created_at: new Date(Date.now() - 10 * DAY_MS).toISOString(),
    in_flight: false,
    failure_reason: null,
    ...overrides,
  }
}

describe('auto-starting a stale scout on return (#50)', () => {
  beforeEach(() => {
    listRuns.mockReset()
    startRun.mockReset()
  })

  it('starts a fresh scout when the last one is stale and finished', async () => {
    listRuns.mockResolvedValue([run()])
    startRun.mockResolvedValue(
      run({ run_id: 'auto1', status: 'researching', in_flight: true, created_at: new Date().toISOString() }),
    )

    render(<App />)

    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(1))
    expect(startRun).toHaveBeenCalledWith('micro-saas', 3, [], undefined, undefined)

    // The founder must be able to tell this happened *to* them, not just that
    // a run appeared — otherwise it is indistinguishable from a bug.
    await waitFor(() => expect(document.body.textContent).toMatch(/started automatically/i))
  })

  it('does not auto-start when there is no run history at all', async () => {
    listRuns.mockResolvedValue([])

    render(<App />)

    await waitFor(() => expect(listRuns).toHaveBeenCalled())
    expect(startRun).not.toHaveBeenCalled()
  })

  it('does not auto-start when the last run is not yet stale', async () => {
    listRuns.mockResolvedValue([run({ created_at: new Date().toISOString() })])

    render(<App />)

    await waitFor(() => expect(listRuns).toHaveBeenCalled())
    expect(startRun).not.toHaveBeenCalled()
  })

  it('does not auto-start when the last run is stale but still running', async () => {
    listRuns.mockResolvedValue([
      run({ status: 'researching', in_flight: true, created_at: new Date(Date.now() - 30 * DAY_MS).toISOString() }),
    ])

    render(<App />)

    await waitFor(() => expect(listRuns).toHaveBeenCalled())
    expect(startRun).not.toHaveBeenCalled()
  })

  it('does not auto-start when the last run is stale but still queued for synthesis', async () => {
    listRuns.mockResolvedValue([
      run({ status: 'synthesising', in_flight: true, created_at: new Date(Date.now() - 30 * DAY_MS).toISOString() }),
    ])

    render(<App />)

    await waitFor(() => expect(listRuns).toHaveBeenCalled())
    expect(startRun).not.toHaveBeenCalled()
  })

  it('a refresh moments after an auto-start does not start a second run', async () => {
    // First "tab": the stale run triggers exactly one auto-start.
    listRuns.mockResolvedValueOnce([run()])
    startRun.mockResolvedValue(
      run({ run_id: 'auto1', status: 'researching', in_flight: true, created_at: new Date().toISOString() }),
    )
    // Every listRuns call after the first — including the one this component's
    // own success handler makes, and the one a fresh mount ("refresh" / second
    // tab) makes — sees the auto-started run as server truth: in flight.
    listRuns.mockResolvedValue([
      run({ run_id: 'auto1', status: 'researching', in_flight: true, created_at: new Date().toISOString() }),
    ])

    const first = render(<App />)
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(1))

    // A second mount — a refresh, a second tab, or coming back via browser
    // history — reads the same (now updated) server state fresh.
    render(<App />)
    await waitFor(() => expect(listRuns.mock.calls.length).toBeGreaterThanOrEqual(3))

    expect(startRun).toHaveBeenCalledTimes(1)
    first.unmount()
  })
})
