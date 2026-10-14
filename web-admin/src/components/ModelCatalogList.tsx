import { useState } from 'react'
import { statusBadgeClass, statusLabel } from '@biffo/design-tokens/status.mjs'
import { isBaseModelId, type ModelCatalogEntry } from '../lib/api'
import { ConfirmDelete } from './ConfirmDelete'

interface ModelCatalogListProps {
  entries: ModelCatalogEntry[]
  onUpdate: (entryId: string, updates: Partial<ModelCatalogEntry>) => void
  onDelete: (entryId: string) => void
}

const EDITABLE_FIELDS = ['model_id', 'label', 'active', 'is_default'] as const

export function ModelCatalogList({ entries, onUpdate, onDelete }: ModelCatalogListProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<ModelCatalogEntry>>({})
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [idError, setIdError] = useState<string | null>(null)

  function handleEdit(entry: ModelCatalogEntry) {
    setEditingId(entry.id)
    // Only editable fields: the fetched row also carries server-managed
    // columns (tenant_id, created_at, updated_at) that Core rejects on update.
    setEditForm({
      model_id: entry.model_id,
      label: entry.label,
      active: entry.active,
      is_default: entry.is_default,
    })
    setIdError(null)
  }

  function handleSaveEdit() {
    if (!editingId) return
    const current = entries.find((e) => e.id === editingId)
    // Only a changed id is checked, so a legacy ':' row can still be deactivated.
    if (editForm.model_id !== current?.model_id && !isBaseModelId(editForm.model_id ?? '')) {
      setIdError(
        "A model id cannot contain ':' — web search (':online') is decided per agent and is never chosen here.",
      )
      return
    }
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

  const defaults = entries.filter((e) => e.is_default)
  const currentDefault = defaults.length === 1 ? defaults[0] : null

  return (
    <div className="admin-list">
      <p className="admin-default-summary" role="status">
        {defaults.length === 0
          ? 'No default model is set.'
          : currentDefault
            ? `Current default model: ${currentDefault.label}`
            : `Warning: ${defaults.length} models are marked default (${defaults
                .map((d) => d.label)
                .join(', ')}). Saving a model as default will clear the others.`}
      </p>
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
                {idError != null && (
                  <span role="alert" className="admin-error">
                    {idError}
                  </span>
                )}
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

              <div className="admin-form-actions">
                <button onClick={handleSaveEdit} className="biffo-btn-primary">
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
                <span className={statusBadgeClass(entry.active ? 'active' : 'inactive')}>
                  {statusLabel(entry.active ? 'active' : 'inactive')}
                </span>
              </p>
              <p>
                <strong>Default:</strong>{' '}
                <span className={entry.is_default ? 'badge-default' : 'badge-not-default'}>
                  {entry.is_default ? 'Yes' : 'No'}
                </span>
              </p>
            </div>
            <div className="admin-list-actions">
              <button onClick={() => handleEdit(entry)} className="admin-btn-secondary">
                Edit
              </button>
              {confirmingId === entry.id ? (
                <ConfirmDelete
                  prompt="Delete this model?"
                  onConfirm={() => {
                    setConfirmingId(null)
                    onDelete(entry.id)
                  }}
                  onCancel={() => setConfirmingId(null)}
                />
              ) : (
                <button onClick={() => setConfirmingId(entry.id)} className="biffo-btn-delete">
                  Delete
                </button>
              )}
            </div>
          </div>
        ),
      )}
    </div>
  )
}
