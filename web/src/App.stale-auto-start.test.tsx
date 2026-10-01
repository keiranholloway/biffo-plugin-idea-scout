/**
 * Pull-based cadence (#50, option A): a founder returning to the surface with
 * a stale last run gets a fresh one started for them, instead of the empty
 * "Run now" form. This is the correctness-critical half of that feature: the
 * trigger must fire exactly once per genuinely-stale return, and must never
 * fire a second time behind it — a refresh, a second tab, or a
 * back-navigation moments later must see the just-started run as the reason
 * not to start another one, not as a fresh occasion to.
 *
 * **Where staleness is decided has moved.** It is now `cadence.is_due`,
 * computed server-side from this founder's own stored interval and their most
 * recent run (`service._derive_cadence_state`, covered in
 * `tests/test_idea_scout_cadence.py`). So `getCadence` is mocked here as what
 * the server *said*, and the run ages below are only there to make each
 * scenario readable — nothing in the component compares them any more.
 *
 * That separation lets the guard tests get sharper rather than weaker: the
 * in-flight cases now answer `is_due: true`, which the real server would never
 * say. That is deliberate. The client's own `!mostRecent.in_flight` check is
 * belt-and-braces behind the server's, and the only way to prove it still
 * works is to ask it to hold when the server's answer would not save it.
 *
 * Every scenario reads `listRuns` fresh, the same way two real tabs would —
 * there is no shared client-side lock between them.
 *
 * ## Why this file no longer waits on a real-wall-clock budget at all
 *
 * Same flake class as `App.cadence.test.tsx` (#136 → #143, see that file's
 * header for the full history): CI CPU contention delays this process getting
 * scheduled, so a real-wall-clock `waitFor` budget elapses before the app ever
 * got the CPU time to settle. This file exercises the identical async chain
 * (session → bootstrap → listRuns/getCadence → startRun) and was missed by
 * that earlier sweep. It now uses the same `settle()` fixed-point helper —
 * call the mocks, await everything currently pending inside `act()`, check
 * whether that produced any *new* calls, and repeat until a pass makes none.
 * It has no timeout and no real-clock budget: under CPU contention it simply
 * takes longer *in real time* to run the same fixed number of hops. See
 * `App.cadence.test.tsx` for the full rationale.
 */

import { act, render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listRuns = vi.fn()
const startRun = vi.fn()
const getCadence = vi.fn()

// Tracked (not a bare arrow function) so `settle()` below can see when the
// app calls it and await the exact promise it is itself chained from — the
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
      setCadence: vi.fn(),
    }),
  }
})

const { default: App } = await import('./App')

/** What the server currently reports for this founder's cadence. Set by
 * `serve()` before each render; read by both the bootstrap and `getCadence`. */
let served: ReturnType<typeof cadenceFixture>

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
const TRACKED_MOCKS = [getCurrentSession, getFormOptions, getLastUsedModel, listRuns, startRun, getCadence] as const

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
          mock.mock.results.map((result) => Promise.resolve(result.value).catch(() => undefined)),
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
    created_at: new Date(Date.now() - 10 * DAY_MS).toISOString(),
    in_flight: false,
    failure_reason: null,
    ...overrides,
  }
}

/** What `GET /cadence` answered. `is_due` is the server's decision, not ours. */
function cadenceFixture(overrides: Record<string, unknown> = {}) {
  return {
    enabled: true,
    cadence_days: 7,
    min_cadence_days: 1,
    max_cadence_days: 90,
    next_due_at: new Date(Date.now() - 3 * DAY_MS).toISOString(),
    is_due: true,
    ...overrides,
  }
}

/** Make `overrides` what the server reports — through the mount bootstrap AND
 * through `getCadence`, which is what the page re-reads after a run starts.
 * Setting only one of the two is how a test would assert against a cadence the
 * page was never actually given. */
function serve(overrides: Record<string, unknown> = {}) {
  served = cadenceFixture(overrides)
  getCadence.mockResolvedValue(served)
  return served
}

