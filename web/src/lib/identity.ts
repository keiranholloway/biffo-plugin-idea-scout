// Runtime core identity (#403/#400), mirroring the sibling skeleton's identity.ts.
//
// Core publishes its Cognito coordinates at /.well-known/biffo-identity.json,
// served same-origin from the portal bucket. We resolve it at RUNTIME so this app
// never bakes the core's pool/client id into its bundle — when core replaces its
// pool, we always see the current one. Same-origin (baseurl.com/ vs
// baseurl.com/ideation/) makes a relative fetch valid with no CORS. Memoised: at
// most one request per page load. Unreachable → null → the caller treats the
// visitor as signed out (a clean redirect beats trusting a stale local pool id).

export interface CoreIdentity {
  userPoolId: string
  clientId: string
  region?: string
  apiUrl?: string
  portalUrl?: string
}

const IDENTITY_DOCUMENT_PATH = '/.well-known/biffo-identity.json'

let cached: Promise<CoreIdentity | null> | null = null

function identityFromDocument(data: unknown): CoreIdentity | null {
  if (typeof data !== 'object' || data === null) return null
  const doc = data as Record<string, unknown>
  const userPoolId = typeof doc['userPoolId'] === 'string' ? doc['userPoolId'] : ''
  const clientId = typeof doc['clientId'] === 'string' ? doc['clientId'] : ''
  if (!userPoolId || !clientId) return null
  const identity: CoreIdentity = { userPoolId, clientId }
  if (typeof doc['region'] === 'string') identity.region = doc['region']
  if (typeof doc['apiUrl'] === 'string') identity.apiUrl = doc['apiUrl']
  if (typeof doc['portalUrl'] === 'string') identity.portalUrl = doc['portalUrl']
  return identity
}

async function fetchCoreIdentity(): Promise<CoreIdentity | null> {
  try {
    const res = await fetch(IDENTITY_DOCUMENT_PATH, { cache: 'no-store' })
    if (res.ok) {
      const identity = identityFromDocument(await res.json())
      if (identity) return identity
    }
  } catch {
    // Network error or fetch unavailable — fall through to null.
  }
  console.warn(
    `[biffo] could not resolve the core identity document at ${IDENTITY_DOCUMENT_PATH}; ` +
      'treating the visitor as signed out.',
  )
  return null
}

/** Resolve core's Cognito identity at runtime. Memoised; null when unreachable. */
export function resolveCoreIdentity(): Promise<CoreIdentity | null> {
  cached ??= fetchCoreIdentity()
  return cached
}

/** Test-only: clear the memoised resolution. */
export function __resetCoreIdentityForTests(): void {
  cached = null
}
