import { useState } from 'react'
import type { ChatAgent } from '../lib/api'

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
  onUpdate: (key: string, updates: Partial<ChatAgent>) => void
  onDelete: (key: string) => void
  onStoreBuiltin: (agent: ChatAgent) => void
  busy: boolean
}

export function AgentList({
  agents,
  builtinAgents,
  onUpdate,
  onDelete,
  onStoreBuiltin,
  busy,
}: AgentListProps) {
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<ChatAgent>>({})

  function handleEdit(agent: ChatAgent) {
    setEditingKey(agent.agent_key)
    setEditForm({ ...agent })
  }

  function handleSaveEdit() {
    if (!editingKey) return
    onUpdate(editingKey, editForm)
    setEditingKey(null)
    setEditForm({})
  }

  function handleCancel() {
    setEditingKey(null)
    setEditForm({})
  }

  const rows = mergeAgentRows(agents, builtinAgents)

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
                    Model:
                    <input
                      type="text"
                      value={editForm.model ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, model: e.target.value })}
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
                    <button onClick={handleSaveEdit} className="admin-btn-primary" disabled={busy}>
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
                    <p>
                      <strong>Model:</strong> {row.agent.model}
                    </p>
                    <p>
                      <strong>Status:</strong>{' '}
                      <span className={row.agent.active ? 'badge-active' : 'badge-inactive'}>
                        {row.agent.active ? 'Active' : 'Inactive'}
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
                    <button
                      onClick={() => onDelete(row.agent.agent_key)}
                      className="admin-btn-danger"
                      disabled={busy}
                    >
                      Delete
                    </button>
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
