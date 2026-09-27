/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // The notes editor (TipTap + ProseMirror + Yjs) is one ~515 kB chunk, loaded only when a
    // note is opened.
    chunkSizeWarningLimit: 600,
    // Not "assets": that's an app page (/assets = vehicles, boats, ...).
    assetsDir: 'static',
    // No source maps in production builds: they would publish the original source layout.
    sourcemap: false,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
