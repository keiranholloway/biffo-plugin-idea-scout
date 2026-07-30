import { useState } from 'react'

import type { BuildType, BuildTypeDraft } from '../lib/api'

interface Props {
  existing: BuildType | null
  busy: boolean
  /** What this editor is editing, for copy only. The two admin-managed pickers
   * share a table shape and therefore share this form. */
  noun?: string
  onSave: (draft: BuildTypeDraft) => void
  onCancel: () => void
}

/** A URL-safe, stable identifier — what a run stores, so it must not drift. */
const KEY_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/

export function BuildTypeForm({ existing, busy, onSave, onCancel, noun = 'build type' }: Props) {
  const [key, setKey] = useState(existing?.key ?? '')
  const [label, setLabel] = useState(existing?.label ?? '')
  const [description, setDescription] = useState(existing?.description ?? '')
  const [sortOrder, setSortOrder] = useState(String(existing?.sort_order ?? ''))
  const [active, setActive] = useState(existing?.active ?? true)

  const keyValid = KEY_PATTERN.test(key)
  const canSave = !busy && label.trim() !== '' && keyValid

  return (
    <form
      className="build-type-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (!canSave) return
        onSave({
          key,
          label: label.trim(),
          description: description.trim() === '' ? null : description.trim(),
          active,
          sort_order: sortOrder.trim() === '' ? null : Number(sortOrder),
        })
      }}
    >
      <h2>{existing ? `Edit ${existing.label}` : `New ${noun}`}</h2>

      <label>
        Label
        <input value={label} onChange={(e) => setLabel(e.target.value)} required />
        <span className="hint">What the founder sees in the picker, e.g. “MicroSaaS”.</span>
      </label>

      <label>
        Key
        <input
          value={key}
          onChange={(e) => setKey(e.target.value)}
          disabled={existing != null}
          required
        />
        <span className="hint">
          {existing != null
            ? 'Immutable — existing runs reference this key, and changing it would orphan them.'
            : 'Lower-case and hyphenated, e.g. “micro-saas”. Stored on every run, so choose carefully.'}
        </span>
        {!keyValid && key !== '' && (
          <span className="field-error">Use lower-case letters, numbers and hyphens only.</span>
        )}
      </label>

      <label>
        Description
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
        <span className="hint">
          Shown under the label, and included in the research brief so the agents scope to it.
        </span>
      </label>

      <label>
        Sort order
        <input
          type="number"
          value={sortOrder}
          onChange={(e) => setSortOrder(e.target.value)}
          placeholder="—"
        />
        <span className="hint">Ascending. Blank sorts last.</span>
      </label>

      <label className="checkbox">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Offered to founders
      </label>

      <div className="form-actions">
        <button type="submit" className="primary" disabled={!canSave}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}
