/**
 * The founder-facing half of the cadence preference (#50).
 *
 * The estate's most-measured defect is a field and a route tested end to end
 * with **zero callers in the interface** — persisted, covered, and unreachable
 * from the surface anyone actually uses. So these tests are deliberately
 * written against the rendered app rather than the component in isolation:
 * every assertion below starts from what a founder can see or click.
 *
 * Each of the three things the issue asked for gets one:
 *
 * - SEE that cadence is on, and when the next scout falls due.
 * - CHANGE the interval, and have the new value reach the API.
 * - Turn it OFF — and, critically, have OFF *suppress the auto-start* rather
 *   than merely hide the control. That last one is asserted through
 *   `startRun` not being called against a run old enough that any live cadence
 *   would have replaced it.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listRuns = vi.fn()
const startRun = vi.fn()
const getCadence = vi.fn()
const setCadence = vi.fn()

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
      // The cadence arrives INSIDE the bootstrap, exactly as the real client
      // receives it (#50) — kept in step with `getCadence` below via the one
      // `served` value, so a test cannot accidentally assert against a cadence
      // the page was never given.
      getFormOptions: () =>
        Promise.resolve({
          build_types: [{ key: 'micro-saas', label: 'MicroSaaS', description: null }],
          business_models: [],
          models: [],
          preferences: [],
          complexity_levels: [{ value: 3, label: 'moderate' }],
          cadence: served,
        }),
      getLastUsedModel: () => Promise.resolve(null),
      listRuns,
      getRun: vi.fn(),
      startRun,
      deleteRun: vi.fn(),
      getCandidates: vi.fn(),
      getCadence,
      setCadence,
    }),
  }
})

const { default: App } = await import('./App')

/** What the server currently reports for this founder's cadence. Set by
 * `serve()` before each render; read by both the bootstrap and `getCadence`. */
let served: ReturnType<typeof cadenceFixture>

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
    created_at: new Date(Date.now() - 400 * DAY_MS).toISOString(),
    in_flight: false,
    failure_reason: null,
    ...overrides,
  }
}

function cadenceFixture(overrides: Record<string, unknown> = {}) {
  return {
    enabled: true,
    cadence_days: 7,
    min_cadence_days: 1,
    max_cadence_days: 90,
    next_due_at: new Date(Date.now() + 3 * DAY_MS).toISOString(),
    is_due: false,
    ...overrides,
  }
}

const toggle = () => screen.getByLabelText(/scout for me automatically/i)
const interval = () => screen.getByLabelText(/days between automatic scouts/i)
const save = () => screen.getByRole('button', { name: /save cadence/i })

/** Make `overrides` what the server reports — through the mount bootstrap AND
 * through `getCadence`, which is what the page re-reads after a run starts.
 * Setting only one of the two is how a test would assert against a cadence the
 * page was never actually given. */
function serve(overrides: Record<string, unknown> = {}) {
  served = cadenceFixture(overrides)
  getCadence.mockResolvedValue(served)
  return served
}

