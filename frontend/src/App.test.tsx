import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import App from './App.tsx'

describe('App', () => {
  it('renders the product name', () => {
    expect(renderToString(<App />)).toContain('Planhaven')
  })
})
