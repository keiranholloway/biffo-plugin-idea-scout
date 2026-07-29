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

export function createApi(getIdToken: () => string | null) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = getIdToken()
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
    getBuildTypes: () => request<BuildType[]>('GET', '/build-types'),
    getComplexityLevels: () => request<ComplexityLevel[]>('GET', '/complexity-levels'),
    getPreferences: () => request<Preference[]>('GET', '/preferences'),
    getModels: () => request<ModelOption[]>('GET', '/models'),
    getLastUsedModel: () => request<string | null>('GET', '/models/last-used'),
    startRun: (build_type: string, complexity: number, preferences: string[] = [], research_model?: string) => {
      const body: Record<string, unknown> = { build_type, complexity, preferences }
      if (research_model != null) body.research_model = research_model
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
