import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Served path-routed at <base>/idea-scout/* on the shared CloudFront (ADR-0018),
// so every asset/link URL must carry the /idea-scout/ prefix. The parent CDN
// forwards the full path to this app's S3 origin with no prefix stripping.
// Getting this wrong ships an app whose assets 404 — the Ideation Engine hit
// exactly that (its #51).
export default defineConfig({
  base: '/idea-scout/',
  plugins: [react()],
  // amazon-cognito-identity-js's `buffer` dependency references Node's `global`,
  // which Vite (unlike webpack/CRA) does not polyfill — without this the app
  // crashes on load with "ReferenceError: global is not defined".
  define: { global: 'globalThis' },
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
