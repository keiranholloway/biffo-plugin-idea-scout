import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Served from the shared plugin-host Lambda's StaticFiles mount (ADR-0021,
// biffo-template#1915/#1939), not this plugin's own S3/CloudFront origin
// (#130) — so every asset/link URL must carry the full
// /api/v1/plugins/idea-scout/ui/ prefix the host mounts the bundle under.
// Getting this wrong ships an app whose assets 404 — the Ideation Engine hit
// exactly that with the old per-plugin CloudFront path (its #51).
export default defineConfig({
  base: '/api/v1/plugins/idea-scout/ui/',
  plugins: [react()],
  // amazon-cognito-identity-js's `buffer` dependency references Node's `global`,
  // which Vite (unlike webpack/CRA) does not polyfill — without this the app
  // crashes on load with "ReferenceError: global is not defined".
  define: { global: 'globalThis' },
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
