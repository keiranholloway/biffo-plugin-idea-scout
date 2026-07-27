import { useState } from 'react'

import type { BuildType, ComplexityLevel } from '../lib/api'

/** The run setup: what to look for, and how ambitious.
 *
 * Both lists come from the API rather than being hardcoded here. Build types are
 * admin-managed, and the complexity wording is served so that the words a founder
 * reads on the slider are the words the research agents are briefed with — two
 * copies would drift and this one would be the wrong one.
 */
export function RunForm({
  buildTypes,
  complexityLevels,
  busy,
  onStart,
}: {
  buildTypes: BuildType[]
  complexityLevels: ComplexityLevel[]
  busy: boolean
  onStart: (buildType: string, complexity: number) => void
}) {
  const [buildType, setBuildType] = useState<string>('')
  const [complexity, setComplexity] = useState<number>(3)

  const selected = buildTypes.find((t) => t.key === buildType)
  const level = complexityLevels.find((l) => l.value === complexity)

  if (buildTypes.length === 0) {
    // Not a loading state — the API answered with an empty list. That means no
    // active categories, which is an admin problem the founder cannot fix, so
    // say so rather than showing an empty picker that silently rejects.
    return (
      <div className="run-form run-form-empty">
        <p>
          No build types are configured yet, so a scout cannot be started. An admin needs to add
          at least one category.
        </p>
      </div>
    )
  }

  return (
    <form
      className="run-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (buildType !== '') onStart(buildType, complexity)
      }}
    >
      <label className="field">
        <span className="field-label">What are you looking to build?</span>
        <select
          value={buildType}
          onChange={(event) => setBuildType(event.target.value)}
          required
          disabled={busy}
        >
          <option value="" disabled>
            Choose a shape…
          </option>
          {buildTypes.map((type) => (
            <option key={type.key} value={type.key}>
              {type.label}
            </option>
          ))}
        </select>
        {selected?.description != null && (
          <span className="field-hint">{selected.description}</span>
        )}
      </label>

      <label className="field">
        <span className="field-label">How ambitious?</span>
        <input
          type="range"
          min={complexityLevels[0]?.value ?? 1}
          max={complexityLevels[complexityLevels.length - 1]?.value ?? 5}
          step={1}
          value={complexity}
          onChange={(event) => setComplexity(Number(event.target.value))}
          disabled={busy}
          aria-describedby="complexity-hint"
        />
        <span className="field-hint" id="complexity-hint">
          {level?.label ?? ''}
        </span>
      </label>

      <button type="submit" disabled={busy || buildType === ''}>
        {busy ? 'Starting…' : 'Run now'}
      </button>

      <p className="run-form-note">
        This takes a few minutes. You can close this tab — the scout finishes on its own and the
        results will be here when you come back.
      </p>
    </form>
  )
}
