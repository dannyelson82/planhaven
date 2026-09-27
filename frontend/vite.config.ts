/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // No source maps in production builds: they would publish the original source layout.
    sourcemap: false,
  },
  test: {
    environment: 'node',
  },
})
