// Calls this module's API only (never Core directly — ADR-0002), served by the
// shared plugin host at <base>/api/v1/plugins/idea-scout/* (ADR-0021).
//
// A note on polling, because it is not obvious from the endpoint names: reading a
// run is what *advances* it. GET /runs/{id} and GET /runs/{id}/candidates both
// move the state machine forward when the agent runs they are waiting on have
// finished. GET /runs (the sidebar) deliberately does not. So a client must poll
// one of the first two to see a run progress — and must not treat either as
// cacheable.

const API_BASE = '/api/v1/plugins/idea-scout'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export type RunStatus = 'researching' | 'synthesising' | 'complete' | 'failed'

export interface BuildType {
  key: string
  label: string
  description: string | null
}

/** How an idea makes money. Same shape as BuildType and deliberately carrying no
 * valuation field: the taxonomy came from a corpus of asking prices with no
 * confirmed sales, so a multiple here would read as a valuation it is not. */
export interface BusinessModel {
  key: string
  label: string
  description: string | null
}

/** Everything the run form needs, in one response.
 *
 * One request instead of five. Each `/api/v1/plugins/idea-scout/*` call is
 * served by the shared plugin host, which then calls Core — so every request
 * costs two Lambda invocations, and fetching these separately on mount
 * self-throttled against the account concurrency ceiling (#79).
 */
export interface FormOptions {
  build_types: BuildType[]
  business_models: BusinessModel[]
  models: ModelOption[]
  preferences: Preference[]
  complexity_levels: ComplexityLevel[]
}

export interface ComplexityLevel {
  value: number
  label: string
}

export interface Preference {
  key: string
  /** `prefer` lifts an idea that satisfies it; `avoid` weighs against one that violates it. */
  direction: 'prefer' | 'avoid'
  label: string
}

export interface ModelOption {
  id: string
  model_id: string
  label: string
  is_default: boolean
}

export interface RunState {
  run_id: string
  status: RunStatus
  build_type: string
  complexity: number
  complexity_label: string
  preferences: string[]
  research_model?: string
  // Echoed back by the server (app.py's `_run_state`) but not previously
  // typed here. Needed to replay a past run's settings when auto-starting a
  // fresh one for a returning founder (#50) — `null` means "no preference",
  // same convention as `startRun`'s own optional parameter.
  business_model?: string | null
  created_at: string | null
  in_flight: boolean
  failure_reason: string | null
}

export interface ScoreAxis {
  score: number
  rationale: string
}

export interface Competitor {
  name: string
  url?: string | null
  note: string
}

export interface Scorecard {
  viability: ScoreAxis
  complexity: ScoreAxis
  economic_moat: ScoreAxis
  market_fit: ScoreAxis
  build_vs_buy: string
  competitors: Competitor[]
  summary: string
}

export interface Source {
  url: string
  note: string
}

export interface Candidate {
  id: string
  rank: number
  title: string
  pitch: string
  scorecard: Scorecard | null
  sources: Source[]
}

export interface CandidatesResponse extends RunState {
  candidates: Candidate[]
}

export type Api = ReturnType<typeof createApi>

export function createApi(getIdToken: () => string | null | Promise<string | null>) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = await getIdToken()
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        // The founder id token rides Authorization: Bearer (ADR-0021), exactly as
        // the portal calls Core. The API Gateway's Cognito authorizer validates
        // it, the plugin host's group gate enforces the founder group, and the
        // app re-verifies it before forwarding to Core.
        ...(token != null ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText)
      throw new ApiError(res.status, detail)
    }
    if (res.status === 204) return undefined as T
    return res.json() as Promise<T>
  }

  return {
    // One call replacing getBuildTypes/getBusinessModels/getComplexityLevels/
    // getPreferences/getModels (#79). Those five endpoints still exist server-side
    // and are still individually correct; nothing in this app calls them.
    getFormOptions: () => request<FormOptions>('GET', '/form-options'),
    // The server returns an OBJECT — `{"research_model": "…"}` or
    // `{"research_model": null}` — so unwrap it. This was typed as a bare
    // `string | null` and `request<T>` casts blindly (`as T`), so TypeScript had
    // nothing to check it against and the mismatch reached the founder:
    // `selectedModel` became the object, an object is truthy, `modelId` became
    // the object, no `<option value>` matched it so the browser displayed the
    // FIRST model as if chosen, and submitting sent the object — which the API
    // rejected with 422 `string_type`, `"input":{"research_model":null}`.
    //
    // So a founder who loaded the page and pressed Run now without touching the
    // dropdown could not start a scout at all, and the form looked complete.
    getLastUsedModel: async (): Promise<string | null> => {
      const body = await request<{ research_model: string | null }>('GET', '/models/last-used')
      return body?.research_model ?? null
    },
    startRun: (
      build_type: string,
      complexity: number,
      preferences: string[] = [],
      research_model?: string,
      business_model?: string,
    ) => {
      const body: Record<string, unknown> = { build_type, complexity, preferences }
      if (research_model != null) body.research_model = research_model
      // Omitted rather than sent as null when the founder expressed no
      // preference: the server treats absent as "no preference" and an explicit
      // null would be a second way of saying the same thing.
      if (business_model) body.business_model = business_model
      return request<RunState>('POST', '/runs', body)
    },
    listRuns: () => request<RunState[]>('GET', '/runs'),
    getRun: (id: string) => request<RunState>('GET', `/runs/${id}`),
    getCandidates: (id: string) => request<CandidatesResponse>('GET', `/runs/${id}/candidates`),
    deleteRun: (id: string) => request<void>('POST', `/runs/${id}/delete`),
  }
}

/** Where a promoted candidate goes: the Ideation Engine, seeded with the pitch.
 *
 * Same-origin sibling app (ADR-0007), so a relative path keeps the shared Cognito
 * session with no second sign-in. The pitch is URL-encoded and bounded to the
 * 16,000 characters the Ideation Engine's own request model enforces — sending
 * more would 422 there rather than here, which is a worse place to find out.
 */
export const IDEATION_SEED_LIMIT = 16_000

export function pressureTestUrl(pitch: string): string {
  const seed = pitch.slice(0, IDEATION_SEED_LIMIT)
  return `/ideation/?seed=${encodeURIComponent(seed)}`
}
