// Screenshots for the user guide (docs/user-guide/screens/{phone,desktop}/), taken on the
// sample data the journey test creates. Runs only when asked:
//   GUIDE_SHOTS=1 planhaven-e2e e2e/journey.spec.ts e2e/guide.spec.ts
// (npm run guide-shots against a running instance does the same). Commit the pictures with the
// guide change they belong to.
import { mkdirSync } from 'node:fs'
import { type Locator, type Page, test } from '@playwright/test'

test.skip(!process.env.GUIDE_SHOTS, 'Set GUIDE_SHOTS=1 to take the user guide screenshots')

async function shot(page: Page, device: string, name: string, target?: Locator) {
  const dir = new URL(`../../docs/user-guide/screens/${device}/`, import.meta.url).pathname
  mkdirSync(dir, { recursive: true })
  const options = { path: `${dir}${name}.jpg`, type: 'jpeg' as const, quality: 70, animations: 'disabled' as const }
  await page.waitForLoadState('networkidle')
  if (target) {
    await target.scrollIntoViewIfNeeded()
    await target.screenshot(options)
  } else {
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot(options)
  }
}

test('user guide screenshots', async ({ page }, info) => {
  test.setTimeout(120_000)
  const device = info.project.name // "phone" or "desktop"
  const main = page.locator('main')

  await page.goto('/projects')
  await page.getByRole('heading', { name: 'Projects' }).waitFor()
  await shot(page, device, 'projects')

  // A project: the top with the add bar, a drawer open, arranging.
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('heading', { name: 'Winterize boat' }).waitFor()
  const projectUrl = page.url()
  await shot(page, device, 'project')
  const bar = page.getByRole('toolbar', { name: 'Add to this project' })
  await bar.getByRole('button', { name: 'Task', exact: true }).click()
  await shot(page, device, 'add-bar', bar.locator('..'))
  await bar.getByRole('button', { name: 'Task', exact: true }).click()
  await page.getByRole('button', { name: 'Arrange' }).click()
  await shot(page, device, 'arrange')
  await page.getByRole('button', { name: 'Done' }).click()

  // Tiles on the project page.
  await shot(page, device, 'note-card', page.getByRole('region', { name: 'Notes' }).locator('li').first())
  await shot(page, device, 'photos', page.getByRole('region', { name: 'Photos and files' }))
  await shot(page, device, 'quotes', page.getByRole('region', { name: 'Quotes', exact: true }))
  await shot(page, device, 'costs', page.getByRole('region', { name: 'Costs' }))

  // Sharing.
  await page.getByRole('button', { name: 'Share' }).click()
  await shot(page, device, 'share', page.getByRole('dialog'))
  await page.getByRole('button', { name: 'Done', exact: true }).click()

  // A list, and its edit mode.
  await page.getByRole('link', { name: 'Hardware store' }).first().click()
  await page.getByRole('heading', { name: 'Hardware store' }).waitFor()
  await shot(page, device, 'list')
  await page.getByRole('button', { name: 'Edit' }).click()
  await shot(page, device, 'list-edit')
  await page.getByRole('button', { name: 'Done' }).click()

  // A note: the editor, and the question when leaving without saving.
  await page.goto(projectUrl)
  await page.getByRole('link', { name: 'Engine notes' }).first().click()
  await page.getByRole('textbox', { name: 'Note', exact: true }).waitFor()
  await shot(page, device, 'note-editor')
  await page.getByRole('textbox', { name: 'Note', exact: true }).click()
  await page.keyboard.press('Control+End')
  await page.keyboard.type(' ')
  await page.getByRole('link', { name: '← Back to project' }).click()
  await shot(page, device, 'note-leave', page.getByRole('dialog'))
  await page.getByRole('button', { name: 'Leave without saving' }).click()

  // A purchase, recorded from a list.
  await page.goto(projectUrl)
  const pid = projectUrl.split('/').pop()
  const csrf = (await (await page.request.get('/api/v1/auth/session')).json()).csrf_token
  const headers = { 'X-CSRF-Token': csrf, Origin: new URL(projectUrl).origin }
  const list = await (await page.request.post(`/api/v1/projects/${pid}/lists`, { data: { title: `Paint run (${device})`, kind: 'parts' }, headers })).json()
  for (const item of [{ text: 'Sandpaper', quantity: '3', price_cents: 150 }, { text: 'Marine varnish', price_cents: 2499 }]) {
    const added = await (await page.request.post(`/api/v1/lists/${list.id}/items`, { data: item, headers })).json()
    await page.request.patch(`/api/v1/list-items/${added.id}`, { data: { checked: true }, headers })
  }
  await page.goto(`/lists/${list.id}`)
  await page.getByRole('button', { name: 'Record purchase' }).click()
  await page.getByLabel('Store').waitFor()
  await page.getByLabel('Store').fill('Harbour Hardware')
  await page.getByLabel('Store').press('Enter')
  await page.getByLabel('Price each of Marine varnish').fill('22.99')
  await page.getByLabel('Price each of Marine varnish').press('Enter')
  await page.getByLabel('Amount paid (CAD)').fill('31.06')
  await page.getByLabel('Amount paid (CAD)').press('Enter')
  await page.getByText('Tax and other').waitFor()
  await shot(page, device, 'purchase', main)

  // Contacts, a contact, an asset.
  await page.goto('/contacts')
  await page.getByRole('heading', { name: 'Contacts' }).waitFor()
  await shot(page, device, 'contacts')
  await page.getByRole('link', { name: 'Dave Pipes' }).first().click()
  await page.getByRole('heading', { name: 'Dave Pipes' }).waitFor()
  await shot(page, device, 'contact')
  await page.goto('/assets')
  await page.getByRole('link', { name: 'Sea Ray 240' }).click()
  await page.getByRole('heading', { name: 'Sea Ray 240' }).waitFor()
  await shot(page, device, 'asset')

  // Trash, account, admin.
  await page.goto(`/projects/${pid}/trash`)
  await page.getByRole('heading', { name: /^Trash/ }).waitFor()
  await shot(page, device, 'trash')
  await page.goto('/account')
  await page.getByRole('heading', { name: 'Account' }).waitFor()
  await shot(page, device, 'account')
  await page.goto('/admin')
  await page.getByRole('heading', { name: 'Admin' }).waitFor()
  await shot(page, device, 'admin')
})

test.describe('signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } })
  test('user guide screenshot: signing in', async ({ page }, info) => {
    await page.goto('/')
    await page.getByRole('heading', { name: 'Sign in' }).waitFor()
    await shot(page, info.project.name, 'sign-in')
  })
})
