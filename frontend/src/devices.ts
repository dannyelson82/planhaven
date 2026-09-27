// Friendly names for "signed-in devices" from a browser's user-agent string.
export function deviceName(userAgent: string | null): string {
  if (!userAgent) return 'Unknown device'
  const ua = userAgent
  const device = /iPhone/.test(ua) ? 'iPhone'
    : /iPad/.test(ua) ? 'iPad'
    : /Android/.test(ua) ? 'Android'
    : /Macintosh|Mac OS X/.test(ua) ? 'Mac'
    : /Windows/.test(ua) ? 'Windows PC'
    : /Linux/.test(ua) ? 'Linux'
    : 'Device'
  const browser = /Edg\//.test(ua) ? 'Edge'
    : /Firefox\/|FxiOS/.test(ua) ? 'Firefox'
    : /CriOS|Chrome\//.test(ua) ? 'Chrome'
    : /Safari\//.test(ua) ? 'Safari'
    : 'browser'
  return `${device} · ${browser}`
}
