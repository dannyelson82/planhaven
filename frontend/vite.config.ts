/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Installable app (A§13.5). The service worker caches only the app itself (index.html,
    // scripts, styles, icons), never API responses: no private data is stored by it.
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: false, // registered in main.tsx (no inline script: CSP)
      manifestFilename: 'manifest.webmanifest',
      manifest: {
        name: 'PlanHaven',
        short_name: 'PlanHaven',
        description: 'From idea to done',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#fafaf9',
        theme_color: '#1f8a64',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['index.html', 'static/**/*.{js,css}', 'icons/*.png'],
        // Phone alerts: the push and notification-tap handlers (public/push-sw.js).
        importScripts: ['/push-sw.js'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/healthz$/, /^\/readyz$/],
        runtimeCaching: [],
        inlineWorkboxRuntime: true,
        // A new version takes over open pages at once (main.tsx then reloads them), instead
        // of waiting until every tab and the home-screen app are closed.
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        maximumFileSizeToCacheInBytes: 1_000_000,
      },
    }),
  ],
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
