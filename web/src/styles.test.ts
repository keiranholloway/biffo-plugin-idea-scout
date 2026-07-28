/** The stylesheet has to actually style this app.
 *
 * This exists because it did not. `index.css` was the Ideation Engine's file,
 * copied verbatim when the plugin was scaffolded: every rule keyed on a
 * different prefix while these components emit `.candidate`, `.scorecard`,
 * `.run-form` and so on. **Zero of 35 class names matched.** The stylesheet
 * loaded fine — 57 rules — and styled nothing but the bare `button`/`input`
 * selectors, so the app rendered as one run-on line of browser defaults with
 * branded buttons dropped into it.
 *
 * Nothing caught that. Every unit test passed, the build was clean, the CSS
 * returned 200, and the only symptom was visual. A class-coverage check is the
 * cheapest thing that fails when a stylesheet and its markup belong to
 * different apps — which is one copy-paste away in any plugin scaffolded from
 * another.
 *
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// Read off disk rather than imported: Vitest stubs CSS imports (`css: false`),
// so `import css from './index.css?raw'` hands back an empty string and every
// check below passes vacuously — the exact failure shape this file exists to
// catch. `process.cwd()` is the package root under Vitest.
const SRC = join(process.cwd(), 'src')

// Comments stripped: this file's own prose names classes, and CSS comments
// explain the rules they sit above. A comment must never be able to make a
// rule look present.
const CSS = readFileSync(join(SRC, 'index.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

// The published token surface, read from the installed package rather than
// restated here — a second list would be one more thing to drift.
const PACKAGE_TOKENS = readFileSync(
  join(process.cwd(), 'node_modules/@biffo/design-tokens/tokens.css'),
  'utf8',
)

/** Every `className="…"` literal in the component tree, split into names.
 *
 * Deliberately literal-only. Template-interpolated names (`axis ${band(...)}`)
 * are listed in DYNAMIC below instead, because a regex that tried to evaluate
 * expressions would be guessing.
 */
function classNamesUsed(): Set<string> {
  const names = new Set<string>()
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(path)
        continue
      }
      if (!entry.name.endsWith('.tsx') || entry.name.endsWith('.test.tsx')) continue
      for (const [, value] of readFileSync(path, 'utf8').matchAll(/className="([^"{}]+)"/g)) {
        for (const name of value.split(/\s+/).filter(Boolean)) names.add(name)
      }
    }
  }
  walk(SRC)
  return names
}

/** Names built at runtime rather than written as literals. */
const DYNAMIC = ['axis--high', 'axis--mid', 'axis--low', 'axis-pip', 'axis-pip--on', 'active']

function isStyled(name: string): boolean {
  // Matches `.name` as a whole class token — `.axis` must not be satisfied by
  // `.axis-head`, or the check would pass on near-misses.
  return new RegExp(`\\.${name.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}(?![\\w-])`).test(CSS)
}

describe('index.css covers the classes this app emits', () => {
  it('styles every literal className in the components', () => {
    const unstyled = [...classNamesUsed()].filter((name) => !isStyled(name)).sort()

    expect(unstyled).toEqual([])
  })

  it('styles every dynamically-built class name', () => {
    expect(DYNAMIC.filter((name) => !isStyled(name)).sort()).toEqual([])
  })

  it('finds a meaningful number of classes, so an empty scan cannot pass', () => {
    // Guards the guard: a broken walk or regex yields an empty set, and "none
    // unstyled" would then be vacuously true — the same shape of vacuous pass
    // this file exists to catch.
    expect(classNamesUsed().size).toBeGreaterThan(20)
  })

  /**
   * The palette lives in `@biffo/design-tokens`, not here.
   *
   * This file used to declare its own copy of `--brand`, `--surface`, `--text`
   * and the rest. That was a deliberate copy at the time — the plugin deploys
   * separately and shares no bundler with the portal — but it is exactly how
   * three surfaces ended up with three different brand blues. Re-declaring a
   * shared token locally silently wins over the import, so the app would look
   * right while being disconnected from the platform's definition.
   *
   * App-specific variables are still fine; the check is only that a token the
   * package owns is not redefined here.
   */
  it('does not re-declare a token the shared package owns', () => {
    const shared = new Set(
      [...PACKAGE_TOKENS.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]),
    )
    const localised = [...CSS.matchAll(/(--[a-z0-9-]+)\s*:/g)]
      .map((m) => m[1])
      .filter((name) => shared.has(name))

    expect([...new Set(localised)]).toEqual([])
  })

  it('imports the shared tokens, so the variables it uses are actually defined', () => {
    // Without the import every `var(--brand)` silently falls back to nothing
    // and the app renders unstyled — the same failure mode as the stylesheet
    // that matched no classes, arriving through a different door.
    expect(CSS).toMatch(/@import\s+['"]@biffo\/design-tokens\/tokens\.css['"]/)
  })

  it('is not another plugin_s stylesheet', () => {
    // The specific failure: the Ideation Engine's rules living in this file.
    expect(CSS).not.toMatch(/\.ide-[a-z]/)
  })
})
