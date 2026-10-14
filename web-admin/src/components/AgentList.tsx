import { useState } from 'react'
import { statusBadgeClass, statusLabel } from '@biffo/design-tokens/status.mjs'
import type { AgentModelInfo, ChatAgent } from '../lib/api'
import { ConfirmDelete } from './ConfirmDelete'

type Row =
  | { kind: 'stored'; agent: ChatAgent }
  | { kind: 'builtin'; agent: ChatAgent }

function mergeAgentRows(storedAgents: ChatAgent[], builtinAgents: ChatAgent[]): Row[] {
  const storedKeys = new Set(storedAgents.map((a) => a.agent_key))

  return [
    // Stored rows first
    ...storedAgents.map(
      (agent): Row => ({
        kind: 'stored',
        agent,
      }),
    ),
    // Then built-ins with no stored row
    ...builtinAgents.filter((b) => !storedKeys.has(b.agent_key)).map(
      (agent): Row => ({
        kind: 'builtin',
        agent,
      }),
    ),
  ]
}

interface AgentListProps {
  agents: ChatAgent[]
  builtinAgents: ChatAgent[]
  /**
   * Whether either agent request FAILED, as distinct from returning nothing.
   *
   * "No agents stored" is a claim about the founder's configuration. Without
   * this flag it was made on the strength of two requests that came back 403,
   * which is how #69 looked like an empty table rather than a broken panel —
   * the fourth time this estate has rendered a failed fetch as an empty state,
   * and the second in this plugin after #53.
   */
  loadFailed?: boolean
  /** Each agent's effective model, web-search marker and drift, from `GET /model`. */
  modelInfo?: AgentModelInfo[]
  /** Re-applies the selected model (`PUT /model`), clearing drift. */
  onReapplyModel?: () => void
  onUpdate: (key: string, updates: Partial<ChatAgent>) => void
  onDelete: (key: string) => void
  onStoreBuiltin: (agent: ChatAgent) => void
  busy: boolean
}

