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
  type BusinessModel,
  type BusinessModelDraft,
  type ChatAgent,
  type ModelCatalogEntry,
} from './lib/api'
import { getCurrentSession, getFreshIdToken } from './lib/auth'

type Tab = 'build-types' | 'business-models' | 'agents' | 'models'

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
  // Created once and never rebuilt: `getFreshIdToken` is a stable module-level
  // function that re-resolves the session on every call, so the client itself
  // never goes stale — nothing here snapshots a token (biffo-plugin-ideation#69).
  const [api] = useState(() => createApi(getFreshIdToken))
  const [signedIn, setSignedIn] = useState<boolean | null>(null)
  const [tab, setTab] = useState<Tab>('build-types')

  // Build types state
  const [types, setTypes] = useState<BuildType[]>([])
  const [editing, setEditing] = useState<BuildType | null>(null)
  const [creating, setCreating] = useState(false)
  const [bizModels, setBizModels] = useState<BusinessModel[]>([])
  const [editingModel, setEditingModel] = useState<BusinessModel | null>(null)
  const [creatingModel, setCreatingModel] = useState(false)

  // Agents state
  const [agents, setAgents] = useState<ChatAgent[]>([])
  const [builtinAgents, setBuiltinAgents] = useState<ChatAgent[]>([])

  // Models state
  const [models, setModels] = useState<ModelCatalogEntry[]>([])

  const [loaded, setLoaded] = useState(false)
  // Keyed by concern, not one shared string. The four loaders fire concurrently
  // and each used to call `setError(null)` on success, so a 200 from one wiped a
  // failure from another purely on resolution order: agents 403'd, models
  // succeeded a moment later, and the agents error vanished before it was ever
  // rendered. That is half of why #69 presented as "no agents stored" with no
  // error anywhere — the panel HAD the reason and threw it away.
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const failed = useCallback((concern: string, message: string) => {
    setErrors((prev) => ({ ...prev, [concern]: message }))
  }, [])
  const succeeded = useCallback((concern: string) => {
    setErrors((prev) => {
      if (!(concern in prev)) return prev
      const next = { ...prev }
      delete next[concern]
      return next
    })
  }, [])
  const error = Object.values(errors).join(' · ') || null

  // Whether the agent loads FAILED, as opposed to returning nothing. The panel
  // must not make a claim about the founder's data on the strength of a request
  // that never succeeded.
  const agentsFailed = 'agents' in errors || 'builtin-agents' in errors

  // Only decides whether to show the panel or the "not signed in" message.
  // Requests themselves never read this — `api` re-resolves the token per
  // call via `getFreshIdToken`, so this snapshot going stale doesn't matter.
  useEffect(() => {
    let cancelled = false
    void getCurrentSession().then((session) => {
      if (cancelled) return
      setSignedIn(session != null)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const refreshBusinessModels = useCallback(async () => {
    try {
      setBizModels(forDisplay(await api.listBusinessModels()))
      succeeded('business-models')
    } catch (err) {
      failed(
        'business-models',
        err instanceof ApiError && err.status === 403
          ? 'Your account is not in the admin group, so business models cannot be changed.'
          : err instanceof Error
            ? err.message
            : 'Could not load business models.',
      )
    }
    // `api` is created once (useState initializer) and never changes identity,
    // so depending on it is safe — unlike the old `() => idToken` closure,
    // this doesn't churn on every render.
  }, [api])

  const refreshBuildTypes = useCallback(async () => {
    try {
      setTypes(forDisplay(await api.list()))
      succeeded('build-types')
    } catch (err) {
      failed(
        'build-types',
        err instanceof ApiError && err.status === 403
          ? 'Your account is not in the admin group, so build types cannot be changed.'
          : err instanceof Error
            ? err.message
            : 'Could not load build types.',
      )
    }
  }, [api])

  const refreshAgents = useCallback(async () => {
    try {
      setAgents(await api.listChatAgents())
      succeeded('agents')
    } catch (err) {
      failed('agents', `Failed to load agents: ${errorText(err)}`)
    }
  }, [api])

  const refreshModels = useCallback(async () => {
    try {
      setModels(await api.listModelCatalog())
      succeeded('models')
    } catch (err) {
      failed('models', `Failed to load models: ${errorText(err)}`)
    }
  }, [api])

  const refreshBuiltinAgents = useCallback(async () => {
    try {
      const result = await api.getBuiltinAgents()
      setBuiltinAgents(result.agents)
      succeeded('builtin-agents')
    } catch (err) {
      failed('builtin-agents', `Failed to load built-in agents: ${errorText(err)}`)
    }
  }, [api])

  useEffect(() => {
    if (signedIn !== true) return
    void refreshBuildTypes()
    void refreshBusinessModels()
    void refreshAgents()
    void refreshBuiltinAgents()
    void refreshModels()
    setLoaded(true)
  }, [
    signedIn,
    refreshBuildTypes,
    refreshBusinessModels,
    refreshAgents,
    refreshBuiltinAgents,
    refreshModels,
  ])

  async function saveBuildType(draft: BuildTypeDraft) {
    setBusy(true)
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
    try {
      if (editing) await api.update(editing.id, draft)
      else await api.create(draft)
      setEditing(null)
      setCreating(false)
      await refreshBuildTypes()
    } catch (err) {
      failed('action', err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }

  async function saveBusinessModel(draft: BusinessModelDraft) {
    setBusy(true)
    succeeded('action')
    try {
      if (editingModel) await api.updateBusinessModel(editingModel.id, draft)
      else await api.createBusinessModel(draft)
      setEditingModel(null)
      setCreatingModel(false)
      await refreshBusinessModels()
    } catch (err) {
      failed('action', err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleModelActive(model: BusinessModel) {
    setBusy(true)
    succeeded('action')
    try {
      await api.updateBusinessModel(model.id, {
        key: model.key,
        label: model.label,
        description: model.description,
        sort_order: model.sort_order,
        active: !(model.active ?? false),
      })
      await refreshBusinessModels()
    } catch (err) {
      failed('action', err instanceof Error ? err.message : 'Could not update.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(type: BuildType) {
    setBusy(true)
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
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
      failed('action', err instanceof Error ? err.message : 'Could not update.')
    } finally {
      setBusy(false)
    }
  }

  async function updateAgent(agentKey: string, updates: Partial<ChatAgent>) {
    setBusy(true)
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
    try {
      await api.updateChatAgent(agentKey, updates)
      await refreshAgents()
    } catch (err) {
      failed('action', `Failed to update agent: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function deleteAgent(agentKey: string) {
    if (!window.confirm('Delete this agent? This action cannot be undone.')) return
    setBusy(true)
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
    try {
      await api.deleteChatAgent(agentKey)
      await refreshAgents()
    } catch (err) {
      failed('action', `Failed to delete agent: ${errorText(err)}`)
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
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
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
      failed('action', `Failed to store default: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function createModel(entry: Omit<ModelCatalogEntry, 'id'>) {
    setBusy(true)
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
    try {
      await api.createModelCatalogEntry(entry)
      await refreshModels()
    } catch (err) {
      failed('action', `Failed to create model: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function updateModel(entryId: string, updates: Partial<ModelCatalogEntry>) {
    setBusy(true)
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
    try {
      await api.updateModelCatalogEntry(entryId, updates)
      await refreshModels()
    } catch (err) {
      failed('action', `Failed to update model: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  async function deleteModel(entryId: string) {
    if (!window.confirm('Delete this model? This action cannot be undone.')) return
    setBusy(true)
    // A previous action's failure must not linger over a new attempt.
    succeeded('action')
    try {
      await api.deleteModelCatalogEntry(entryId)
      await refreshModels()
    } catch (err) {
      failed('action', `Failed to delete model: ${errorText(err)}`)
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
              className={`admin-tab ${tab === 'business-models' ? 'admin-tab--active' : ''}`}
              onClick={() => setTab('business-models')}
            >
              Business Models
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

          {tab === 'business-models' && (
            <section className="admin-section">
              <h2>Business Models</h2>
              <p className="muted">
                How an idea makes money. Optional on the run form — a founder may have no
                preference, and an empty list here degrades a run rather than blocking it, unlike
                build types. Deactivating hides a model from new runs while existing runs keep
                referencing it by key, so prefer deactivating over deleting. Descriptions reach the
                research brief; keep prices and multiples out of them, since the taxonomy came from
                asking prices with no confirmed sales behind them.
              </p>

              <BuildTypeList
                types={bizModels}
                busy={busy}
                emptyMessage="No business models yet — the run form simply omits the picker until one exists."
                onEdit={(m) => {
                  setCreatingModel(false)
                  setEditingModel(m)
                }}
                onToggleActive={(m) => void toggleModelActive(m)}
              />

              {!creatingModel && editingModel == null && (
                <button type="button" className="primary" onClick={() => setCreatingModel(true)}>
                  Add a business model
                </button>
              )}

              {(creatingModel || editingModel != null) && (
                <BuildTypeForm
                  existing={editingModel}
                  busy={busy}
                  noun="business model"
                  onSave={(draft) => void saveBusinessModel(draft)}
                  onCancel={() => {
                    setEditingModel(null)
                    setCreatingModel(false)
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
                builtinAgents={builtinAgents}
                loadFailed={agentsFailed}
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
