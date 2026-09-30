import { useState } from 'react'
import type { ModelCatalogEntry } from '../lib/api'

interface ModelCatalogListProps {
  entries: ModelCatalogEntry[]
  onUpdate: (entryId: string, updates: Partial<ModelCatalogEntry>) => void
  onDelete: (entryId: string) => void
}

const EDITABLE_FIELDS = ['model_id', 'label', 'active', 'is_default', 'web_capable'] as const

export function ModelCatalogList({ entries, onUpdate, onDelete }: ModelCatalogListProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<ModelCatalogEntry>>({})

  function handleEdit(entry: ModelCatalogEntry) {
    setEditingId(entry.id)
    // Only editable fields: the fetched row also carries server-managed
    // columns (tenant_id, created_at, updated_at) that Core rejects on update.
    setEditForm({
      model_id: entry.model_id,
      label: entry.label,
      active: entry.active,
      is_default: entry.is_default,
      web_capable: entry.web_capable,
    })
  }

  function handleSaveEdit() {
    if (!editingId) return
    const original = entries.find((e) => e.id === editingId)
    // Send only the fields that actually changed.
    const changes: Partial<ModelCatalogEntry> = {}
    for (const key of EDITABLE_FIELDS) {
      if (editForm[key] !== undefined && editForm[key] !== original?.[key]) {
        ;(changes as Record<string, unknown>)[key] = editForm[key]
      }
    }
    if (Object.keys(changes).length > 0) onUpdate(editingId, changes)
    setEditingId(null)
    setEditForm({})
  }

  function handleCancel() {
    setEditingId(null)
    setEditForm({})
  }

  if (entries.length === 0) {
    return <p className="admin-empty">No models in the catalog yet.</p>
  }

  return (
    <div className="admin-list">
      {entries.map((entry) =>
        editingId === entry.id ? (
          <div key={entry.id} className="admin-list-item">
            <div className="admin-edit-form">
              <label>
                Model ID:
                <input
                  type="text"
                  value={editForm.model_id ?? ''}
                  onChange={(e) => setEditForm({ ...editForm, model_id: e.target.value })}
                />
              </label>

              <label>
                Label:
                <input
                  type="text"
                  value={editForm.label ?? ''}
                  onChange={(e) => setEditForm({ ...editForm, label: e.target.value })}
                />
              </label>

              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={editForm.active ?? false}
                  onChange={(e) => setEditForm({ ...editForm, active: e.target.checked })}
                />
                Active
              </label>

              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={editForm.is_default ?? false}
                  onChange={(e) => setEditForm({ ...editForm, is_default: e.target.checked })}
                />
                Default
              </label>

              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={editForm.web_capable ?? false}
                  onChange={(e) => setEditForm({ ...editForm, web_capable: e.target.checked })}
                />
                Web Capable
              </label>

              <div className="admin-form-actions">
                <button onClick={handleSaveEdit} className="admin-btn-primary">
                  Save
                </button>
                <button onClick={handleCancel} className="admin-btn-secondary">
                  Cancel
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div key={entry.id} className="admin-list-item">
            <div className="admin-list-content">
              <h3>{entry.label}</h3>
              <p>
                <strong>Model ID:</strong> <code>{entry.model_id}</code>
              </p>
              <p>
                <strong>Status:</strong>{' '}
                <span className={entry.active ? 'badge-active' : 'badge-inactive'}>
                  {entry.active ? 'Active' : 'Inactive'}
                </span>
              </p>
              <p>
                <strong>Default:</strong>{' '}
                <span className={entry.is_default ? 'badge-default' : 'badge-not-default'}>
                  {entry.is_default ? 'Yes' : 'No'}
                </span>
              </p>
              <p>
                <strong>Web Capable:</strong>{' '}
                <span className={entry.web_capable ? 'badge-web-capable' : 'badge-not-web-capable'}>
                  {entry.web_capable ? 'Yes' : 'No'}
                </span>
              </p>
            </div>
            <div className="admin-list-actions">
              <button onClick={() => handleEdit(entry)} className="admin-btn-secondary">
                Edit
              </button>
              <button onClick={() => onDelete(entry.id)} className="admin-btn-danger">
                Delete
              </button>
            </div>
          </div>
        ),
      )}
    </div>
  )
}
