// Admin API client for Idea Scout's admin panel: build types, agents, and model catalog.
//
// Every base is under `/api/v1/plugins/idea-scout`, and that is not incidental:
//
// - BUILD_TYPES_BASE and MODEL_CATALOG_BASE: The CRUD routes for these tables
//   are declared in `biffo.plugin.json`'s `api_routes`, so Core generates them
//   and the plugin host forwards them (biffo-template#684), authorised by the
//   table's own permissions: list/read open to any authenticated caller, create/
//   update/delete admin-only.
//
// - AGENTS_BASE: this plugin's own admin app, which forwards to Core's admin
//   routes server-side as the calling admin (`admin_app._core_request`).
//
// AGENTS_BASE used to point straight at `/api/v1/admin/plugins/idea-scout`, on
// the reasoning that going through the admin app would make the host call itself
// and forward to Core — three hops, biffo-template#652. That cost is real for a
// SELF-call through the public path; the admin app calls Core directly, which is
// one hop, and it is what ideation does.
//
// The reason it had to change is #69: **`/api/v1/admin/*` is not routed to Core
// from the browser at all.** The CDN carries one API behaviour, `api/v1/plugins/*`;
// everything else falls through to the portal origin, which answered these calls
// with its own HTML shell and a 403. The panel then reported that as "no agents
// stored". Nothing was wrong with the token — it carried `cognito:groups: [admin]`
// and had 45 minutes left.
const BUILD_TYPES_BASE = '/api/v1/plugins/idea-scout'
const BUSINESS_MODELS_BASE = '/api/v1/plugins/idea-scout'
const AGENTS_BASE = '/api/v1/plugins/idea-scout/admin'
const MODEL_CATALOG_BASE = '/api/v1/plugins/idea-scout'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface BuildType {
  id: string
  key: string
  label: string
  description: string | null
  active: boolean | null
  sort_order: number | null
}

/** The fields an admin may set. `id` is Core's; `key` is immutable after create. */
export type BuildTypeDraft = Omit<BuildType, 'id'>

/** How an idea makes money. Structurally identical to BuildType by design — the
 * two admin-managed pickers share their table shape, their permission posture
 * and, here, their editor. Deliberately no valuation field: the taxonomy came
 * from a corpus of asking prices with no confirmed sales in it. */
export type BusinessModel = BuildType
export type BusinessModelDraft = BuildTypeDraft

export interface ChatAgent {
  agent_key: string
  agent_name: string
  role: string
  system_prompt: string
  model: string
  required_group: string
  active: boolean
  max_history_messages: number
  max_output_tokens: number
  timeout_seconds: number
}

export interface ModelCatalogEntry {
  id: string
  model_id: string
  label: string
  active: boolean | null
  is_default: boolean | null
  web_capable: boolean | null
}

async function request<T>(
  token: () => string | null,
  method: string,
  path: string,
  body?: unknown,
  base: string = BUILD_TYPES_BASE,
): Promise<T> {
  const idToken = token()
  const res = await fetch(`${base}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(idToken ? { Authorization: `Bearer ${idToken}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })

  if (!res.ok) {
    // Read the body for the reason: Core returns a JSON detail for a permission
    // failure, and "403" alone tells an admin nothing about which rule bit.
    const detail = await res.text().catch(() => res.statusText)
    throw new ApiError(res.status, detail || res.statusText)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export function createApi(token: () => string | null) {
  return {
    // Build types
    list: () => request<BuildType[]>(token, 'GET', '/build-types', undefined, BUILD_TYPES_BASE),
    create: (draft: BuildTypeDraft) =>
      request<BuildType>(token, 'POST', '/build-types', draft, BUILD_TYPES_BASE),
    update: (id: string, draft: BuildTypeDraft) =>
      request<BuildType>(token, 'PUT', `/build-types/${id}`, draft, BUILD_TYPES_BASE),
    remove: (id: string) => request<void>(token, 'DELETE', `/build-types/${id}`, undefined, BUILD_TYPES_BASE),

    // Business models
    listBusinessModels: () =>
      request<BusinessModel[]>(token, 'GET', '/business-models', undefined, BUSINESS_MODELS_BASE),
    createBusinessModel: (draft: BusinessModelDraft) =>
      request<BusinessModel>(token, 'POST', '/business-models', draft, BUSINESS_MODELS_BASE),
    updateBusinessModel: (id: string, draft: BusinessModelDraft) =>
      request<BusinessModel>(token, 'PUT', `/business-models/${id}`, draft, BUSINESS_MODELS_BASE),
    removeBusinessModel: (id: string) =>
      request<void>(token, 'DELETE', `/business-models/${id}`, undefined, BUSINESS_MODELS_BASE),

    // Chat agents
    listChatAgents: () => request<ChatAgent[]>(token, 'GET', '/chat-agents', undefined, AGENTS_BASE),
    getBuiltinAgents: () =>
      request<{ agents: ChatAgent[] }>(token, 'GET', '/builtin-agents', undefined, AGENTS_BASE),
    createChatAgent: (agent: Omit<ChatAgent, 'agent_key'>) =>
      request<ChatAgent>(token, 'POST', '/chat-agents', agent, AGENTS_BASE),
    updateChatAgent: (agentKey: string, updates: Partial<ChatAgent>) =>
      request<ChatAgent>(token, 'PUT', `/chat-agents/${agentKey}`, updates, AGENTS_BASE),
    deleteChatAgent: (agentKey: string) =>
      request<void>(token, 'DELETE', `/chat-agents/${agentKey}`, undefined, AGENTS_BASE),

    // Model catalog
    listModelCatalog: () =>
      request<ModelCatalogEntry[]>(token, 'GET', '/idea_scout_model_catalog', undefined, MODEL_CATALOG_BASE),
    createModelCatalogEntry: (entry: Omit<ModelCatalogEntry, 'id'>) =>
      request<ModelCatalogEntry>(token, 'POST', '/idea_scout_model_catalog', entry, MODEL_CATALOG_BASE),
    updateModelCatalogEntry: (entryId: string, updates: Partial<ModelCatalogEntry>) =>
      request<ModelCatalogEntry>(token, 'PUT', `/idea_scout_model_catalog/${entryId}`, updates, MODEL_CATALOG_BASE),
    deleteModelCatalogEntry: (entryId: string) =>
      request<void>(token, 'DELETE', `/idea_scout_model_catalog/${entryId}`, undefined, MODEL_CATALOG_BASE),
  }
}

export type Api = ReturnType<typeof createApi>

/**
 * Sort for display: `sort_order` ascending, ties broken by label.
 *
 * Mirrors the founder-facing picker's order (documented on the column) so an
 * admin sees the list in the order a founder will. `sort_order` is nullable —
 * the generated migration DDL does not apply declared defaults — and a null
 * sorts last rather than as zero, so an unordered row does not jump to the top.
 */
export function forDisplay(types: readonly BuildType[]): BuildType[] {
  return [...types].sort((a, b) => {
    const ao = a.sort_order ?? Number.MAX_SAFE_INTEGER
    const bo = b.sort_order ?? Number.MAX_SAFE_INTEGER
    return ao === bo ? a.label.localeCompare(b.label) : ao - bo
  })
}
