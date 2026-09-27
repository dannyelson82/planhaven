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
  await page.getByRole('link', { name: '← Back to project' }).click()
  await expect(page.getByText('Shopping · 1 to get of 2')).toBeVisible()

  // A note, edited in two tabs at once: typing in one appears live in the other.
  await page.getByRole('button', { name: 'New note' }).click()
  const title = page.getByLabel('Note title')
  await expect(title).toHaveValue('Untitled note')
  await title.fill('Engine notes')
  await title.press('Enter')
  const editor = page.getByRole('textbox', { name: 'Note', exact: true })
  await expect(page.getByText('Saved automatically')).toBeVisible()
  await editor.click()
  await editor.pressSequentially('Oil: 10W-30')
  const other = await page.context().newPage()
  const otherProblems = watchForProblems(other)
  await other.goto(page.url())
  await expect(other.getByRole('textbox', { name: 'Note', exact: true })).toContainText('Oil: 10W-30')
  await page.getByRole('button', { name: 'Checklist' }).click()
  await editor.pressSequentially('Change impeller')
  await expect(other.getByRole('textbox', { name: 'Note', exact: true }).getByRole('checkbox')).toHaveCount(1)
  await expect(other.getByRole('textbox', { name: 'Note', exact: true })).toContainText('Change impeller')
  expect(otherProblems).toEqual([])
  await other.close()
  await page.getByRole('link', { name: '← Back to project' }).click()
  await expect(page.getByRole('link', { name: 'Engine notes' })).toBeVisible()
  await expect(page.getByText(/Oil: 10W-30/)).toBeVisible()

  // A photo and a file: the photo gets a thumbnail, the file a download link.
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==', 'base64')
  await page.getByTestId('file-input').setInputFiles([
    { name: 'hull.png', mimeType: 'image/png', buffer: png },
    { name: 'parts.csv', mimeType: 'text/csv', buffer: Buffer.from('part,qty\nimpeller,1\n') },
  ])
  const thumb = page.getByRole('img', { name: 'hull.png' })
  await expect(thumb).toBeVisible()
  await expect.poll(() => thumb.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
  await expect(page.getByRole('link', { name: 'parts.csv' })).toHaveAttribute('href', /\/download$/)

  // Deleted by mistake: the file comes back from the trash.
  await page.getByRole('button', { name: 'Delete parts.csv' }).click()
  await expect(page.getByRole('link', { name: 'parts.csv' })).toBeHidden()
  await page.goto('/trash')
  await page.getByRole('button', { name: 'Restore' }).click()
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
  await page.goto(projectUrl)
  await page.getByLabel('For', { exact: true }).selectOption({ label: 'Sea Ray 240' })
  await page.getByRole('link', { name: 'Open' }).click()
  await expect(page.getByLabel('Hull ID', { exact: true })).toHaveValue('SERA1234B626')
  await expect(page.getByRole('region', { name: 'Service history' }).getByRole('link', { name: 'Winterize boat' })).toBeVisible()
  await page.goto(projectUrl)

  // Sharing dialog lists the owner.
  await page.getByRole('button', { name: 'Share' }).click()
  await expect(page.getByRole('heading', { name: 'Share this project' })).toBeVisible()
  await expect(page.getByText('Test Admin (you)')).toBeVisible()
  await page.getByRole('button', { name: 'Done', exact: true }).click()

  // Sign out and back in, with the second factor.
  await page.goto('/account')
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
  expect(problems).toEqual([])
})
