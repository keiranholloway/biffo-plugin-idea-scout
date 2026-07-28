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

  it('is not another plugin_s stylesheet', () => {
    // The specific failure: the Ideation Engine's rules living in this file.
    expect(CSS).not.toMatch(/\.ide-[a-z]/)
  })
})
