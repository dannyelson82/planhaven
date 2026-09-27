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
