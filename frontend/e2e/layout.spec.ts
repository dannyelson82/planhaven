import { expect, test } from '@playwright/test'
import { watchForProblems } from './helpers.ts'

// Phone (390 px) and desktop (1280 px) layouts (ARCHITECTURE.md §13.5).
test('layout fits the screen and navigation is where the thumb or mouse is', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const phone = info.project.name === 'phone'
  for (const path of ['/projects', '/assets', '/contacts', '/account']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, `horizontal scroll on ${path}`).toBeLessThanOrEqual(0)
  }
  // An asset page, with its details form.
  await page.goto('/assets')
  await page.getByRole('link', { name: 'Sea Ray 240' }).click()
  await expect(page.getByRole('heading', { name: 'Sea Ray 240' })).toBeVisible()
  await page.screenshot({ path: `test-results/screens/${info.project.name}-asset.png`, fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
  // Both menus are in the page; CSS shows one per screen size (side first, bottom last).
  const navs = page.locator('nav[aria-label="Main"]')
  const side = navs.first()
  const bottom = navs.last()
  if (phone) {
    await expect(bottom).toBeVisible()
    await expect(side).toBeHidden()
    const box = (await bottom.boundingBox())!
    expect(box.y + box.height).toBeGreaterThan(800) // docked at the bottom
    for (const link of await bottom.getByRole('link').all()) {
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
  } else {
    await expect(side).toBeVisible()
    await expect(bottom).toBeHidden()
  }
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()
  await page.screenshot({ path: `test-results/screens/${info.project.name}-project.png` })
  await page.goto('/projects')
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await page.screenshot({ path: `test-results/screens/${info.project.name}-projects.png` })
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('link', { name: 'Hardware store' }).click()
  await expect(page.getByRole('heading', { name: 'Hardware store' })).toBeVisible()
  await page.screenshot({ path: `test-results/screens/${info.project.name}-list.png` })
  await page.getByRole('link', { name: '← Back to project' }).click()
  await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()
  // Each task row (the checkbox's label) is the touch target.
  const rows = page.locator('label:has(input[type="checkbox"]):visible')
  await expect(rows.first()).toBeVisible()
  for (const row of await rows.all()) {
    expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  expect(problems).toEqual([])
})

// Installable app (A§13.5): manifest, icons and a service worker that opens the app offline.
test('installs as an app and opens offline', async ({ page, context }) => {
  const problems = watchForProblems(page)
  await page.goto('/projects')
  const manifest = await (await page.request.get('/manifest.webmanifest')).json()
  expect(manifest.display).toBe('standalone')
  for (const icon of manifest.icons as { src: string }[]) {
    expect((await page.request.get(icon.src)).ok(), icon.src).toBe(true)
  }
  await expect
    .poll(() => page.evaluate(async () => Boolean((await navigator.serviceWorker.getRegistration())?.active)))
    .toBe(true)
  // The service worker takes over the page it was installed from (clientsClaim), so a new
  // version reaches open pages without clearing site data.
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true)
  // Offline, the app itself still opens (data needs the server, so it says so).
  await context.setOffline(true)
  await page.reload()
  // Signed in on this device before: it opens with what it saved, and says it's offline.
  await expect(page.getByText(/^Offline: showing what this device saved/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  // Back online, it retries by itself.
  await context.setOffline(false)
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  expect(problems.filter((p) => !p.includes('Failed to load resource'))).toEqual([])
})

// In a shop with no signal: the list opens, items can be added and checked off, and the
// changes reach the server once back online.
test('lists work offline and catch up when back online', async ({ page, context }, info) => {
  const problems = watchForProblems(page)
  const extra = `Zip ties (${info.project.name})`
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('link', { name: 'Hardware store' }).click()
  await expect(page.getByRole('heading', { name: 'Hardware store' })).toBeVisible()
  const listUrl = page.url()
  const listId = listUrl.split('/').pop()
  await expect
    .poll(() => page.evaluate(async () => Boolean((await navigator.serviceWorker.getRegistration())?.active)))
    .toBe(true)
  // An item someone else will delete while we're offline.
  const rope = `Old rope (${info.project.name})`
  const csrf = (await (await page.request.get('/api/v1/auth/session')).json()).csrf_token
  const origin = new URL(page.url()).origin
  const ropeItem = await (await page.request.post(`/api/v1/lists/${listId}/items`, {
    data: { text: rope }, headers: { 'X-CSRF-Token': csrf, Origin: origin },
  })).json()
  await page.reload()
  await expect(page.getByText(rope)).toBeVisible()
  const before = await (await page.request.get(`/api/v1/lists/${listId}`)).json()
  const clamps = before.items.find((i: { text: string }) => i.text === 'Hose clamps')

  await context.setOffline(true)
  await page.reload()
  await expect(page.getByText(/^Offline: showing what this device saved/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Hardware store' })).toBeVisible()
  await page.getByLabel('Add item').fill(extra)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByText(extra)).toBeVisible()
  await expect(page.getByText('not sent yet')).toBeVisible()
  await page.locator('label', { hasText: 'Hose clamps' }).click()
  await page.locator('label', { hasText: rope }).click()
  const gone = await page.request.delete(`/api/v1/list-items/${ropeItem.id}`, { headers: { 'X-CSRF-Token': csrf, Origin: origin } })
  expect(gone.status()).toBe(204)

  await context.setOffline(false)
  await expect(page.getByText('not sent yet')).toBeHidden({ timeout: 15_000 })
  await expect(page.getByText(extra)).toBeVisible() // now from the server
  await expect(page.getByRole('alert')).toContainText(`Check off “${rope}”`)
  await page.getByRole('button', { name: 'OK' }).click()
  const after = await (await page.request.get(`/api/v1/lists/${listId}`)).json()
  expect(after.items.map((i: { text: string }) => i.text)).toContain(extra)
  expect(after.items.find((i: { text: string }) => i.text === 'Hose clamps').checked).toBe(!clamps.checked)
  expect(problems.filter((p) => !p.includes('Failed to load resource') && !p.includes('ERR_INTERNET_DISCONNECTED'))).toEqual([])
})
