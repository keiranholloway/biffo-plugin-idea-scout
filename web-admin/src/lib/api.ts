// Admin API client for Idea Scout's build-type categories.
//
// One base, and it is **Core's**, not this plugin's admin app. The five CRUD
// routes for `idea_scout_build_types` are declared in `biffo.plugin.json`'s
// `api_routes`, so Core generates them and the plugin host forwards them
// (biffo-template#684), authorised by the table's own permissions:
// list/read open to any authenticated caller (the founder's run form needs the
// list), create/update/delete admin-only.
//
// Calling them through this plugin's admin app instead would make the host call
// itself and then forward on to Core — three hops, and a 500 when they outrun
// the client's timeout. Ideation hit exactly that (biffo-template#652) and its
// api.ts carries the same warning.
const BASE = '/api/v1/plugins/idea-scout'

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

async function request<T>(
  token: () => string | null,
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const idToken = token()
  const res = await fetch(`${BASE}${path}`, {
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
    list: () => request<BuildType[]>(token, 'GET', '/build-types'),
    create: (draft: BuildTypeDraft) => request<BuildType>(token, 'POST', '/build-types', draft),
    update: (id: string, draft: BuildTypeDraft) =>
      request<BuildType>(token, 'PUT', `/build-types/${id}`, draft),
    remove: (id: string) => request<void>(token, 'DELETE', `/build-types/${id}`),
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
