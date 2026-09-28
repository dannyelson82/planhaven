import { defineConfig, devices } from '@playwright/test'

// End-to-end tests against a running PlanHaven (container in CI, local server in dev).
// PLAYWRIGHT_BASE_URL must match the instance's BASE_URL; SETUP_TOKEN is its setup token.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:8123',
    trace: 'off',
  },
  projects: [
    { name: 'journey', testMatch: /journey\.spec\.ts/, use: { ...devices['Desktop Chrome'] } },
    {
      name: 'phone',
      testMatch: /layout\.spec\.ts/,
      dependencies: ['journey'],
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
        storageState: 'e2e/.auth/state.json',
      },
    },
    {
      name: 'desktop',
      testMatch: /layout\.spec\.ts/,
      dependencies: ['journey'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 }, storageState: 'e2e/.auth/state.json' },
    },
  ],
})
