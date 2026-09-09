import { useCallback, useEffect, useRef, useState } from "react";

import { CadenceControl } from "./components/CadenceControl";
import { CandidateCard } from "./components/CandidateCard";
import { RunForm } from "./components/RunForm";
import { ageInDays } from "./lib/cadence";
import {
  ApiError,
  createApi,
  type BuildType,
  type BusinessModel,
  type Cadence,
  type Candidate,
  type ComplexityLevel,
  type ModelOption,
  type Preference,
  type RunState,
} from "./lib/api";
import { getCurrentSession, getFreshIdToken } from "./lib/auth";
import { startedAt } from "./lib/started-at";

/** What triggered a `startRun` call, so the founder can be told why a scout
 * appeared rather than it simply showing up (#50). `undefined` is a normal,
 * founder-initiated "Run now". */
interface AutoStartTrigger {
  /** Whole days since the run being replaced, for the explanation's copy. */
  ageDays: number | null;
}

/** How often to re-read an in-flight run.
 *
 * Reading is what advances the run (see lib/api.ts), so this is not a cosmetic
 * refresh — it is the clock the pipeline's *projection* runs on. Kept slow
 * because the work behind it takes minutes and each poll is a Core round trip.
 */
const POLL_MS = 5_000;

export default function App() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  const [buildTypes, setBuildTypes] = useState<BuildType[]>([]);
  const [businessModels, setBusinessModels] = useState<BusinessModel[]>([]);
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [complexityLevels, setComplexityLevels] = useState<ComplexityLevel[]>(
    [],
  );
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunState[]>([]);
  // The founder's own cadence preference plus the server's derived `is_due`.
  // `null` until the first load answers — the control is not rendered before
  // then, because "off" and "not loaded yet" must not look the same.
  const [cadence, setCadence] = useState<Cadence | null>(null);
  const [savingCadence, setSavingCadence] = useState(false);
  const [current, setCurrent] = useState<RunState | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [starting, setStarting] = useState(false);
  // Whether the first load actually returned. Without this an *unloaded* app and
  // one that loaded an empty list are indistinguishable, and the empty-list copy
  // blames an admin (#23).
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set only when the run currently shown was started automatically because
  // the founder's previous one was stale (#50) — keyed by run id so it stops
  // applying the moment `current` becomes a different run. Never persisted:
  // it explains what just happened in *this* visit, not history.
  const [autoStarted, setAutoStarted] = useState<{
    runId: string;
    ageDays: number | null;
  } | null>(null);
  // Guards against firing the auto-start twice from one mount (e.g. React's
  // dev-mode double-invoke of effects). It does NOT and cannot guard against
  // a second browser tab — that guard is `!mostRecent.in_flight` below, which
  // reads the server's own state fresh on every mount instead of relying on
  // anything shared between tabs.
  const autoStartAttempted = useRef(false);

  // Created once (lazy initializer — `createApi` runs exactly once, not on
  // every render): `getFreshIdToken` is a stable module-level function that
  // re-resolves the session on every call, so the client itself never goes
  // stale, and nothing here snapshots a token (biffo-plugin-ideation#69).
  const [api] = useState(() => createApi(getFreshIdToken));

  // Only decides whether to show the sign-in prompt and gate the initial
  // load below. Requests themselves never read this — `api` re-resolves the
  // token per call via `getFreshIdToken`, so this snapshot going stale
  // doesn't matter, including across the life of a polled in-flight run.
  useEffect(() => {
    let cancelled = false;
    void getCurrentSession().then((session) => {
      if (cancelled) return;
      setSignedIn(session != null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (signedIn !== true) return;
    // THREE requests, and the count is load-bearing rather than incidental:
    // every `/api/v1/plugins/idea-scout/*` request is served by the shared
    // plugin host, which then calls Core, so each costs TWO Lambda
    // invocations. Five separate calls once asked for ~10 against an account
    // ceiling of 10 and throttled the page into a 503 (#79), and
    // `App.request-fanout.test.tsx` guards the number.
    //
    // The cadence is therefore bootstrapped inside `/form-options` rather than
    // fetched as a fourth call. Anything else this page comes to need on mount
    // belongs there too.
    void Promise.all([api.getFormOptions(), api.getLastUsedModel(), api.listRuns()])
      .then(([options, lastUsed, existing]) => {
        const currentCadence = options.cadence;
        setBuildTypes(options.build_types);
        setBusinessModels(options.business_models);
        setComplexityLevels(options.complexity_levels);
        setPreferences(options.preferences);
        setModels(options.models);
        setSelectedModel(lastUsed);
        setRuns(existing);
        setCadence(currentCadence);
        setLoaded(true);

        // Pull-based cadence (#50). The staleness DECISION is
        // `currentCadence.is_due`, computed server-side from this founder's
        // own stored interval and their most recent run. It is deliberately
        // not recomputed here: the interval is per-founder now, so a local
        // comparison would be measuring against a number they may never have
        // chosen — and an explicit OFF makes `is_due` false at the source,
        // which is what stops the run rather than merely hiding the control.
        //
        // `existing` is most-recent-first (see service.list_runs), so
        // existing[0] is the run whose settings get replayed.
        //
        // `!mostRecent.in_flight` stays as a client-side idempotency guard
        // even though the server applies the same rule to `is_due`. It is not
        // a second copy of the staleness rule — it is this client checking the
        // list it actually holds, read fresh from the server on every mount:
        // once any trigger has started a run, that run IS the most recent one
        // and it is in flight, so a refresh, a second tab, or a
        // back-navigation moments later reads that fact and does not fire
        // again. `autoStartAttempted` only covers a second effect firing
        // within *this* mount.
        const mostRecent = existing[0];
        if (
          currentCadence.is_due &&
          mostRecent != null &&
          !mostRecent.in_flight &&
          !autoStartAttempted.current
        ) {
          autoStartAttempted.current = true;
          void startRun(
            mostRecent.build_type,
            mostRecent.complexity,
            mostRecent.preferences,
            mostRecent.research_model ?? undefined,
            mostRecent.business_model ?? undefined,
            { ageDays: ageInDays(mostRecent.created_at) },
          );
        }
      })
      .catch((err: unknown) => {
        // A 401 here means the portal session has expired, not that this
        // founder lacks access. Treating it as signed-out shows the sign-in
        // prompt instead of RunForm's "an admin needs to add a category" —
        // which is what a stale token used to render as, sending people to
        // look for configuration that was never missing (#23).
        if (err instanceof ApiError && err.status === 401) {
          setSignedIn(false);
          return;
        }
        setError(describe(err));
      });
  }, [signedIn]);

  const openRun = useCallback(async (runId: string) => {
    setError(null);
    setCandidates([]);
    try {
      const response = await api.getCandidates(runId);
      setCurrent(response);
      setCandidates(response.candidates);
    } catch (err: unknown) {
      setError(describe(err));
    }
  }, []);

  // Poll only while the open run is in flight. Reading is what moves it along,
  // so stopping the poll on a terminal status is both correct and the thing
  // that keeps a finished run from being re-read forever.
  useEffect(() => {
    if (current == null || !current.in_flight) return;
    const runId = current.run_id;
    const timer = setInterval(() => {
      void api
        .getCandidates(runId)
        .then((response) => {
          setCurrent(response);
          setCandidates(response.candidates);
          if (!response.in_flight) {
            void api
              .listRuns()
              .then(setRuns)
              .catch(() => undefined);
          }
        })
        .catch((err: unknown) => setError(describe(err)));
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [current]);

  async function startRun(
    buildType: string,
    complexity: number,
    prefs: string[] = [],
    research_model?: string,
    business_model?: string,
    autoTrigger?: AutoStartTrigger,
  ) {
    setStarting(true);
    setError(null);
    try {
      const run = await api.startRun(
        buildType,
        complexity,
        prefs,
        research_model,
        business_model,
      );
      setCurrent(run);
      setCandidates([]);
      setRuns(await api.listRuns());
      // Starting a run moves the founder's most recent `created_at`, and the
      // due date is derived from it — so the control would otherwise keep
      // saying "due now" immediately after a scout it just started. Re-read
      // rather than recompute: the server owns that derivation, and this is
      // the one place a local guess would be cheap and wrong.
      setCadence(await api.getCadence());
      setAutoStarted(
        autoTrigger != null ? { runId: run.run_id, ageDays: autoTrigger.ageDays } : null,
      );
    } catch (err: unknown) {
      setError(describe(err));
      if (autoTrigger != null) setAutoStarted(null);
    } finally {
      setStarting(false);
    }
  }

  async function saveCadence(enabled: boolean, cadenceDays: number) {
    setSavingCadence(true);
    setError(null);
    try {
      // The response is the recomputed cadence, so `next_due_at` and `is_due`
      // reflect what was just saved without a second request — and without
      // this client deriving either for itself.
      setCadence(await api.setCadence(enabled, cadenceDays));
    } catch (err: unknown) {
      setError(describe(err));
    } finally {
      setSavingCadence(false);
    }
  }

  async function deleteRun(runId: string) {
    try {
      await api.deleteRun(runId);
      setRuns(await api.listRuns());
      if (current?.run_id === runId) {
        setCurrent(null);
        setCandidates([]);
      }
    } catch (err: unknown) {
      setError(describe(err));
    }
  }

  if (signedIn === false) {
    return (
      <main className="signed-out">
        <h1>Idea Scout</h1>
        <p>Sign in through the Biffo portal to use Idea Scout.</p>
      </main>
    );
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>Past scouts</h2>
        {/* `loaded` gates this the same way it gates the main pane: until the
            list has answered, "No scouts yet." is a claim the app cannot make.
            It told a founder with eleven scouts they had none (#53). */}
        {runs.length === 0 && !loaded && (
          <p className="muted">Loading your scouts…</p>
        )}
        {runs.length === 0 && loaded && (
          <p className="muted">No scouts yet.</p>
        )}
        <ul>
          {runs.map((run) => {
            const started = startedAt(run.created_at);
            return (
              <li
                key={run.run_id}
                className={
                  run.run_id === current?.run_id ? "active" : undefined
                }
              >
                <button type="button" onClick={() => void openRun(run.run_id)}>
                  <span className="run-type">
                    {typeLabel(buildTypes, run.build_type)}
                  </span>
                  <span className="run-meta">
                    <span className="run-status" data-status={statusLabel(run)}>
                      {statusLabel(run)}
                    </span>
                    {started != null && (
                      <time
                        className="run-started"
                        dateTime={started.iso}
                        title={started.title}
                      >
                        {started.label}
                      </time>
                    )}
                  </span>
                </button>
                <button
                  type="button"
                  className="run-delete"
                  aria-label={`Delete scout ${run.run_id}`}
                  onClick={() => void deleteRun(run.run_id)}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>

        {/* Rendered only once the first load has answered: before that, an
            "off" control and an unloaded one are indistinguishable, which is
            the same mistake the sidebar's empty-list copy made (#53). */}
        {cadence != null && (
          <CadenceControl
            cadence={cadence}
            busy={savingCadence}
            onSave={(enabled, days) => void saveCadence(enabled, days)}
          />
        )}
      </aside>

      <main className="main">
        <h1>Idea Scout</h1>
        {error != null && <p className="error">{error}</p>}

        {current == null && !loaded && <p className="muted">Loading…</p>}

        {current == null && loaded ? (
          <RunForm
            buildTypes={buildTypes}
            businessModels={businessModels}
            complexityLevels={complexityLevels}
            preferences={preferences}
            models={models}
            selectedModel={selectedModel}
            busy={starting}
            onStart={(type, complexity, prefs, model, bizModel) =>
              void startRun(type, complexity, prefs, model, bizModel)
            }
          />
        ) : current == null ? null : (
          <>
            <div className="run-header">
              <span className="run-type">
                {typeLabel(buildTypes, current.build_type)}
              </span>
              <span className="run-complexity">{current.complexity_label}</span>
              {current.research_model != null && (
                <span className="run-model">
                  {modelLabel(models, current.research_model)}
                </span>
              )}
              <button type="button" onClick={() => setCurrent(null)}>
                New scout
              </button>
            </div>

            {autoStarted?.runId === current.run_id && (
              <p className="auto-started" role="status">
                Started automatically —{" "}
                {autoStarted.ageDays != null
                  ? `your last scout was ${autoStarted.ageDays} day${autoStarted.ageDays === 1 ? "" : "s"} old.`
                  : "it had been a while since your last scout."}
              </p>
            )}

            {current.in_flight && (
              <p className="in-flight" role="status">
                {current.status === "researching"
                  ? "Researching — three agents are searching for signals."
                  : "Reconciling the findings into ranked ideas."}{" "}
                You can close this tab; it will finish without you. This usually
                takes two to four minutes, and if something goes wrong it stops
                and tells you rather than hanging.
              </p>
            )}

            {current.status === "failed" && (
              <p className="error" role="status">
                {current.failure_reason ?? "This scout failed."}
              </p>
            )}

            {candidates.map((candidate) => (
              <CandidateCard key={candidate.id} candidate={candidate} />
            ))}
          </>
        )}
      </main>
    </div>
  );
}

/** The build type's human label, falling back to its key.
 *
 * Runs store the `key` (`micro-saas`); only the build-types list knows it is
 * called "MicroSaaS". The fallback matters: a run started against a category an
 * admin has since removed still has to render as something.
 */
function typeLabel(buildTypes: BuildType[], key: string): string {
  return buildTypes.find((type) => type.key === key)?.label ?? key;
}

/** The model's human label, falling back to its id.
 *
 * Runs store the model `id`; only the models list knows its label. The fallback
 * matters: a run started against a model an admin has since removed still has to
 * render as something.
 */
function modelLabel(models: ModelOption[], id: string): string {
  return models.find((model) => model.id === id)?.label ?? id;
}

function statusLabel(run: RunState): string {
  if (run.status === "complete") return "ready";
  if (run.status === "failed") return "failed";
  return "running";
}

function describe(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}
