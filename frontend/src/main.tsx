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
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => undefined)
  })
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