describe('auto-starting a stale scout on return (#50)', () => {
  beforeEach(() => {
    listRuns.mockReset()
    startRun.mockReset()
    getCadence.mockReset()
    // These carry a persistent implementation (read `served` live), so only
    // their call history is cleared — `mockReset()` would drop the
    // implementation along with it.
    getCurrentSession.mockClear()
    getFormOptions.mockClear()
    getLastUsedModel.mockClear()
    serve()
  })

  it(
    'starts a fresh scout when the server says one is due',
    async () => {
      listRuns.mockResolvedValue([run()])
      startRun.mockResolvedValue(
        run({ run_id: 'auto1', status: 'researching', in_flight: true, created_at: new Date().toISOString() }),
      )

      render(<App />)
      await settle()

      expect(startRun).toHaveBeenCalledTimes(1)
      expect(startRun).toHaveBeenCalledWith('micro-saas', 3, [], undefined, undefined)
      // The founder must be able to tell this happened *to* them, not just
      // that a run appeared — otherwise it is indistinguishable from a bug.
      expect(document.body.textContent).toMatch(/started automatically/i)
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'replays the last run settings rather than the form defaults',
    async () => {
      // The auto-start has no founder in front of it to pick a build type, so
      // it repeats what they last asked for. A regression here would
      // silently scout a different category than the one they chose.
      listRuns.mockResolvedValue([
        run({
          build_type: 'marketplace',
          complexity: 5,
          preferences: ['recurring-revenue'],
          research_model: 'Some Model Name',
          business_model: 'subscription',
        }),
      ])
      // The runs list holds the model NAME; the replay must send the catalog ID.
      getLastUsedModel.mockResolvedValueOnce('model-7')
      startRun.mockResolvedValue(run({ run_id: 'auto1', in_flight: true }))

      render(<App />)
      await settle()

      expect(startRun).toHaveBeenCalledTimes(1)
      expect(startRun).toHaveBeenCalledWith('marketplace', 5, ['recurring-revenue'], 'model-7', 'subscription')
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'does not auto-start when there is no run history at all',
    async () => {
      // A founder who has never scouted is new, not returning — the server
      // says so, and there would be nothing to replay the settings of anyway.
      listRuns.mockResolvedValue([])
      serve({ is_due: false, next_due_at: null })

      render(<App />)
      await settle()

      expect(listRuns).toHaveBeenCalled()
      expect(startRun).not.toHaveBeenCalled()
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'does not auto-start when the server says nothing is due yet',
    async () => {
      listRuns.mockResolvedValue([run({ created_at: new Date().toISOString() })])
      serve({ is_due: false, next_due_at: new Date(Date.now() + 7 * DAY_MS).toISOString() })

      render(<App />)
      await settle()

      expect(listRuns).toHaveBeenCalled()
      expect(startRun).not.toHaveBeenCalled()
    },
    TEST_TIMEOUT_MS,
  )

  it.each(['researching', 'synthesising'])(
    'does not auto-start while the last run is still %s, even if told it is due',
    async (status) => {
      // `is_due: true` is a deliberately impossible answer — the real server
      // never reports an in-flight run as due. Asking the client to hold
      // anyway is the only way to prove its own guard is still load-bearing
      // rather than being carried by the server's.
      listRuns.mockResolvedValue([
        run({ status, in_flight: true, created_at: new Date(Date.now() - 30 * DAY_MS).toISOString() }),
      ])

      render(<App />)
      await settle()

      expect(listRuns).toHaveBeenCalled()
      expect(startRun).not.toHaveBeenCalled()
    },
    TEST_TIMEOUT_MS,
  )

  it(
    'a refresh moments after an auto-start does not start a second run',
    async () => {
      // First "tab": the stale run triggers exactly one auto-start.
      listRuns.mockResolvedValueOnce([run()])
      startRun.mockResolvedValue(
        run({ run_id: 'auto1', status: 'researching', in_flight: true, created_at: new Date().toISOString() }),
      )
      // Every listRuns call after the first — including the one this
      // component's own success handler makes, and the one a fresh mount
      // ("refresh" / second tab) makes — sees the auto-started run as server
      // truth: in flight. The cadence mock keeps saying `is_due: true`
      // throughout, so the in-flight run is the only thing standing between
      // this and a duplicate.
      listRuns.mockResolvedValue([
        run({ run_id: 'auto1', status: 'researching', in_flight: true, created_at: new Date().toISOString() }),
      ])

      const first = render(<App />)
      await settle()
      expect(startRun).toHaveBeenCalledTimes(1)

      // A second mount — a refresh, a second tab, or coming back via browser
      // history — reads the same (now updated) server state fresh.
      render(<App />)
      await settle()
      expect(listRuns.mock.calls.length).toBeGreaterThanOrEqual(3)

      expect(startRun).toHaveBeenCalledTimes(1)
      first.unmount()
    },
    TEST_TIMEOUT_MS,
  )
})
