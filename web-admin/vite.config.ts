import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Served by the shared plugin host at /api/v1/plugins/ideation/admin/* (the
// API Gateway path, not a separate CloudFront/S3 origin the way the
// founder-facing web/ app is) — every asset/link URL must carry that full
// prefix. Confirmed the hard way: with just "/ideation/admin/", the built
// index.html requested its own JS/CSS at a path with no unauthenticated route
// and no Lambda mount, which CloudFront's 404->index.html custom error
// response silently papered over as a 200 (serving the PORTAL's homepage
// instead of erroring), so the browser tried to parse HTML as JS.
export default defineConfig({
  base: '/api/v1/plugins/ideation/admin/',
  plugins: [react()],
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
