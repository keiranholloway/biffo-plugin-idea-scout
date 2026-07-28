import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Every className the components emit must be styled.
 *
 * This guard exists because idea-scout's founder app once shipped a stylesheet
 * copied wholesale from ideation: 35 classes defined, 0 of them the ones this
 * app emits, and the page rendered unstyled with every test green. The same
 * guard caught two unstyled classes in the founder app earlier today before CI
 * did.
 *
 * Read from disk rather than imported: vitest stubs CSS imports (`css: false`),
 * so `import css from './index.css?raw'` returns empty and the guard passes
 * vacuously — which is how it was first written, and how it first failed to
 * guard anything.
 */
const SRC = join(__dirname)

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(full)
    return /\.tsx$/.test(entry.name) && !/\.test\./.test(entry.name) ? [full] : []
  })
}

function classNamesUsed(): Set<string> {
  const names = new Set<string>()
  for (const file of sourceFiles(SRC)) {
    const source = readFileSync(file, 'utf8')
    for (const [, value] of source.matchAll(/className="([^"{}]+)"/g)) {
      for (const name of value.split(/\s+/).filter(Boolean)) names.add(name)
    }
  }
  return names
}

describe('index.css covers the classes this app emits', () => {
  const css = readFileSync(join(SRC, 'index.css'), 'utf8')

  it('styles every literal className in the components', () => {
    const unstyled = [...classNamesUsed()].filter((name) => !css.includes(`.${name}`))
    expect(unstyled).toEqual([])
  })

  it('finds classes at all, so the check above is not vacuous', () => {
    expect(classNamesUsed().size).toBeGreaterThan(5)
  })

  it('imports the shared design tokens rather than redefining the palette', () => {
    // Three surfaces once carried three different brand blues; the tokens
    // package exists to end that. A local hex for a token colour is the drift.
    expect(css).toContain("@import '@biffo/design-tokens/tokens.css'")
  })
})
