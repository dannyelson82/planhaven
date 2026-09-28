import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

// The service worker makes the app installable and open offline (it caches only the app
// itself; see vite.config.ts).
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .then((registration) => {
        // Look for a new version whenever the app comes back to the screen (a phone
        // resuming the home-screen app doesn't reload the page) and every hour while open.
        const check = () => void registration.update().catch(() => undefined)
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible') check()
        })
        setInterval(check, 60 * 60 * 1000)
      })
      .catch(() => undefined)
  })
  // A new version took over (after a server update): reload once so this tab runs it too,
  // instead of the copy saved on this device.
  const hadController = Boolean(navigator.serviceWorker.controller)
  let reloaded = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadController || reloaded) return
    reloaded = true
    window.location.reload()
  })
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
