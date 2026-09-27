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
  await page.getByLabel('Notes').fill('5W-30, 6 quarts')
  await page.getByLabel('Due date').fill('2026-10-15')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('heading', { name: 'Edit task' })).toBeHidden()
  await expect(page.locator('label', { hasText: 'Change oil' })).toContainText('has notes')

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
