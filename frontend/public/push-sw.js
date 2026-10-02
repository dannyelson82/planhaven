// Phone alerts (ADR 0018), loaded into the app's service worker (vite.config.ts importScripts).
// A push carries {title, body, url}; tapping the alert opens that page of the app. Only paths
// in this app are opened, never another site.
self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = {}
  }
  const title = typeof data.title === 'string' && data.title ? data.title.slice(0, 120) : 'PlanHaven'
  const body = typeof data.body === 'string' ? data.body.slice(0, 200) : ''
  const url = typeof data.url === 'string' && data.url.startsWith('/') && !data.url.startsWith('//') ? data.url : '/notifications'
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    data: { url },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const path = (event.notification.data && event.notification.data.url) || '/notifications'
  const target = new URL(path, self.location.origin)
  if (target.origin !== self.location.origin) return
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
        await client.focus()
        if ('navigate' in client) await client.navigate(target.href)
        return
      }
    }
    await self.clients.openWindow(target.href)
  })())
})
