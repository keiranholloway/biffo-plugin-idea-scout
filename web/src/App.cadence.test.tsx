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
 *
 * ## Why every assertion in this file goes through `eventually()`, not `waitFor`
 *
 * #136 → #137 → #138 → #139 → #140 is the SAME flake class turning up one
 * instance at a time: CI CPU contention delays this process getting
 * scheduled, so a real-wall-clock `waitFor` budget elapses before the app
 * ever got the CPU time to settle. Each prior fix widened whichever
 * `waitFor` had just been observed failing, to 3000ms — and #140's own
 * repro proved that insufficient at the CLASS level: under the exact
 * contention recipe from #138, `refuses to save an interval outside the
 * served bounds, and says why` failed on its ALREADY-WIDENED 3000ms
 * `waitFor`.
 *
 * #140 asked this file to try fake timers first, on the theory that a
 * simulated clock removes the real-wall-clock dependency entirely. Tried
 * and rejected here: under `vi.useFakeTimers()`, this component's own
 * render pipeline needed simulated advancement within a few hundred
 * milliseconds of whatever total budget was granted before it reliably
 * settled — i.e. the "budget" stopped bounding CI contention and started
 * bounding an opaque number of internal scheduler hops instead, which is
 * exactly the "fights the component's own async data-fetching" case #140's
 * own text names as the fallback trigger. A fixed numeric budget picked to
 * survive that is no more principled than a fixed real-ms one — it is the
 * same class of guess, just against simulated ticks instead of real ones.
 *
 * So this is the sanctioned fallback instead: an EXHAUSTIVE sweep, in one
 * pass, of every `waitFor`/assertion pair in the file against both named
 * shapes of the class —
 *
 *   1. a `waitFor` on a mock call left at a tight budget, and
 *   2. a synchronous assertion sitting unwrapped immediately after an
 *      unrelated `waitFor`, assuming its condition implies this one's.
 *
 * `eventually()` is the only spelling either shape may use from here on:
 * every assertion that depends on an async render settling is retried
 * against its OWN condition, on one shared, generous, single-sourced
 * budget — not an unwrapped assumption riding an unrelated wait, and not a
 * hand-tuned number re-picked per call site. Vitest's own per-test timeout
 * is raised alongside it (`TEST_TIMEOUT_MS`) so it cannot mask a slow-but-
 * genuine pass the way the file's own comments previously warned the
 * default 5000ms would.
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

// Single shared budget for every assertion in this file (see the file-level
// comment for why). Well above what #140 proved insufficient (3000ms,
// already widened once, still failed under the exact contention recipe
// below) — chosen empirically against that same recipe, not picked in the
// abstract; see the PR body for the repro run this survived.
const WAIT_TIMEOUT_MS = 12_000

// Vitest's own per-test deadline is 5000ms by default, which is BELOW
// `WAIT_TIMEOUT_MS` and would otherwise fire first and mask a slow-but-
// genuine pass with a less informative error. A test with several
// sequential `eventually()` calls can legitimately need several budgets
// worth of headroom under adversarial contention.
const TEST_TIMEOUT_MS = 45_000

/** The only way an assertion in this file may depend on an async render
 * settling — see the file-level comment for why. */
async function eventually(assertion: () => void) {
  await waitFor(assertion, { timeout: WAIT_TIMEOUT_MS })
}

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

  it(
    'shows the founder that cadence is on, and at what interval',
    async () => {
      render(<App />)

      await eventually(() => expect(toggle()).toBeChecked())
      await eventually(() => expect(interval()).toHaveValue(7))
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'shows when the next automatic scout falls due',
    async () => {
      render(<App />)

      await eventually(() =>
        expect(document.body.textContent).toMatch(/next scout due in 3 days/i),
      )
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'says so plainly when cadence is off, rather than showing nothing',
    async () => {
      // An absent control and a switched-off one must not look the same —
      // that is the #23/#53 mistake, where the surface made a claim it could
      // not support. A founder who turned this off should see that they did.
      serve({ enabled: false, next_due_at: null, is_due: false })

      render(<App />)

      await eventually(() => expect(toggle()).not.toBeChecked())
      // Was an unwrapped synchronous assertion riding the waitFor above —
      // one of #140's two named shapes of the class. Its own condition now
      // retries independently rather than assuming the toggle's did.
      await eventually(() =>
        expect(document.body.textContent).toMatch(/only run when you press run now/i),
      )
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'takes the interval bounds from the server rather than restating them',
    async () => {
      // If these were hardcoded in the component they could offer a value the
      // save then 422s on. Served bounds are the same fix this plugin already
      // made for the complexity labels and the preference wording.
      serve({ min_cadence_days: 2, max_cadence_days: 45 })

      render(<App />)

      await eventually(() => expect(interval()).toHaveAttribute('min', '2'))
      await eventually(() => expect(interval()).toHaveAttribute('max', '45'))
    },
    TEST_TIMEOUT_MS,
  )

  // ── CHANGE ─────────────────────────────────────────────────────────────

  it(
    'sends a changed interval to the API',
    async () => {
      setCadence.mockResolvedValue(cadenceFixture({ cadence_days: 14 }))
      render(<App />)
      await eventually(() => expect(interval()).toHaveValue(7))

      fireEvent.change(interval(), { target: { value: '14' } })
      fireEvent.click(save())

      await eventually(() => expect(setCadence).toHaveBeenCalledWith(true, 14))
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'shows the recomputed due date the save came back with',
    async () => {
      // Not re-derived locally: the response carries the new `next_due_at`,
      // and rendering a locally-computed one is how the two copies would
      // drift.
      setCadence.mockResolvedValue(
        cadenceFixture({ cadence_days: 30, next_due_at: new Date(Date.now() + 20 * DAY_MS).toISOString() }),
      )
      render(<App />)
      await eventually(() => expect(interval()).toHaveValue(7))

      fireEvent.change(interval(), { target: { value: '30' } })
      fireEvent.click(save())

      await eventually(() =>
        expect(document.body.textContent).toMatch(/next scout due in 20 days/i),
      )
      // Was an unwrapped synchronous assertion riding the waitFor above.
      await eventually(() => expect(interval()).toHaveValue(30))
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'refuses to save an interval outside the served bounds, and says why',
    async () => {
      render(<App />)
      await eventually(() => expect(interval()).toHaveValue(7))

      fireEvent.change(interval(), { target: { value: '500' } })

      await eventually(() => expect(save()).toBeDisabled())
      await eventually(() =>
        expect(document.body.textContent).toMatch(/choose between 1 and 90 days/i),
      )
      // Was an unwrapped synchronous assertion riding the waitFor above —
      // this is the exact test #140's own repro caught failing on its
      // ALREADY-widened 3000ms waitFor.
      await eventually(() => expect(setCadence).not.toHaveBeenCalled())
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'does not write when nothing has changed',
    async () => {
      render(<App />)

      await eventually(() => expect(interval()).toHaveValue(7))
      // Was an unwrapped synchronous assertion riding the waitFor above.
      await eventually(() => expect(save()).toBeDisabled())
    },
    TEST_TIMEOUT_MS,
  )

  // ── OFF ────────────────────────────────────────────────────────────────

  it(
    'writes an explicit off when the founder unchecks it',
    async () => {
      // `enabled: false` reaches the API, keeping the interval alongside it —
      // the value is remembered so switching back on does not reset them.
      setCadence.mockResolvedValue(cadenceFixture({ enabled: false, next_due_at: null }))
      render(<App />)
      await eventually(() => expect(toggle()).toBeChecked())

      fireEvent.click(toggle())
      fireEvent.click(save())

      await eventually(() => expect(setCadence).toHaveBeenCalledWith(false, 7))
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'OFF suppresses the auto-start, it does not merely hide the control',
    async () => {
      // The assertion this whole feature turns on. The run below is over a
      // year old — under any live cadence it would be replaced on sight. It
      // is not, because the server reports `is_due: false` for a founder who
      // switched cadence off, and the surface acts on that rather than on
      // the age.
      serve({ enabled: false, next_due_at: null, is_due: false })
      listRuns.mockResolvedValue([run({ created_at: new Date(Date.now() - 400 * DAY_MS).toISOString() })])

      render(<App />)

      await eventually(() => expect(toggle()).not.toBeChecked())
      // Was an unwrapped synchronous assertion riding the waitFor above —
      // named as a flagged-but-unconfirmed instance in #140's body;
      // confirmed here as the same shape as the others in this file.
      await eventually(() => expect(startRun).not.toHaveBeenCalled())
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'and the same run IS auto-started once cadence is on and due',
    async () => {
      // The mirror of the case above, on identical run data. Without it, a
      // component that never auto-started anything at all would pass the OFF
      // test — the assertion would be vacuous.
      serve({ enabled: true, is_due: true })
      listRuns.mockResolvedValue([run({ created_at: new Date(Date.now() - 400 * DAY_MS).toISOString() })])
      startRun.mockResolvedValue(run({ run_id: 'auto1', in_flight: true }))

      render(<App />)

      await eventually(() => expect(startRun).toHaveBeenCalledTimes(1))
    },
    TEST_TIMEOUT_MS,
  )

  // ── Failure ────────────────────────────────────────────────────────────

  it(
    'surfaces a failed save instead of silently keeping the old value',
    async () => {
      setCadence.mockRejectedValue(new Error('Core said no'))
      render(<App />)
      await eventually(() => expect(interval()).toHaveValue(7))

      fireEvent.change(interval(), { target: { value: '14' } })
      fireEvent.click(save())

      await eventually(() => expect(document.body.textContent).toMatch(/core said no/i))
    },
    TEST_TIMEOUT_MS,
  )
})