export function AgentList({
  agents,
  builtinAgents,
  loadFailed = false,
  modelInfo = [],
  onReapplyModel,
  onUpdate,
  onDelete,
  onStoreBuiltin,
  busy,
}: AgentListProps) {
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<ChatAgent>>({})
  const [confirmingKey, setConfirmingKey] = useState<string | null>(null)

  function handleEdit(agent: ChatAgent) {
    setEditingKey(agent.agent_key)
    setEditForm({ ...agent })
  }

  function handleSaveEdit() {
    if (!editingKey) return
    // The model is never part of an agent edit: it is the one selected model.
    const { model: _model, ...updates } = editForm
    void _model
    onUpdate(editingKey, updates)
    setEditingKey(null)
    setEditForm({})
  }

  function handleCancel() {
    setEditingKey(null)
    setEditForm({})
  }

  const rows = mergeAgentRows(agents, builtinAgents)
  const infoFor = (key: string) => modelInfo.find((m) => m.agent_key === key)

  if (loadFailed) {
    // Deliberately NOT the empty state. The request failed; what is stored is
    // unknown, and saying "none" here is a false statement about the founder's
    // data rather than a missing one. The banner above carries the reason.
    return (
      <p className="admin-error">
        Could not load the agents, so what is configured is unknown. This is not the same as
        having none — see the error above.
      </p>
    )
  }

  if (rows.length === 0) {
    return <p className="admin-empty">No agents stored, and no built-in defaults reported.</p>
  }

  return (
    <>
      {agents.length === 0 && (
        <p className="admin-note">
          No agents are stored. The engine is running on the built-in defaults below — it is
          configured, just not from this table.
        </p>
      )}

      <div className="admin-list">
        {rows.map((row) =>
          row.kind === 'builtin' ? (
            <div key={row.agent.agent_key} className="admin-list-item admin-list-item--builtin">
              <div className="admin-list-content">
                <h3>{row.agent.agent_name}</h3>
                <p>
                  <strong>Source:</strong>{' '}
                  <span className="badge-builtin">Default — not stored</span>
                </p>
                <p>
                  <strong>Key:</strong> {row.agent.agent_key}
                </p>
                <p>
                  <strong>Role:</strong> {row.agent.role}
                </p>
                <ModelLine info={infoFor(row.agent.agent_key)} fallback={row.agent.model} />
                <details>
                  <summary>System prompt (built-in)</summary>
                  <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}>
                    {row.agent.system_prompt}
                  </pre>
                </details>
              </div>
              <div className="admin-list-actions">
                <button
                  onClick={() => onStoreBuiltin(row.agent)}
                  className="admin-btn-secondary"
                  disabled={busy}
                >
                  Store a copy to edit
                </button>
              </div>
            </div>
          ) : (
            <div key={row.agent.agent_key} className="admin-list-item">
              {editingKey === row.agent.agent_key ? (
                <div className="admin-edit-form">
                  <label>
                    Name:
                    <input
                      type="text"
                      value={editForm.agent_name ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, agent_name: e.target.value })}
                      disabled={busy}
                    />
                  </label>

                  <label>
                    Role:
                    <input
                      type="text"
                      value={editForm.role ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                      disabled={busy}
                    />
                  </label>

                  <label>
                    System Prompt:
                    <textarea
                      rows={12}
                      value={editForm.system_prompt ?? ''}
                      onChange={(e) =>
                        setEditForm({ ...editForm, system_prompt: e.target.value })
                      }
                      disabled={busy}
                    />
                  </label>

                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={editForm.active ?? false}
                      onChange={(e) => setEditForm({ ...editForm, active: e.target.checked })}
                      disabled={busy}
                    />
                    Active
                  </label>

                  <div className="admin-form-actions">
                    <button onClick={handleSaveEdit} className="biffo-btn-primary" disabled={busy}>
                      Save
                    </button>
                    <button onClick={handleCancel} className="admin-btn-secondary" disabled={busy}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="admin-list-content">
                    <h3>{row.agent.agent_name}</h3>
                    <p>
                      <strong>Source:</strong>{' '}
                      <span className="badge-stored">Stored</span>
                    </p>
                    <p>
                      <strong>Key:</strong> {row.agent.agent_key}
                    </p>
                    <p>
                      <strong>Role:</strong> {row.agent.role}
                    </p>
                    <ModelLine info={infoFor(row.agent.agent_key)} fallback={row.agent.model} />
                    {infoFor(row.agent.agent_key)?.drift === true && (
                      <p className="admin-error" role="status">
                        This agent&apos;s stored model ({infoFor(row.agent.agent_key)?.stored_model})
                        differs from the selected model.{' '}
                        <button
                          type="button"
                          className="admin-btn-secondary"
                          onClick={onReapplyModel}
                          disabled={busy || onReapplyModel == null}
                        >
                          Re-apply selected model
                        </button>
                      </p>
                    )}
                    <p>
                      <strong>Status:</strong>{' '}
                      <span className={statusBadgeClass(row.agent.active ? 'active' : 'inactive')}>
                        {statusLabel(row.agent.active ? 'active' : 'inactive')}
                      </span>
                    </p>
                    <details>
                      <summary>System prompt (in use)</summary>
                      <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}>
                        {row.agent.system_prompt}
                      </pre>
                    </details>
                  </div>
                  <div className="admin-list-actions">
                    <button
                      onClick={() => handleEdit(row.agent)}
                      className="admin-btn-secondary"
                      disabled={busy}
                    >
                      Edit
                    </button>
                    {confirmingKey === row.agent.agent_key ? (
                      <ConfirmDelete
                        prompt="Delete this agent?"
                        disabled={busy}
                        onConfirm={() => {
                          setConfirmingKey(null)
                          onDelete(row.agent.agent_key)
                        }}
                        onCancel={() => setConfirmingKey(null)}
                      />
                    ) : (
                      <button
                        onClick={() => setConfirmingKey(row.agent.agent_key)}
                        className="biffo-btn-delete"
                        disabled={busy}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          ),
        )}
      </div>
    </>
  )
}

/** The agent's effective model and its read-only web-search marker. Neither is
 * editable here: the model is the one selected above, and web search is decided
 * per agent in code. */
function ModelLine({ info, fallback }: { info: AgentModelInfo | undefined; fallback: string }) {
  const model = info?.effective_model ?? fallback
  return (
    <p>
      <strong>Model:</strong> <code>{model}</code>{' '}
      {info != null && (
        <span className="badge-readonly">web search: {info.web_search ? 'on' : 'off'}</span>
      )}
    </p>
  )
}
