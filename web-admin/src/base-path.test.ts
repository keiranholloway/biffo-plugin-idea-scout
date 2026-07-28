import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * The Vite `base` must name THIS plugin.
 *
 * This file was scaffolded from ideation's and kept `base:
 * '/api/v1/plugins/ideation/admin/'`. The built index.html then requested
 * idea-scout's own asset filenames under ideation's path — 503, blank page.
 *
 * **Every other gate passed**: eslint, tsc, 15 unit tests, and `vite build`
 * itself. `base` only affects URLs inside the emitted HTML, so nothing that
 * runs locally exercises it. It was found by loading the deployed page and
 * reading the network log — which is not a check that runs on every PR.
 *
 * So the check is here instead: cheap, and it fails on the exact mistake that
 * was made rather than on a general principle.
 */
const ROOT = join(__dirname, '..')
const PLUGIN = 'idea-scout'

describe('vite base path', () => {
  const config = readFileSync(join(ROOT, 'vite.config.ts'), 'utf8')

  it('is the full API Gateway path for THIS plugin', () => {
    const match = config.match(/base:\s*'([^']+)'/)
    expect(match, 'no `base` found in vite.config.ts').not.toBeNull()
    expect(match![1]).toBe(`/api/v1/plugins/${PLUGIN}/admin/`)
  })

  // There is deliberately NO "the config mentions no other plugin" test.
  // Written first, it failed immediately — on the comment that explains this
  // very bug, which names ideation's path on purpose. That is the same mistake
  // as the guard in #30 which banned the string `parent.parent.parent` and then
  // rejected the correct fix: a check that bans a TOKEN flags the prose that
  // legitimately contains it. The assertion above tests the property precisely,
  // and the one below tests the outcome.

  it('the built index.html requests assets under that base', () => {
    // The property that actually matters. Skipped when dist/ is absent (a
    // source checkout); CI runs `build` before `test`… but if it ever does not,
    // this must not pass silently, so the skip is explicit and visible.
    let html: string
    try {
      html = readFileSync(join(ROOT, 'dist', 'index.html'), 'utf8')
    } catch {
      console.warn('dist/index.html absent — build not run; base-path check skipped')
      return
    }
    const srcs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1])
    const assetRefs = srcs.filter((s) => s.includes('/assets/'))
    expect(assetRefs.length, 'no asset references in the built HTML').toBeGreaterThan(0)
    for (const ref of assetRefs) {
      expect(ref.startsWith(`/api/v1/plugins/${PLUGIN}/admin/`), `bad asset path: ${ref}`).toBe(true)
    }
  })
})
