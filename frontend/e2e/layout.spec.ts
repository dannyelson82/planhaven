import { expect, test } from '@playwright/test'
import { watchForProblems } from './helpers.ts'

// Phone (390 px) and desktop (1280 px) layouts (ARCHITECTURE.md §13.5).
test('layout fits the screen and navigation is where the thumb or mouse is', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const phone = info.project.name === 'phone'
  for (const path of ['/projects', '/assets', '/account']) {
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
