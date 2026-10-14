import { useState } from 'react'
import { isBaseModelId, type ModelCatalogEntry } from '../lib/api'

interface ModelCatalogFormProps {
  onSubmit: (entry: Omit<ModelCatalogEntry, 'id'>) => void
}

export const BASE_ID_MESSAGE =
  "A model id cannot contain ':' — web search (':online') is decided per agent and is never chosen here."

export function ModelCatalogForm({ onSubmit }: ModelCatalogFormProps) {
  const [form, setForm] = useState<Omit<ModelCatalogEntry, 'id'>>({
    model_id: '',
    label: '',
    active: true,
    is_default: false,
  })
  const [idError, setIdError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isBaseModelId(form.model_id)) {
      setIdError(BASE_ID_MESSAGE)
      return
    }
    setIdError(null)
    onSubmit(form)
    setForm({
      model_id: '',
      label: '',
      active: true,
      is_default: false,
    })
    setShowForm(false)
  }

  return (
    <div className="admin-form-container">
      <button onClick={() => setShowForm(!showForm)} className="biffo-btn-primary">
        {showForm ? 'Cancel' : 'Add Model'}
      </button>

      {showForm && (
        <form onSubmit={handleSubmit} className="admin-form">
          <label>
            Model ID:
            <input
              type="text"
              required
              value={form.model_id}
              onChange={(e) => setForm({ ...form, model_id: e.target.value })}
              placeholder="e.g., anthropic/claude-opus-5.5"
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
              required
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="e.g., Claude Opus 5.5"
            />
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.active ?? false}
              onChange={(e) => setForm({ ...form, active: e.target.checked })}
            />
            Active
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.is_default ?? false}
              onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
            />
            Set as Default
          </label>

          <button type="submit" className="biffo-btn-primary">
            Create Model
          </button>
        </form>
      )}
    </div>
  )
}
