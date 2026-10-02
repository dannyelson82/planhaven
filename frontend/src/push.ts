// Phone alerts on this device (Web Push, ADR 0018): turning them on and off, and forgetting
// this browser on sign-out so the next person to use it doesn't get your alerts.
import { api } from './api.ts'

export type PushState = 'unsupported' | 'needs-home-screen' | 'blocked' | 'off' | 'on'

const isIos = () => /iPhone|iPad|iPod/.test(navigator.userAgent)
const standalone = () => window.matchMedia('(display-mode: standalone)').matches
  || (navigator as Navigator & { standalone?: boolean }).standalone === true

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null
  return (await navigator.serviceWorker.getRegistration('/')) ?? null
}

export async function pushState(): Promise<PushState> {
  if (!('PushManager' in window) || !('Notification' in window) || !('serviceWorker' in navigator)) {
    // iPhone: only an app added to the Home Screen can get alerts.
    return isIos() && !standalone() ? 'needs-home-screen' : 'unsupported'
  }
  if (Notification.permission === 'denied') return 'blocked'
  const reg = await registration()
  if (!reg) return 'unsupported'
  return (await reg.pushManager.getSubscription()) ? 'on' : 'off'
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const b64 = base64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (base64url.length % 4)) % 4)
  const raw = atob(b64)
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

function deviceLabel(): string {
  const ua = navigator.userAgent
  const device = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua) ? 'Android'
    : /Mac/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : 'Device'
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome'
    : /Safari\//.test(ua) ? 'Safari' : ''
  return [device, browser].filter(Boolean).join(' · ')
}

/** Ask for permission (needs a tap), subscribe with the server's key, register the device. */
export async function turnOn(): Promise<void> {
  const reg = await registration()
  if (!reg) throw new Error('Phone alerts need the installed app (or a browser that supports them).')
  if ((await Notification.requestPermission()) !== 'granted') {
    throw new Error('Alerts were not allowed. You can allow them in this device\'s settings.')
  }
  const { public_key } = await api<{ public_key: string }>('GET', '/api/v1/push/key')
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) })
  const json = sub.toJSON()
  await api('POST', '/api/v1/push/devices', {
    endpoint: sub.endpoint, p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '', label: deviceLabel(),
  })
}

/** Stop alerts on this device: unsubscribe and tell the server. */
export async function turnOff(): Promise<void> {
  const sub = await (await registration())?.pushManager.getSubscription()
  if (!sub) return
  await api('POST', '/api/v1/push/forget', { endpoint: sub.endpoint }).catch(() => undefined)
  await sub.unsubscribe().catch(() => false)
}

/** On sign-out (before the session ends): this browser stops getting this person's alerts. */
export async function forgetThisBrowser(): Promise<void> {
  try {
    await turnOff()
  } catch {
    // nothing registered
  }
}
