import { useCallback, useEffect, useState } from 'react'

import { BuildTypeForm } from './components/BuildTypeForm'
import { BuildTypeList } from './components/BuildTypeList'
import { ApiError, createApi, forDisplay, type BuildType, type BuildTypeDraft } from './lib/api'
import { getCurrentSession } from './lib/auth'

/**
 * Idea Scout's admin surface: the build-type categories a founder picks from.
 *
 * This is success criterion 5 of the v1 epic — "an admin can add/edit/deactivate
 * build-type categories in a UI without a code change". The milestone that was
 * meant to deliver it (M5) was closed while the UI did not exist; #22 found the
 * manifest declaring `admin_ingress` with no `web-admin/` anywhere in the repo.
 */
export default function App() {
  const [idToken, setIdToken] = useState<string | null>(null)
  const [signedIn, setSignedIn] = useState<boolean | null>(null)
  const [types, setTypes] = useState<BuildType[]>([])
  const [loaded, setLoaded] = useState(false)
  const [editing, setEditing] = useState<BuildType | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const api = createApi(() => idToken)

  useEffect(() => {
    let cancelled = false
    void getCurrentSession().then((session) => {
      if (cancelled) return
      const token = session?.getIdToken().getJwtToken() ?? null
      setIdToken(token)
      setSignedIn(token != null)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      setTypes(forDisplay(await api.list()))
      setError(null)
    } catch (err) {
      // A 403 here is the common case and means "signed in, but not an admin".
      // Saying so beats "Failed to fetch", which reads as the service being down.
      setError(
        err instanceof ApiError && err.status === 403
          ? 'Your account is not in the admin group, so build types cannot be changed.'
          : err instanceof Error
            ? err.message
            : 'Could not load build types.',
      )
    } finally {
      setLoaded(true)
    }
  }, [idToken])

  useEffect(() => {
    if (idToken == null) return
    void refresh()
  }, [idToken, refresh])

  async function save(draft: BuildTypeDraft) {
    setBusy(true)
    try {
      if (editing) await api.update(editing.id, draft)
      else await api.create(draft)
      setEditing(null)
      setCreating(false)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(type: BuildType) {
    setBusy(true)
    try {
      await api.update(type.id, {
        key: type.key,
        label: type.label,
        description: type.description,
        sort_order: type.sort_order,
        active: !(type.active ?? false),
      })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update.')
    } finally {
      setBusy(false)
    }
  }

  if (signedIn === false) {
    return (
      <main className="page">
        <h1>Idea Scout — Admin</h1>
        <p className="error">Not signed in. Open this from the Biffo portal.</p>
      </main>
    )
  }

  return (
    <main className="page">
      <h1>Idea Scout — Admin</h1>
      <p className="muted">
        The categories a founder chooses from on the run form. Deactivating a category hides it
        from new runs; existing runs keep referencing it by key, so prefer deactivating over
        deleting.
      </p>

      {error != null && <p className="error">{error}</p>}

      {!loaded && <p className="muted">Loading…</p>}

      {loaded && (
        <>
          <BuildTypeList
            types={types}
            busy={busy}
            onEdit={(t) => {
              setCreating(false)
              setEditing(t)
            }}
            onToggleActive={(t) => void toggleActive(t)}
          />

          {!creating && editing == null && (
            <button type="button" className="primary" onClick={() => setCreating(true)}>
              Add a build type
            </button>
          )}

          {(creating || editing != null) && (
            <BuildTypeForm
              existing={editing}
              busy={busy}
              onSave={(draft) => void save(draft)}
              onCancel={() => {
                setEditing(null)
                setCreating(false)
              }}
            />
          )}
        </>
      )}
    </main>
  )
}
