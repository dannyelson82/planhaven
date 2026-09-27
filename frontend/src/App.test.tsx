import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { match } from './router.ts'
import { Button } from './ui.tsx'

describe('router', () => {
  it('matches app paths', () => {
    expect(match('/')).toEqual({ name: 'projects' })
    expect(match('/projects/0192a0e1-0000-7000-8000-000000000000')).toEqual({
      name: 'project',
      id: '0192a0e1-0000-7000-8000-000000000000',
    })
    expect(match('/projects/../../etc')).toEqual({ name: 'not-found' })
    expect(match('/invite')).toEqual({ name: 'invite' })
  })
})

describe('ui', () => {
  it('renders an accessible button with a 44px touch target', () => {
    const html = renderToString(<Button>Save</Button>)
    expect(html).toContain('Save')
    expect(html).toContain('min-h-11')
  })
})

import { deviceName } from './devices.ts'

describe('deviceName', () => {
  it('turns user agents into friendly names', () => {
    expect(deviceName('Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0 Mobile/15E148 Safari/604.1')).toBe('iPhone · Safari')
    expect(deviceName('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0 Safari/537.36')).toBe('Windows PC · Chrome')
    expect(deviceName(null)).toBe('Unknown device')
  })
})