describe('the cadence control (#50)', () => {
  beforeEach(() => {
    listRuns.mockReset()
    startRun.mockReset()
    getCadence.mockReset()
    setCadence.mockReset()
    listRuns.mockResolvedValue([run()])
    serve()
  })

  // ── SEE ────────────────────────────────────────────────────────────────

  it('shows the founder that cadence is on, and at what interval', async () => {
    render(<App />)

    await waitFor(() => expect(toggle()).toBeChecked())
    expect(interval()).toHaveValue(7)
  })

  it('shows when the next automatic scout falls due', async () => {
    render(<App />)

    await waitFor(() => expect(document.body.textContent).toMatch(/next scout due in 3 days/i))
  })

  it('says so plainly when cadence is off, rather than showing nothing', async () => {
    // An absent control and a switched-off one must not look the same — that
    // is the #23/#53 mistake, where the surface made a claim it could not
    // support. A founder who turned this off should see that they did.
    serve({ enabled: false, next_due_at: null, is_due: false })

    render(<App />)

    await waitFor(() => expect(toggle()).not.toBeChecked())
    expect(document.body.textContent).toMatch(/only run when you press run now/i)
  })

  it('takes the interval bounds from the server rather than restating them', async () => {
    // If these were hardcoded in the component they could offer a value the
    // save then 422s on. Served bounds are the same fix this plugin already
    // made for the complexity labels and the preference wording.
    serve({ min_cadence_days: 2, max_cadence_days: 45 })

    render(<App />)

    await waitFor(() => expect(interval()).toHaveAttribute('min', '2'))
    expect(interval()).toHaveAttribute('max', '45')
  })

  // ── CHANGE ─────────────────────────────────────────────────────────────

  it('sends a changed interval to the API', async () => {
    setCadence.mockResolvedValue(cadenceFixture({ cadence_days: 14 }))
    render(<App />)
    await waitFor(() => expect(interval()).toHaveValue(7))

    fireEvent.change(interval(), { target: { value: '14' } })
    fireEvent.click(save())

    await waitFor(() => expect(setCadence).toHaveBeenCalledWith(true, 14))
  })

  it('shows the recomputed due date the save came back with', async () => {
    // Not re-derived locally: the response carries the new `next_due_at`, and
    // rendering a locally-computed one is how the two copies would drift.
    setCadence.mockResolvedValue(
      cadenceFixture({ cadence_days: 30, next_due_at: new Date(Date.now() + 20 * DAY_MS).toISOString() }),
    )
    render(<App />)
    await waitFor(() => expect(interval()).toHaveValue(7))

    fireEvent.change(interval(), { target: { value: '30' } })
    fireEvent.click(save())

    await waitFor(() => expect(document.body.textContent).toMatch(/next scout due in 20 days/i))
    expect(interval()).toHaveValue(30)
  })

  it('refuses to save an interval outside the served bounds, and says why', async () => {
    render(<App />)
    await waitFor(() => expect(interval()).toHaveValue(7))

    fireEvent.change(interval(), { target: { value: '500' } })

    await waitFor(() => expect(save()).toBeDisabled())
    expect(document.body.textContent).toMatch(/choose between 1 and 90 days/i)
    expect(setCadence).not.toHaveBeenCalled()
  })

  it('does not write when nothing has changed', async () => {
    render(<App />)

    await waitFor(() => expect(interval()).toHaveValue(7))
    expect(save()).toBeDisabled()
  })

  // ── OFF ────────────────────────────────────────────────────────────────

  it('writes an explicit off when the founder unchecks it', async () => {
    // `enabled: false` reaches the API, keeping the interval alongside it —
    // the value is remembered so switching back on does not reset them.
    setCadence.mockResolvedValue(cadenceFixture({ enabled: false, next_due_at: null }))
    render(<App />)
    await waitFor(() => expect(toggle()).toBeChecked())

    fireEvent.click(toggle())
    fireEvent.click(save())

    await waitFor(() => expect(setCadence).toHaveBeenCalledWith(false, 7))
  })

  it('OFF suppresses the auto-start, it does not merely hide the control', async () => {
    // The assertion this whole feature turns on. The run below is over a year
    // old — under any live cadence it would be replaced on sight. It is not,
    // because the server reports `is_due: false` for a founder who switched
    // cadence off, and the surface acts on that rather than on the age.
    serve({ enabled: false, next_due_at: null, is_due: false })
    listRuns.mockResolvedValue([run({ created_at: new Date(Date.now() - 400 * DAY_MS).toISOString() })])

    render(<App />)

    await waitFor(() => expect(toggle()).not.toBeChecked())
    expect(startRun).not.toHaveBeenCalled()
  })

  it('and the same run IS auto-started once cadence is on and due', async () => {
    // The mirror of the case above, on identical run data. Without it, a
    // component that never auto-started anything at all would pass the OFF
    // test — the assertion would be vacuous.
    serve({ enabled: true, is_due: true })
    listRuns.mockResolvedValue([run({ created_at: new Date(Date.now() - 400 * DAY_MS).toISOString() })])
    startRun.mockResolvedValue(run({ run_id: 'auto1', in_flight: true }))

    render(<App />)

    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(1))
  })

  // ── Failure ────────────────────────────────────────────────────────────

  it('surfaces a failed save instead of silently keeping the old value', async () => {
    setCadence.mockRejectedValue(new Error('Core said no'))
    render(<App />)
    await waitFor(() => expect(interval()).toHaveValue(7))

    fireEvent.change(interval(), { target: { value: '14' } })
    fireEvent.click(save())

    await waitFor(() => expect(document.body.textContent).toMatch(/core said no/i))
  })
})
