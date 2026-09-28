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
 * ## Why this file no longer waits on a real-wall-clock budget at all
 *
 * #136 → #137 → #138 → #139 → #140 → #142 → #143 is the SAME flake class
 * turning up one instance at a time: CI CPU contention delays this process
 * getting scheduled, so a real-wall-clock `waitFor` budget elapses before the
 * app ever got the CPU time to settle. Each prior fix widened whichever
 * `waitFor` had just been observed failing — first per call site to 3000ms
 * (#137/#139), then via a single shared `eventually()` helper raised to
 * 12000ms (#141) — and #143's own repro proved that insufficient too: under
 * sufficient contention (reproduced live, ~36 load average on 12 cores), the
 * SAME two tests still exceeded the widened 12000ms budget. A fixed
 * numeric budget, however generous, remains a guess a sufficiently contended
 * runner can still exceed — widening it again would just be the fourth
 * instance of the same mitigation.
 *
 * So this file asserts off a different signal entirely: the actual promises
 * the mocked API/auth calls return, awaited to a **fixed point** — call the
 * mocks, await everything currently pending inside `act()`, check whether
 * that produced any *new* calls, and repeat until a pass makes none. That is
 * `settle()` below. It has no timeout and no real-clock budget: under CPU
 * contention it simply takes longer *in real time* to run the same fixed
 * number of hops, because the awaits inside `act()` really do wait for the
 * component's actual continuation to run — there is nothing left to race.
 * The only bound is `MAX_SETTLE_HOPS`, a count of logical chain hops (how
 * many times the component's own code calls another mock in reaction to a
 * previous one resolving), which is a property of the code path, not of how
 * fast the CPU happens to be scheduled — unlike the fake-timer "opaque number
 * of scheduler hops" #140 tried and rejected, this count is not tuned by
 * hand: it is *detected*, by re-checking call counts every hop and stopping
 * the moment a hop adds nothing, so a slow-but-genuine settle of any depth
 * still passes and only a genuinely stuck app (an actual bug, not
 * contention) can exhaust it.
 *
 * `TEST_TIMEOUT_MS` remains as a coarse, per-test hang backstop — it no
 * longer does any of the actual synchronizing work, `settle()` does, so it is
 * a detector for a truly stuck test, not the mechanism racing CI contention.
 *
 * Every assertion that depends on an async render settling now runs as a
 * plain synchronous `expect(...)` immediately after `await settle()`, rather
 * than through a polling wrapper — once `settle()` returns, the state it
 * gathered promises for is already committed, so polling again would only
 * reintroduce the thing this rewrite removes.
 */

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listRuns = vi.fn()
const startRun = vi.fn()
const getCadence = vi.fn()
const setCadence = vi.fn()

/** What the server currently reports for this founder's cadence. Set by
 * `serve()` before each render; read by both the bootstrap and `getCadence`. */
let served: ReturnType<typeof cadenceFixture>

// Tracked (not bare arrow functions) so `settle()` below can see when the app
// calls them and await the exact promise it is itself chained from — the
// mechanism this file now uses instead of a real-wall-clock `waitFor` budget.
const getCurrentSession = vi.fn(() =>
  Promise.resolve({
    getIdToken: () => ({ getJwtToken: () => 'test-token' }),
  }),
)

vi.mock('./lib/auth', () => ({
  getCurrentSession: () => getCurrentSession(),
  getFreshIdToken: () => Promise.resolve('test-token'),
}))

const getFormOptions = vi.fn(() =>
  Promise.resolve({
    build_types: [{ key: 'micro-saas', label: 'MicroSaaS', description: null }],
    business_models: [],
    models: [],
    preferences: [],
    complexity_levels: [{ value: 3, label: 'moderate' }],
    // The cadence arrives INSIDE the bootstrap, exactly as the real client
    // receives it (#50) — kept in step with `getCadence` below via the one
    // `served` value, so a test cannot accidentally assert against a cadence
    // the page was never given.
    cadence: served,
  }),
)
const getLastUsedModel = vi.fn(() => Promise.resolve(null))

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    createApi: () => ({
      getFormOptions: () => getFormOptions(),
      getLastUsedModel: () => getLastUsedModel(),
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

const DAY_MS = 24 * 60 * 60 * 1000

// Vitest's own per-test deadline; raised because a test can legitimately need
// several `settle()` chains' worth of headroom under adversarial contention.
// This is a hang backstop, not the synchronization mechanism — see the
// file-level comment.
const TEST_TIMEOUT_MS = 45_000

// A count of logical chain hops (one mock's resolution causing the app to
// call another), not a time budget — see the file-level comment. The deepest
// chain in this file is the auto-start path (session → bootstrap →
// startRun → listRuns → getCadence), four hops; this leaves generous room
// without being unbounded.
const MAX_SETTLE_HOPS = 20

/** Every mock whose resolution the app under test reacts to by calling
 * another one of these, or by committing state this file asserts against. */
const TRACKED_MOCKS = [
  getCurrentSession,
  getFormOptions,
  getLastUsedModel,
  listRuns,
  startRun,
  getCadence,
  setCadence,
] as const

/** The only way an assertion in this file may depend on an async render
 * settling — see the file-level comment for why this replaced `waitFor`.
 *
 * Awaits every promise any tracked mock has returned so far, inside `act()`
 * so React commits and flushes the effects that follow, then checks whether
 * that produced any new calls to a tracked mock. Repeats until a pass adds
 * none — a real fixed point, detected rather than guessed, so it holds
 * however many hops the actual code path needs and however long each one
 * takes to actually run under contention. */
async function settle() {
  let callCounts = TRACKED_MOCKS.map((mock) => mock.mock.calls.length)
  for (let hop = 0; hop < MAX_SETTLE_HOPS; hop++) {
    await act(async () => {
      await Promise.all(
        TRACKED_MOCKS.flatMap((mock) =>
          mock.mock.results.map((result) =>
            Promise.resolve(result.value).catch(() => undefined),
          ),
        ),
      )
    })
    const newCounts = TRACKED_MOCKS.map((mock) => mock.mock.calls.length)
    if (newCounts.every((count, index) => count === callCounts[index])) return
    callCounts = newCounts
  }
  throw new Error(
    `settle() did not converge after ${MAX_SETTLE_HOPS} hops — the app is still issuing new calls to a tracked mock. Either a genuine loop, or a new call path that needs adding to TRACKED_MOCKS.`,
  )
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
    // These three carry a persistent implementation (read `served` live), so
    // only their call history is cleared — `mockReset()` would drop the
    // implementation along with it.
    getCurrentSession.mockClear()
    getFormOptions.mockClear()
    getLastUsedModel.mockClear()
    listRuns.mockResolvedValue([run()])
    serve()
  })

  // ── SEE ────────────────────────────────────────────────────────────────

  it(
    'shows the founder that cadence is on, and at what interval',
    async () => {
      render(<App />)
      await settle()

      expect(toggle()).toBeChecked()
      expect(interval()).toHaveValue(7)
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'shows when the next automatic scout falls due',
    async () => {
      render(<App />)
      await settle()

      expect(document.body.textContent).toMatch(/next scout due in 3 days/i)
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
      await settle()

      expect(toggle()).not.toBeChecked()
      expect(document.body.textContent).toMatch(/only run when you press run now/i)
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
      await settle()

      expect(interval()).toHaveAttribute('min', '2')
      expect(interval()).toHaveAttribute('max', '45')
    },
    TEST_TIMEOUT_MS,
  )

  // ── CHANGE ─────────────────────────────────────────────────────────────

  it(
    'sends a changed interval to the API',
    async () => {
      setCadence.mockResolvedValue(cadenceFixture({ cadence_days: 14 }))
      render(<App />)
      await settle()
      expect(interval()).toHaveValue(7)

      fireEvent.change(interval(), { target: { value: '14' } })
      fireEvent.click(save())
      await settle()

      expect(setCadence).toHaveBeenCalledWith(true, 14)
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
      await settle()
      expect(interval()).toHaveValue(7)

      fireEvent.change(interval(), { target: { value: '30' } })
      fireEvent.click(save())
      await settle()

      expect(document.body.textContent).toMatch(/next scout due in 20 days/i)
      expect(interval()).toHaveValue(30)
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'refuses to save an interval outside the served bounds, and says why',
    async () => {
      render(<App />)
      await settle()
      expect(interval()).toHaveValue(7)

      fireEvent.change(interval(), { target: { value: '500' } })
      await settle()

      expect(save()).toBeDisabled()
      expect(document.body.textContent).toMatch(/choose between 1 and 90 days/i)
      expect(setCadence).not.toHaveBeenCalled()
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'does not write when nothing has changed',
    async () => {
      render(<App />)
      await settle()

      expect(interval()).toHaveValue(7)
      expect(save()).toBeDisabled()
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
      await settle()
      expect(toggle()).toBeChecked()

      fireEvent.click(toggle())
      fireEvent.click(save())
      await settle()

      expect(setCadence).toHaveBeenCalledWith(false, 7)
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
      await settle()

      expect(toggle()).not.toBeChecked()
      expect(startRun).not.toHaveBeenCalled()
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
      await settle()

      expect(startRun).toHaveBeenCalledTimes(1)
    },
    TEST_TIMEOUT_MS,
  )

  // ── Failure ────────────────────────────────────────────────────────────

  it(
    'surfaces a failed save instead of silently keeping the old value',
    async () => {
      setCadence.mockRejectedValue(new Error('Core said no'))
      render(<App />)
      await settle()
      expect(interval()).toHaveValue(7)

      fireEvent.change(interval(), { target: { value: '14' } })
      fireEvent.click(save())
      await settle()

      expect(document.body.textContent).toMatch(/core said no/i)
    },
    TEST_TIMEOUT_MS,
  )
})
