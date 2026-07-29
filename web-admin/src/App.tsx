import { useCallback, useEffect, useState } from 'react'

import { BuildTypeForm } from './components/BuildTypeForm'
import { BuildTypeList } from './components/BuildTypeList'
import { AgentList } from './components/AgentList'
import { ModelCatalogList } from './components/ModelCatalogList'
import { ModelCatalogForm } from './components/ModelCatalogForm'
import {
  ApiError,
  createApi,
  forDisplay,
  type BuildType,
  type BuildTypeDraft,
  type ChatAgent,
  type ModelCatalogEntry,
} from './lib/api'
import { getCurrentSession } from './lib/auth'

type Tab = 'build-types' | 'agents' | 'models'

function errorText(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

/**
 * Idea Scout's admin surface with three tabs:
 * - Build Types: the categories a founder picks from
 * - Agents: admin-editable prompts for four agent roles
 * - Models: CRUD for the model catalog with web_capable visibility
 */
export default function App() {
  const [idToken, setIdToken] = useState<string | null>(null)
  const [signedIn, setSignedIn] = useState<boolean | null>(null)
  const [tab, setTab] = useState<Tab>('build-types')

  // Build types state
  const [types, setTypes] = useState<BuildType[]>([])
  const [editing, setEditing] = useState<BuildType | null>(null)
  const [creating, setCreating] = useState(false)

  // Agents state
  const [agents, setAgents] = useState<ChatAgent[]>([])

  // Models state
  const [models, setModels] = useState<ModelCatalogEntry[]>([])

  const [loaded, setLoaded] = useState(false)
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

  const refreshBuildTypes = useCallback(async () => {
    try {
      setTypes(forDisplay(await api.list()))
      setError(null)
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? 'Your account is not in the admin group, so build types cannot be changed.'
          : err instanceof Error
            ? err.message
            : 'Could not load build types.',
      )
    }
  }, [idToken])

  const refreshAgents = useCallback(async () => {
    try {
      setAgents(await api.listChatAgents())
      setError(null)
    } catch (err) {
      setError(`Failed to load agents: ${errorText(err)}`)
    }
  }, [idToken])

  const refreshModels = useCallback(async () => {
    try {
      setModels(await api.listModelCatalog())
      setError(null)
    } catch (err) {
      setError(`Failed to load models: ${errorText(err)}`)
    }
  }, [idToken])

  useEffect(() => {
    if (idToken == null) return
    void refreshBuildTypes()
    void refreshAgents()
    void refreshModels()
    setLoaded(true)
  }, [idToken, refreshBuildTypes, refreshAgents, refreshModels])

  async function saveBuildType(draft: BuildTypeDraft) {
    setBusy(true)
    try {
      if (editing) await api.update(editing.id, draft)
      else await api.create(draft)
      setEditing(null)
      setCreating(false)
      await refreshBuildTypes()
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
      await refreshBuildTypes()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update.')
    } finally {
      setBusy(false)
    }
  }

  async function updateAgent(agentKey: string, updates: Partial<ChatAgent>) {
    setBusy(true)
    try {
      await api.updateChatAgent(agentKey, updates)
      await refreshAgents()
    } catch (err) {
      setError(`Failed to update agent: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function deleteAgent(agentKey: string) {
    if (!window.confirm('Delete this agent? This action cannot be undone.')) return
    setBusy(true)
    try {
      await api.deleteChatAgent(agentKey)
      await refreshAgents()
    } catch (err) {
      setError(`Failed to delete agent: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function storeBuiltinAgent(agent: ChatAgent) {
    if (
      !window.confirm(
        `Store "${agent.agent_key}" as an editable row?\n\n` +
          'It copies the built-in default exactly, so nothing changes now. ' +
          'From then on the stored row is what runs, and every edit you make ' +
          'here overrides the built-in default.',
      )
    )
      return
    setBusy(true)
    try {
      // Create a stored copy of the built-in agent
      const payload = {
        agent_name: agent.agent_name,
        role: agent.role,
        system_prompt: agent.system_prompt,
        model: agent.model,
        required_group: agent.required_group,
        active: agent.active,
        max_history_messages: agent.max_history_messages,
        max_output_tokens: agent.max_output_tokens,
        timeout_seconds: agent.timeout_seconds,
      }
      await api.createChatAgent(payload)
      await refreshAgents()
    } catch (err) {
      setError(`Failed to store default: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function createModel(entry: Omit<ModelCatalogEntry, 'id'>) {
    setBusy(true)
    try {
      await api.createModelCatalogEntry(entry)
      await refreshModels()
    } catch (err) {
      setError(`Failed to create model: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function updateModel(entryId: string, updates: Partial<ModelCatalogEntry>) {
    setBusy(true)
    try {
      await api.updateModelCatalogEntry(entryId, updates)
      await refreshModels()
    } catch (err) {
      setError(`Failed to update model: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function deleteModel(entryId: string) {
    if (!window.confirm('Delete this model? This action cannot be undone.')) return
    setBusy(true)
    try {
      await api.deleteModelCatalogEntry(entryId)
      await refreshModels()
    } catch (err) {
      setError(`Failed to delete model: ${errorText(err)}`)
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

      {error != null && <div className="admin-error">{error}</div>}

      {!loaded && <p className="muted">Loading…</p>}

      {loaded && (
        <>
          <div className="admin-tabs">
            <button
              className={`admin-tab ${tab === 'build-types' ? 'admin-tab--active' : ''}`}
              onClick={() => setTab('build-types')}
            >
              Build Types
            </button>
            <button
              className={`admin-tab ${tab === 'agents' ? 'admin-tab--active' : ''}`}
              onClick={() => setTab('agents')}
            >
              Agents
            </button>
            <button
              className={`admin-tab ${tab === 'models' ? 'admin-tab--active' : ''}`}
              onClick={() => setTab('models')}
            >
              Models
            </button>
          </div>

          {tab === 'build-types' && (
            <section className="admin-section">
              <h2>Build Types</h2>
              <p className="muted">
                The categories a founder chooses from on the run form. Deactivating a category hides
                it from new runs; existing runs keep referencing it by key, so prefer deactivating
                over deleting.
              </p>

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
                  onSave={(draft) => void saveBuildType(draft)}
                  onCancel={() => {
                    setEditing(null)
                    setCreating(false)
                  }}
                />
              )}
            </section>
          )}

          {tab === 'agents' && (
            <section className="admin-section">
              <h2>Agents</h2>
              <p className="muted">
                Admin-editable prompts and models for the four agent roles that run the research
                and synthesis.
              </p>
              <AgentList
                agents={agents}
                onUpdate={updateAgent}
                onDelete={deleteAgent}
                onStoreBuiltin={storeBuiltinAgent}
                busy={busy}
              />
            </section>
          )}

          {tab === 'models' && (
            <section className="admin-section">
              <h2>Models</h2>
              <p className="muted">
                The catalog of models available for research and synthesis. The{' '}
                <strong>web-capable</strong> flag indicates whether a model can reach the web
                through OpenRouter&apos;s :online suffix.
              </p>
              <ModelCatalogForm onSubmit={createModel} />
              <ModelCatalogList entries={models} onUpdate={updateModel} onDelete={deleteModel} />
            </section>
          )}
        </>
      )}
    </main>
  )
}
