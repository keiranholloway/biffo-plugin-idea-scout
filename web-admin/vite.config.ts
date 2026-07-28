import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Served by the shared plugin host at /api/v1/plugins/idea-scout/admin/* (the
// API Gateway path, not a separate CloudFront/S3 origin the way the
// founder-facing web/ app is) — every asset/link URL must carry that full
// prefix, INCLUDING THIS PLUGIN'S OWN NAME.
//
// This file was copied from ideation's and kept ideation's base. The built
// index.html then requested idea-scout's own asset filenames under
// /api/v1/plugins/ideation/admin/assets/… — 503, blank page, and NOT ONE local
// gate caught it: lint, typecheck, 15 unit tests and the production build all
// passed, because `base` only affects the URLs inside the emitted HTML. It was
// visible solely by loading the page and reading the network log.
//
// Ideation's own comment records the neighbouring trap it hit: with a short
// base like "/ideation/admin/", CloudFront's 404->index.html rule papers the
// miss over as a 200 serving the PORTAL's homepage, so the browser tries to
// parse HTML as JS. Both failure modes are silent in different ways.
export default defineConfig({
  base: '/api/v1/plugins/idea-scout/admin/',
  plugins: [react()],
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
