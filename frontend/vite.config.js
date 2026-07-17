/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite proxies /api/* to the FastAPI backend so the SPA can call relative URLs
// without CORS or hardcoded hosts.
export default defineConfig({
  plugins: [react()],
  // Catalyst Web Client Hosting serves the app under a "/app/" path prefix.
  // A relative base makes the built index.html reference "./assets/..." so
  // scripts and styles resolve correctly under /app/ (absolute "/assets/..."
  // would 404). Relative base also keeps local `vite preview` working.
  base: './',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    // jsdom gives React component tests a DOM to render into.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.{test,property.test}.{js,jsx}'],
  },
})
