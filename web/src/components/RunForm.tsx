import { useEffect, useState } from 'react'

import type {
  BuildType,
  BusinessModel,
  ComplexityLevel,
  ModelOption,
  Preference,
} from '../lib/api'

/** The run setup: what to look for, and how ambitious.
 *
 * Both lists come from the API rather than being hardcoded here. Build types are
 * admin-managed, and the complexity wording is served so that the words a founder
 * reads on the slider are the words the research agents are briefed with — two
 * copies would drift and this one would be the wrong one. Models are admin-curated;
 * the founder picks which to run agents on.
 */
export function RunForm({
  buildTypes,
  businessModels,
  complexityLevels,
  preferences,
  models,
  selectedModel,
  busy,
  onStart,
}: {
  buildTypes: BuildType[]
  businessModels: BusinessModel[]
  complexityLevels: ComplexityLevel[]
  preferences: Preference[]
  models: ModelOption[]
  selectedModel: string | null
  busy: boolean
  onStart: (
    buildType: string,
    complexity: number,
    preferences: string[],
    research_model?: string,
    business_model?: string,
  ) => void
}) {
  const [buildType, setBuildType] = useState<string>('')
  // Empty means "no preference", which is a real answer — so unlike buildType
  // this never gates submit. Defaulting it would scope every run from an input
  // the founder never made.
  const [businessModel, setBusinessModel] = useState<string>('')
  const [complexity, setComplexity] = useState<number>(3)
  // Nothing is pre-selected, deliberately. A default here would shape every
  // result from an input the founder never made — the invisible-input failure
  // this plugin has already had twice (#26, #29).
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set())
  const [modelId, setModelId] = useState<string>('')

  // Initialize or update the selected model: last-used, then default, then empty
  useEffect(() => {
    const defaultModel = findDefaultModel(models)
    if (selectedModel) {
      setModelId(selectedModel)
    } else if (defaultModel) {
      setModelId(defaultModel.id)
    } else {
      setModelId('')
    }
  }, [selectedModel, models])

  const selected = buildTypes.find((t) => t.key === buildType)
  const selectedModelKind = businessModels.find((m) => m.key === businessModel)
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
        if (buildType !== '') {
          // Both trailing arguments are optional and independent. `undefined`
          // rather than `''` for an unmade choice, so the api layer omits the
          // field entirely instead of sending an empty string the server would
          // have to interpret.
          onStart(
            buildType,
            complexity,
            [...chosen],
            modelId || undefined,
            businessModel || undefined,
          )
        }
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

      {businessModels.length > 0 && (
        <label className="field">
          <span className="field-label">How should it make money?</span>
          <select
            value={businessModel}
            onChange={(event) => setBusinessModel(event.target.value)}
            disabled={busy}
          >
            <option value="">No preference</option>
            {businessModels.map((model) => (
              <option key={model.key} value={model.key}>
                {model.label}
              </option>
            ))}
          </select>
          {selectedModelKind?.description != null && (
            <span className="field-hint">{selectedModelKind.description}</span>
          )}
        </label>
      )}

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

      {models.length > 0 && (
        <label className="field">
          <span className="field-label">Which model to run on?</span>
          <select
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
            disabled={busy}
          >
            {/* An explicit unselected option, so the select can never DISPLAY a
                model it has not got. A `<select>` whose value matches no option
                renders the first one, which is how a founder saw "Claude Sonnet 4
                (web)" while the state was empty. That is the same
                shows-a-value-it-does-not-have shape as the empty-vs-error
                conflations already fixed in this plugin (#53, #69) — and here it
                also blocked the run. Reachable whenever there is no last-used
                model and no catalog entry flagged `is_default`. */}
            <option value="">Use the built-in default</option>
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}
              </option>
            ))}
          </select>
        </label>
      )}

      {preferences.length > 0 && (
        <fieldset className="preferences" disabled={busy}>
          <legend className="field-label">What matters to you? (optional)</legend>
          <p className="field-hint">
            Preferences, not filters — a strong idea that cuts against one still appears, with
            the trade-off named.
          </p>
          {(['prefer', 'avoid'] as const).map((direction) => {
            const group = preferences.filter((p) => p.direction === direction)
            if (group.length === 0) return null
            return (
              <div className="preference-group" key={direction}>
                <span className="preference-group-label">
                  {direction === 'prefer' ? 'Lean towards' : 'Steer away from'}
                </span>
                {group.map((p) => (
                  <label className="preference" key={p.key}>
                    <input
                      type="checkbox"
                      checked={chosen.has(p.key)}
                      onChange={(event) => {
                        const next = new Set(chosen)
                        if (event.target.checked) next.add(p.key)
                        else next.delete(p.key)
                        setChosen(next)
                      }}
                    />
                    {p.label}
                  </label>
                ))}
              </div>
            )
          })}
        </fieldset>
      )}

      <button type="submit" disabled={busy || buildType === ''}>
        {busy ? 'Starting…' : 'Run now'}
      </button>

      <p className="run-form-note">
        Usually two to four minutes. You can close this tab — the scout finishes on its own and
        the results will be here when you come back. If something goes wrong it stops and tells
        you; it will not sit there indefinitely.
      </p>
    </form>
  )
}

function findDefaultModel(models: ModelOption[]): ModelOption | null {
  return models.find((m) => m.is_default) ?? null
}
