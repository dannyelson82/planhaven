import fs from 'node:fs'
import { expect, test } from '@playwright/test'
import { ADMIN, totp, watchForProblems } from './helpers.ts'

// The first user's whole path through the app, in a real browser: setup, mandatory second
// factor, projects and tasks, signing out and back in. Saves the signed-in state for the
// layout tests.
test('first boot to first project', async ({ page }) => {
  const problems = watchForProblems(page)
  const setupToken = process.env.SETUP_TOKEN
  test.skip(!setupToken, 'SETUP_TOKEN not provided')

  await page.goto('/')
  await expect(page.getByRole('heading', { name: /create the admin account/i })).toBeVisible()
  await page.getByLabel('Setup token').fill(setupToken!)
  await page.getByLabel('Your name').fill(ADMIN.name)
  await page.getByLabel('Email').fill(ADMIN.email)
  await page.getByLabel('Password').fill(ADMIN.password)
  await page.getByRole('button', { name: 'Create admin account' }).click()

  // Second factor is mandatory: set up an authenticator app.
  await expect(page.getByRole('heading', { name: 'Protect your account' })).toBeVisible()
  await page.getByRole('button', { name: 'Use an authenticator app' }).click()
  const secret = (await page.locator('p.font-mono').textContent())!.trim()
  await page.getByLabel(/6-digit code/).fill(totp(secret))
  await page.getByRole('button', { name: 'Confirm' }).click()
  await expect(page.getByRole('heading', { name: 'Save your recovery codes' })).toBeVisible()
  await expect(page.locator('li.font-mono, ul.font-mono li')).toHaveCount(10)
  await page.getByRole('button', { name: "I've saved them" }).click()

  // Projects and tasks.
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await page.getByLabel('New project').fill('Winterize boat')
  await page.getByRole('button', { name: 'Add project' }).click()
  await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()
  for (const task of ['Drain water lines', 'Change oil', 'Cover the boat']) {
    await page.getByLabel('Add a task').fill(task)
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.getByText(task, { exact: true })).toBeVisible()
  }
  await expect(page.getByText('Next small step: Drain water lines')).toBeVisible()
  // Tap the task row (the checkbox's label), as a person would.
  await page.locator('label', { hasText: 'Drain water lines' }).click()
  await expect(page.getByText('Next small step: Change oil')).toBeVisible()
  await page.reload()
  await expect(page.getByText('Done (1)')).toBeVisible()

  // Edit a task: notes and a due date.
  await page.getByRole('button', { name: 'Edit Change oil' }).click()
  await expect(page.getByRole('heading', { name: 'Edit task' })).toBeVisible()
  await page.getByRole('dialog').getByLabel('Notes').fill('5W-30, 6 quarts')
  await page.getByLabel('Due date').fill('2026-10-15')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('heading', { name: 'Edit task' })).toBeHidden()
  await expect(page.locator('label', { hasText: 'Change oil' })).toContainText('has notes')

  // A shopping list, used like in a store.
  await page.getByLabel('New list').fill('Hardware store')
  await page.getByRole('button', { name: 'Add list' }).click()
  await page.getByRole('link', { name: 'Hardware store' }).click()
  await expect(page.getByRole('heading', { name: 'Hardware store' })).toBeVisible()
  await page.getByLabel('Add item').fill('Antifreeze')
  await page.getByLabel('Qty').fill('2')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByLabel('Add item').fill('Hose clamps')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.locator('label', { hasText: 'Antifreeze' }).click()
  await expect(page.getByText('In the cart (1)')).toBeVisible()
  // Edit mode: change a quantity; delete, then undo. No delete buttons outside edit mode.
  await expect(page.getByRole('button', { name: 'Delete Hose clamps' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByLabel('Quantity of Hose clamps').fill('4')
  await page.getByLabel('Quantity of Hose clamps').press('Enter')
  await page.getByRole('button', { name: 'Delete Hose clamps' }).click()
  await expect(page.getByText('Deleted “Hose clamps”')).toBeVisible()
  await page.getByRole('button', { name: 'Undo' }).click()
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page.locator('label', { hasText: 'Hose clamps' })).toContainText('4')
  await page.getByRole('link', { name: '← Back to project' }).click()
  await expect(page.getByText('Shopping · 1 to get of 2')).toBeVisible()
  // A whole list can be deleted from its edit mode (it goes to the trash).
  await page.getByLabel('New list').fill('Scrap list')
  await page.getByRole('button', { name: 'Add list' }).click()
  await page.getByRole('link', { name: 'Scrap list' }).click()
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByRole('button', { name: 'Delete this list' }).click()
  await page.getByRole('button', { name: 'Tap again to delete this list' }).click()
  await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Scrap list' })).toHaveCount(0)

  // The oil change needs the hose clamps from the list; the task says so until they're got.
  await page.getByRole('button', { name: 'Edit Change oil' }).click()
  await page.getByRole('group', { name: 'Items needed' }).getByLabel('Hose clamps').check()
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Needs 1 of 1 item: Hose clamps')).toBeVisible()

  // A note: edit, leave without Done (asked first), then Done saves and goes back.
  await page.getByRole('button', { name: 'New note' }).click()
  const title = page.getByLabel('Note title')
  await expect(title).toHaveValue('Untitled note')
  await title.fill('Engine notes')
  const editor = page.getByRole('textbox', { name: 'Note', exact: true })
  await editor.click()
  await editor.pressSequentially('Oil: 10W-30')
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: 'Checklist' }).click()
  await editor.pressSequentially('Change impeller')
  await expect(page.getByText('Not saved yet')).toBeVisible()
  // The back link asks: keep editing stays on the note.
  await page.getByRole('link', { name: '← Back to project' }).click()
  await expect(page.getByRole('heading', { name: 'Save your changes?' })).toBeVisible()
  await page.getByRole('button', { name: 'Keep editing' }).click()
  await expect(editor).toContainText('Change impeller')
  // So does the browser's back button.
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Save your changes?' })).toBeVisible()
  await page.getByRole('button', { name: 'Keep editing' }).click()
  await expect(page.getByLabel('Note title')).toHaveValue('Engine notes')
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Engine notes' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Notes' }).getByText(/Oil: 10W-30/).first()).toBeVisible()
  // The note's checkbox can be ticked from the project page; the note itself shows it.
  const impeller = page.getByRole('region', { name: 'Notes' }).getByRole('checkbox', { name: /Change impeller/ })
  await expect(impeller).not.toBeChecked()
  await impeller.check() // tick it from the project page
  await expect(impeller).toBeChecked()
  await page.reload()
  await expect(page.getByRole('region', { name: 'Notes' }).getByRole('checkbox', { name: /Change impeller/ })).toBeChecked()
  await page.getByRole('link', { name: 'Engine notes' }).click()
  await expect(page.getByRole('textbox', { name: 'Note', exact: true }).getByRole('checkbox')).toBeChecked()
  await page.getByRole('link', { name: '← Back to project' }).click()

  // A photo and a file: the photo gets a thumbnail, the file a download link.
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==', 'base64')
  await page.getByTestId('file-input').setInputFiles([
    { name: 'hull.png', mimeType: 'image/png', buffer: png },
    { name: 'parts.csv', mimeType: 'text/csv', buffer: Buffer.from('part,qty\nimpeller,1\n') },
    // An iPhone photo (HEIC): converted to JPEG, location removed.
    { name: 'IMG_0001.HEIC', mimeType: 'image/heic', buffer: fs.readFileSync(new URL('../../backend/tests/fixtures/iphone-photo.heic', import.meta.url)) },
  ])
  const thumb = page.getByRole('img', { name: 'hull.png' })
  await expect(thumb).toBeVisible()
  await expect.poll(() => thumb.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
  await expect(page.getByRole('link', { name: 'parts.csv' })).toHaveAttribute('href', /\/download$/)
  await expect.poll(() => page.getByRole('img', { name: 'IMG_0001.jpg' }).evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)

  // Deleted by mistake: the file comes back from the trash.
  await page.getByRole('button', { name: 'Delete parts.csv' }).click()
  await expect(page.getByRole('link', { name: 'parts.csv' })).toBeHidden()
  await page.goto('/trash')
  await page.getByRole('button', { name: 'Restore parts.csv' }).click()
  await page.getByRole('link', { name: 'Open' }).click()
  await expect(page.getByRole('link', { name: 'parts.csv' })).toBeVisible()

  // An asset (the boat) with details, linked to this project: its service history.
  const projectUrl = page.url()
  await page.goto('/assets')
  await page.getByLabel('New asset').fill('Sea Ray 240')
  await page.getByLabel('Kind').selectOption('boat')
  await page.getByRole('button', { name: 'Add asset' }).click()
  await expect(page.getByRole('heading', { name: 'Sea Ray 240' })).toBeVisible()
  await page.getByLabel('Hull ID', { exact: true }).fill('SERA1234B626')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled()
  // A photo of the boat (an iPhone HEIC), shown on the asset's card.
  await page.getByTestId('asset-photo-input').setInputFiles({
    name: 'boat.HEIC', mimeType: 'image/heic',
    buffer: fs.readFileSync(new URL('../../backend/tests/fixtures/iphone-photo.heic', import.meta.url)),
  })
  await expect(page.getByRole('button', { name: 'Change photo' })).toBeVisible()
  await page.getByRole('link', { name: '← All assets' }).click()
  await expect.poll(() => page.locator('img[src*="/photo/thumbnail"]').first().evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
  await page.goto(projectUrl)
  await page.getByLabel('For', { exact: true }).selectOption({ label: 'Sea Ray 240' })
  await page.getByRole('link', { name: 'Open' }).click()
  await expect(page.getByLabel('Hull ID', { exact: true })).toHaveValue('SERA1234B626')
  await expect(page.getByRole('region', { name: 'Service history' }).getByRole('link', { name: 'Winterize boat' })).toBeVisible()
  await page.goto(projectUrl)

  // A contractor, their quote, and what was paid (CAD).
  await page.goto('/contacts')
  await page.getByLabel('New contact').fill('Dave Pipes')
  await page.getByRole('button', { name: 'Add contact' }).click()
  await expect(page.getByRole('heading', { name: 'Dave Pipes' })).toBeVisible()
  await page.getByLabel('Phone').fill('555-0100')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('link', { name: 'Call' })).toHaveAttribute('href', 'tel:5550100')
  await page.goto(projectUrl)
  await page.getByRole('button', { name: 'Add a quote' }).click()
  await page.getByLabel('What for').fill('Rebuild water pump')
  await page.getByLabel('Contact', { exact: true }).selectOption({ label: 'Dave Pipes' })
  await page.getByLabel('Amount (CAD)').first().fill('1,850')
  await page.getByRole('button', { name: 'Add quote' }).click()
  await page.getByLabel('Status of Rebuild water pump').selectOption('accepted')
  await page.getByLabel('Money spent on').fill('Water pump kit')
  await page.getByLabel('Amount (CAD)').fill('1850')
  await page.getByLabel('Paid for quote').selectOption({ label: 'Rebuild water pump' })
  await page.getByRole('button', { name: 'Add cost' }).click()
  await expect(page.getByLabel('Total spent')).toHaveText(/1,850\.00/)

  // Sharing dialog lists the owner.
  await page.getByRole('button', { name: 'Share' }).click()
  await expect(page.getByRole('heading', { name: 'Share this project' })).toBeVisible()
  await expect(page.getByText('Test Admin (you)')).toBeVisible()
  await page.getByRole('button', { name: 'Done', exact: true }).click()

  // Admin: invite someone; they join in another browser. Then a password reset link for them.
  await page.goto('/admin')
  await page.getByRole('button', { name: 'Make invite link' }).click()
  const inviteUrl = await page.getByRole('textbox', { name: 'Invite link' }).inputValue()
  expect(inviteUrl).toMatch(/\/invite#phv_inv_/)
  const guest = await page.context().browser()!.newContext()
  const kid = await guest.newPage()
  await kid.goto(inviteUrl)
  await kid.getByLabel('Your name').fill('Sam')
  await kid.getByLabel('Email').fill('sam@example.com')
  await kid.getByLabel('Choose a password').fill('sam has a long password 42')
  await kid.getByRole('button', { name: 'Create my account' }).click()
  await expect(kid.getByRole('heading', { name: 'Protect your account' })).toBeVisible()
  await page.reload()
  const sam = page.getByRole('article', { name: 'Sam' })
  await expect(sam).toContainText('no second factor yet')
  await sam.getByRole('button', { name: 'Password reset link' }).click()
  const resetUrl = await page.getByRole('textbox', { name: 'Password reset link for Sam' }).inputValue()
  expect(resetUrl).toMatch(/\/reset#phv_rst_/)
  await kid.goto(resetUrl)
  await kid.getByLabel('New password').fill('sam chose another password 43')
  await kid.getByLabel('Type it again').fill('sam chose another password 43')
  await kid.getByRole('button', { name: 'Change password' }).click()
  await expect(kid.getByRole('heading', { name: 'Password changed' })).toBeVisible()
  await guest.close()

  // Account: new recovery codes (two taps).
  await page.goto('/account')
  await page.getByRole('button', { name: 'New recovery codes' }).click()
  await page.getByRole('button', { name: 'Tap again: replace my recovery codes' }).click()
  await expect(page.getByText(/Save these recovery codes/)).toBeVisible()

  // Sign out and back in, with the second factor.
  await page.goto('/account')
  await expect(page.getByText(/^PlanHaven (dev|\d+\.\d+\.\d+)$/)).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.getByLabel('Email').fill(ADMIN.email)
  await page.getByLabel('Password').fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: "Confirm it's you" })).toBeVisible()
  await page.getByLabel(/6-digit code/).fill(totp(secret, 1))
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await expect(page.getByText('Winterize boat')).toBeVisible()

  await page.context().storageState({ path: 'e2e/.auth/state.json' })

  // Offline for longer than the sign-in lasts: a change made offline isn't lost. (The session
  // is ended by dropping its cookie; the saved state above stays valid for the other tests.)
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('link', { name: 'Hardware store' }).click()
  await expect(page.getByRole('heading', { name: 'Hardware store' })).toBeVisible()
  await page.context().setOffline(true)
  await page.getByLabel('Add item').fill('Spark plugs')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByText('not sent yet')).toBeVisible()
  await page.context().clearCookies()
  await page.context().setOffline(false)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByText('1 change made offline is waiting. Sign in to send it.')).toBeVisible()
  expect(problems).toEqual([])
})
