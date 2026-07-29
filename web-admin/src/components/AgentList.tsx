import { useState } from 'react'
import type { ChatAgent } from '../lib/api'

interface AgentListProps {
  agents: ChatAgent[]
  onUpdate: (key: string, updates: Partial<ChatAgent>) => void
  onDelete: (key: string) => void
  busy: boolean
}

export function AgentList({ agents, onUpdate, onDelete, busy }: AgentListProps) {
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

  if (agents.length === 0) {
    return <p className="admin-empty">No agents configured.</p>
  }

  return (
    <div className="admin-list">
      {agents.map((agent) =>
        editingKey === agent.agent_key ? (
          <div key={agent.agent_key} className="admin-list-item">
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
                  onChange={(e) => setEditForm({ ...editForm, system_prompt: e.target.value })}
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
          </div>
        ) : (
          <div key={agent.agent_key} className="admin-list-item">
            <div className="admin-list-content">
              <h3>{agent.agent_name}</h3>
              <p>
                <strong>Role:</strong> {agent.role}
              </p>
              <p>
                <strong>Model:</strong> {agent.model}
              </p>
              <p>
                <strong>Status:</strong>{' '}
                <span className={agent.active ? 'badge-active' : 'badge-inactive'}>
                  {agent.active ? 'Active' : 'Inactive'}
                </span>
              </p>
              <details>
                <summary>System prompt</summary>
                <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}>
                  {agent.system_prompt}
                </pre>
              </details>
            </div>
            <div className="admin-list-actions">
              <button onClick={() => handleEdit(agent)} className="admin-btn-secondary" disabled={busy}>
                Edit
              </button>
              <button onClick={() => onDelete(agent.agent_key)} className="admin-btn-danger" disabled={busy}>
                Delete
              </button>
            </div>
          </div>
        ),
      )}
    </div>
  )
}
