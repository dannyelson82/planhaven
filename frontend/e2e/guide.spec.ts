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

  // A task's details (Change oil is done by now: it's under Done).
  await page.getByText(/^Done \(\d+\)$/).click()
  await page.getByRole('button', { name: 'Details: Change oil', exact: true }).first().click()
  await shot(page, device, 'task-details', page.getByRole('dialog'))
  await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()

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
  await page.getByRole('button', { name: 'Details: Hose clamps', exact: true }).click()
  await shot(page, device, 'item-details', page.getByRole('dialog'))
  await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()
  await page.getByRole('button', { name: 'Add many at once' }).click()
  await page.getByLabel('Items, one per line').fill('Zip ties\nDuct tape\nRags')
  await shot(page, device, 'add-many', page.getByRole('region', { name: 'Add many at once' }))
  await page.getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await shot(page, device, 'list-edit')
  await shot(page, device, 'move-items', page.getByRole('region', { name: 'Move items' }))
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

  // Suppliers (made once; the phone and computer runs share the data).
  await page.goto('/suppliers')
  await page.getByRole('heading', { name: 'Suppliers' }).waitFor()
  if (await page.getByRole('link', { name: 'Marine Depot' }).count() === 0) {
    await page.getByLabel('New supplier').fill('Marine Depot')
    await page.getByRole('button', { name: 'Add supplier' }).click()
    await page.getByRole('heading', { name: 'Marine Depot' }).waitFor()
    await page.goto('/suppliers')
  }
  await shot(page, device, 'suppliers')

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
  const service = page.getByRole('region', { name: 'Service', exact: true })
  if (await service.getByText('Engine oil and filter').count() === 0) {
    await service.getByRole('button', { name: '+ Reading' }).click()
    await service.getByLabel('Hours').fill('410')
    await service.getByRole('button', { name: 'Save reading' }).click()
    await service.getByText('Now: 410 hours').waitFor()
    await service.getByRole('button', { name: '+ Schedule' }).click()
    await service.getByLabel('What').fill('Engine oil and filter')
    await service.getByLabel('Hours').fill('100')
    await service.getByLabel('Months').fill('12')
    await service.getByLabel('Notes').fill('Mercury 25W-40, 5 quarts. Manual p. 52')
    await service.getByRole('button', { name: 'Save schedule' }).click()
    await service.getByRole('button', { name: 'Mark done' }).click()
    await service.getByLabel('Hours').fill('320')
    await service.getByRole('button', { name: 'Save', exact: true }).click()
    await service.getByText('Due soon').waitFor()
    await service.getByRole('button', { name: '+ Schedule' }).click()
    await service.getByLabel('What').fill('Water pump impeller')
    await service.getByLabel('Months').fill('24')
    await service.getByRole('button', { name: 'Save schedule' }).click()
    await service.getByText('Water pump impeller').waitFor()
  }
  await shot(page, device, 'asset-service', service)

  // Templates: one saved from the Hardware store list.
  const lists = await (await page.request.get(`/api/v1/projects/${pid}/lists`)).json()
  const hardware = lists.find((l: { title: string }) => l.title === 'Hardware store')
  const saved = await (await page.request.post(`/api/v1/lists/${hardware.id}/template`, { data: { name: `Boat parts (${device})` }, headers })).json()
  await page.goto('/templates')
  await page.getByRole('heading', { name: 'Templates' }).waitFor()
  await shot(page, device, 'templates')
  await page.goto(`/templates/${saved.id}`)
  await page.getByRole('heading', { name: saved.name }).waitFor()
  await shot(page, device, 'template')
  await page.goto(`/lists/${hardware.id}`)
  await page.getByRole('button', { name: 'Save as template' }).click()
  await shot(page, device, 'save-as-template', page.getByLabel('Template name').locator('xpath=ancestor::form'))

  // Share links: the form, the link made, and what the guest sees.
  await page.goto(`/projects/${pid}/links`)
  await page.getByRole('button', { name: 'Make a share link' }).click()
  await page.getByLabel('Name of the link').fill(`Dave's Garage (${device})`)
  await page.getByRole('checkbox', { name: 'Cover the boat' }).check()
  await page.getByLabel('Note they can add to').selectOption({ label: 'Engine notes' })
  await page.getByRole('checkbox', { name: 'Add photos (location removed)' }).check()
  await shot(page, device, 'share-link-new', page.locator('form').filter({ hasText: 'New share link' }))
  await page.getByRole('button', { name: 'Make the link' }).click()
  const url = await page.getByRole('textbox', { name: 'Share link' }).inputValue()
  // The picture shows an example address, never a real token.
  await page.getByRole('textbox', { name: 'Share link' }).evaluate((el: HTMLInputElement) => { el.value = 'https://planhaven.example.com/s#phv_shr_…' })
  await shot(page, device, 'share-link-made', page.locator('form, div').filter({ has: page.getByRole('textbox', { name: 'Share link' }) }).last())
  const guest = await page.context().browser()!.newContext({ viewport: page.viewportSize()!, isMobile: device === 'phone', hasTouch: device === 'phone' })
  const dave = await guest.newPage()
  await dave.goto(url)
  await shot(dave, device, 'guest-open')
  await dave.getByLabel('Your name').fill('Dave')
  await dave.getByRole('button', { name: 'Open' }).click()
  await dave.getByRole('heading', { name: 'Winterize boat' }).waitFor()
  await shot(dave, device, 'guest')
  await guest.close()

  // Trash, account, admin.
  await page.goto(`/projects/${pid}/trash`)
  await page.getByRole('heading', { name: /^Trash/ }).waitFor()
  await shot(page, device, 'trash')
  // As on a phone that hasn't been asked yet, so the guide shows Turn on phone alerts.
  // (Headless browsers report alerts as blocked; a real phone asks first.)
  await page.addInitScript(() => Object.defineProperty(Notification, 'permission', { get: () => 'default' }))
  await page.goto('/account')
  await page.getByRole('heading', { name: 'Account' }).waitFor()
  await shot(page, device, 'account')
  await shot(page, device, 'notification-settings', page.getByRole('region', { name: 'Notifications settings' }))
  await page.goto('/notifications')
  await page.getByRole('heading', { name: 'Notifications' }).waitFor()
  await shot(page, device, 'notifications')

  // Messages: a conversation with Sam (invited in the journey), made once.
  await page.goto('/messages')
  await page.getByRole('heading', { name: 'Messages' }).waitFor()
  const conversations = page.getByRole('list', { name: 'Conversations' })
  if (await conversations.getByRole('link', { name: /Sam/ }).count() === 0) {
    await page.getByRole('button', { name: 'New message' }).click()
    await page.getByRole('list', { name: 'People' }).getByRole('button', { name: /Sam/ }).click()
    await page.getByLabel('Message', { exact: true }).fill('Can you grab 2 quarts of 5W-30 on the way home?')
    await page.getByRole('button', { name: 'Send' }).click()
    await page.getByLabel('Message', { exact: true }).fill('For the boat, not the truck.')
    await page.getByRole('button', { name: 'Send' }).click()
    await page.getByRole('region', { name: 'Messages' }).getByText('For the boat, not the truck.').first().waitFor()
    await page.goto('/messages')
  }
  await shot(page, device, 'messages')
  await conversations.getByRole('link', { name: /Sam/ }).first().click()
  await page.getByRole('region', { name: 'Messages' }).getByText('For the boat, not the truck.').first().waitFor()
  await shot(page, device, 'conversation')

  // Chores: Take out the bins, weekly for me with a photo (made once).
  await page.goto(projectUrl)
  const bins = page.getByRole('button', { name: 'Details: Take out the bins', exact: true })
  if (await bins.count() === 0) {
    const adder = page.getByRole('toolbar', { name: 'Add to this project' })
    await adder.getByRole('button', { name: 'Task', exact: true }).click()
    await page.getByLabel('Add a task').fill('Take out the bins')
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await adder.getByRole('button', { name: 'Task', exact: true }).click()
  }
  {
    await bins.first().click()
    const chore = page.getByRole('dialog')
    await chore.getByRole('button', { name: 'Chore', exact: true }).click()
    if (await chore.getByLabel('Assign to').inputValue() === '') {
      await chore.getByLabel('Assign to').selectOption({ label: 'Me' })
      await chore.getByLabel('Due').fill('2026-10-06T19:00')
      await chore.getByLabel('Repeats').selectOption('weekly')
      await chore.getByLabel('Tue').check()
      await chore.getByLabel('Proof when done').selectOption({ label: 'A photo' })
    }
    await shot(page, device, 'chore-form', chore)
    await chore.getByRole('button', { name: 'Save' }).click()
    await chore.getByRole('button', { name: 'Close' }).click()
  }
  await page.goto('/chores')
  await page.getByRole('heading', { name: 'Chores', exact: true }).waitFor()
  await shot(page, device, 'chores')

  // The welcome tour and What's new (reopened from Help).
  await page.goto('/help')
  await page.getByRole('button', { name: 'Take the tour again' }).click()
  await page.getByRole('dialog', { name: 'Welcome tour' }).getByRole('button', { name: 'Next' }).click()
  await page.getByRole('dialog', { name: 'Welcome tour' }).getByRole('button', { name: 'Next' }).click()
  await shot(page, device, 'welcome-tour', page.getByRole('dialog', { name: 'Welcome tour' }))
  await page.getByRole('button', { name: 'Skip the tour' }).click()
  await page.getByRole('button', { name: "What's new" }).click()
  await page.getByRole('dialog', { name: "What's new" }).getByRole('button', { name: 'Next' }).click()
  await shot(page, device, 'whats-new', page.getByRole('dialog', { name: "What's new" }))
  await page.getByRole('dialog', { name: "What's new" }).getByRole('button', { name: 'Close' }).click()
  await page.goto('/admin')
  await page.getByRole('heading', { name: 'Admin' }).waitFor()
  await shot(page, device, 'admin')
  await shot(page, device, 'admin-experimental', page.getByRole('region', { name: 'Experimental features' }))
})

test.describe('signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } })
  test('user guide screenshot: signing in', async ({ page }, info) => {
    await page.goto('/')
    await page.getByRole('heading', { name: 'Sign in' }).waitFor()
    await shot(page, info.project.name, 'sign-in')
  })
})
