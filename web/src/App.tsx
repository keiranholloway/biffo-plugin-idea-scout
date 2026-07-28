import { useCallback, useEffect, useRef, useState } from "react";

import { CandidateCard } from "./components/CandidateCard";
import { RunForm } from "./components/RunForm";
import {
  ApiError,
  createApi,
  type BuildType,
  type Candidate,
  type ComplexityLevel,
  type Preference,
  type RunState,
} from "./lib/api";
import { getCurrentSession } from "./lib/auth";
import { startedAt } from "./lib/started-at";

/** How often to re-read an in-flight run.
 *
 * Reading is what advances the run (see lib/api.ts), so this is not a cosmetic
 * refresh — it is the clock the pipeline's *projection* runs on. Kept slow
 * because the work behind it takes minutes and each poll is a Core round trip.
 */
const POLL_MS = 5_000;

export default function App() {
  const [idToken, setIdToken] = useState<string | null>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  const [buildTypes, setBuildTypes] = useState<BuildType[]>([]);
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [complexityLevels, setComplexityLevels] = useState<ComplexityLevel[]>(
    [],
  );
  const [runs, setRuns] = useState<RunState[]>([]);
  const [current, setCurrent] = useState<RunState | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [starting, setStarting] = useState(false);
  // Whether the first load actually returned. Without this an *unloaded* app and
  // one that loaded an empty list are indistinguishable, and the empty-list copy
  // blames an admin (#23).
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const api = useRef(createApi(() => idToken));
  api.current = createApi(() => idToken);

  // The portal owns sign-in; this app only reads the session it established.
  useEffect(() => {
    let cancelled = false;
    void getCurrentSession().then((session) => {
      if (cancelled) return;
      const token = session?.getIdToken().getJwtToken() ?? null;
      setIdToken(token);
      setSignedIn(token != null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (idToken == null) return;
    void Promise.all([
      api.current.getBuildTypes(),
      api.current.getComplexityLevels(),
      api.current.getPreferences(),
      api.current.listRuns(),
    ])
      .then(([types, levels, prefs, existing]) => {
        setBuildTypes(types);
        setComplexityLevels(levels);
        setPreferences(prefs);
        setRuns(existing);
        setLoaded(true);
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
  }, [idToken]);

  const openRun = useCallback(async (runId: string) => {
    setError(null);
    setCandidates([]);
    try {
      const response = await api.current.getCandidates(runId);
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
      void api.current
        .getCandidates(runId)
        .then((response) => {
          setCurrent(response);
          setCandidates(response.candidates);
          if (!response.in_flight) {
            void api.current
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
  ) {
    setStarting(true);
    setError(null);
    try {
      const run = await api.current.startRun(buildType, complexity, prefs);
      setCurrent(run);
      setCandidates([]);
      setRuns(await api.current.listRuns());
    } catch (err: unknown) {
      setError(describe(err));
    } finally {
      setStarting(false);
    }
  }

  async function deleteRun(runId: string) {
    try {
      await api.current.deleteRun(runId);
      setRuns(await api.current.listRuns());
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
        {runs.length === 0 && <p className="muted">No scouts yet.</p>}
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
      </aside>

      <main className="main">
        <h1>Idea Scout</h1>
        {error != null && <p className="error">{error}</p>}

        {current == null && !loaded && <p className="muted">Loading…</p>}

        {current == null && loaded ? (
          <RunForm
            buildTypes={buildTypes}
            complexityLevels={complexityLevels}
            preferences={preferences}
            busy={starting}
            onStart={(type, complexity, prefs) =>
              void startRun(type, complexity, prefs)
            }
          />
        ) : current == null ? null : (
          <>
            <div className="run-header">
              <span className="run-type">
                {typeLabel(buildTypes, current.build_type)}
              </span>
              <span className="run-complexity">{current.complexity_label}</span>
              <button type="button" onClick={() => setCurrent(null)}>
                New scout
              </button>
            </div>

            {current.in_flight && (
              <p className="in-flight" role="status">
                {current.status === "researching"
                  ? "Researching — three agents are searching for signals."
                  : "Reconciling the findings into ranked ideas."}{" "}
                You can close this tab; it will finish without you.
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

function statusLabel(run: RunState): string {
  if (run.status === "complete") return "ready";
  if (run.status === "failed") return "failed";
  return "running";
}

function describe(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}
