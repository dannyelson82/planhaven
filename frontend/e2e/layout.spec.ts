import { expect, test } from '@playwright/test'
import { row, tick, watchForProblems } from './helpers.ts'
import { RELEASES } from '../src/whatsnew.ts'

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
  await tick(page, 'Hose clamps')
  await tick(page, rope)
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

// Notes are saved on Done (docs/adr/0016). Typing fast, long wrapping lines, edits in the
// middle of wrapped text: every character is kept exactly once, and the card matches.
test('a note keeps exactly what was typed, saved on Done', async ({ page }, info) => {
  // Chrome's own editing sometimes tries to add a style while merging text; the CSP blocks
  // it and the editor redraws from its model. Only that browser-internal case is allowed.
  const problems = watchForProblems(page, { allowBrowserEditingStyles: true })
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('toolbar', { name: 'Add to this project' }).getByRole('button', { name: 'Note', exact: true }).click()
  await page.getByRole('button', { name: 'Create and write' }).click()
  const ed = () => page.getByRole('textbox', { name: 'Note', exact: true })
  await page.getByLabel('Note title').fill(`Wrapped (${info.project.name})`)
  const lines = [
    'GARBAGE TEXT STILL SHOWING UP IN THE NOTES WHEN SWITCHING BACK AND FORTH BETWEEN SCREENS',
    'FOUND AN = SIGN RANDOM "=" IN ONE OF THE LINES; (a) [b] {c} + - _ \' "',
    'Short third',
  ]
  await ed().click()
  for (const [i, line] of lines.entries()) {
    await page.keyboard.type(line, { delay: 2 })
    if (i < lines.length - 1) await page.keyboard.press('Enter')
  }
  const noteUrl = page.url()
  const edits = [
    async () => { const b = (await ed().locator('p').first().boundingBox())!; await page.mouse.click(b.x + b.width * 0.4, b.y + b.height - 4); await page.keyboard.type(' MID ', { delay: 2 }) },
    async () => { const b = (await ed().locator('p').nth(1).boundingBox())!; await page.mouse.click(b.x + 1, b.y + 4); await page.keyboard.press('Home'); await page.keyboard.press('Backspace') },
    async () => { await page.keyboard.type(' LAST WORDS', { delay: 1 }) },
  ]
  for (const edit of [async () => undefined, ...edits]) {
    await edit()
    const paragraphs = await ed().evaluate((el) => [...el.querySelectorAll('p')].map((p) => p.textContent!.replace(/\s+/g, ' ').trim()).filter(Boolean))
    await page.getByRole('button', { name: 'Done' }).click()
    await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()
    const card = page.getByRole('region', { name: 'Notes' }).locator('li', { hasText: `Wrapped (${info.project.name})` })
    await expect.poll(async () => (await card.innerText()).replace(/\s+/g, ' ')).toContain(paragraphs.join(' '))
    await page.goto(noteUrl)
    await expect(ed().locator('p')).toHaveText(paragraphs)
    await ed().click()
  }
  expect(problems).toEqual([])
})

test('leaving without saving keeps the note as it was', async ({ page }, info) => {
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('toolbar', { name: 'Add to this project' }).getByRole('button', { name: 'Note', exact: true }).click()
  await page.getByRole('button', { name: 'Create and write' }).click()
  await page.getByLabel('Note title').fill(`Keep me (${info.project.name})`)
  await page.getByRole('textbox', { name: 'Note', exact: true }).click()
  await page.keyboard.type('saved words')
  await page.getByRole('button', { name: 'Done' }).click()
  await page.getByRole('link', { name: `Keep me (${info.project.name})` }).click()
  await page.getByRole('textbox', { name: 'Note', exact: true }).click()
  await page.keyboard.type(' and unsaved words')
  await page.getByRole('link', { name: 'Projects' }).first().click()
  await expect(page.getByRole('heading', { name: 'Save your changes?' })).toBeVisible()
  await page.getByRole('button', { name: 'Leave without saving' }).click()
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('link', { name: `Keep me (${info.project.name})` }).click()
  await expect(page.getByRole('textbox', { name: 'Note', exact: true })).toHaveText('saved words')
})

// Ticking a checkbox on the project page, then editing the note: Done saves (it used to be
// refused as "saved by someone else"). Cards keep their order; Copy gives the note as text.
test('ticking on the card, then editing the note, saves without a conflict', async ({ page, context }, info) => {
  const problems = watchForProblems(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const title = `Ticks (${info.project.name})`
  const item = `Drain the block ${info.project.name}`
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('toolbar', { name: 'Add to this project' }).getByRole('button', { name: 'Note', exact: true }).click()
  await page.getByRole('button', { name: 'Create and write' }).click()
  await page.getByLabel('Note title').fill(title)
  const editor = page.getByRole('textbox', { name: 'Note', exact: true })
  await editor.click()
  await page.keyboard.type('Before the list')
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: 'Checklist' }).click()
  await page.keyboard.type(item)
  await page.getByRole('button', { name: 'Done' }).click()
  // Open it once (kept in this tab), come back, tick on the card.
  await page.getByRole('link', { name: title }).click()
  await expect(editor).toContainText(item)
  await page.getByRole('button', { name: 'Done' }).click()
  const notes = page.getByRole('region', { name: 'Notes' })
  await expect(notes.getByRole('checkbox', { name: item })).toBeVisible()
  const order = await notes.locator('li.break-inside-avoid').allInnerTexts()
  const box = notes.getByRole('checkbox', { name: item })
  // Wait for the tick to be saved (the checkbox shows it at once).
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/checklist') && r.request().method() === 'POST'),
    box.check(),
  ])
  await expect(box).toBeChecked()
  // The text before the list shows in order, as normal text, above the checkbox.
  const card = notes.locator('li.break-inside-avoid', { hasText: title })
  await expect(card.getByText('Before the list')).toBeVisible()
  // Tapping the words on the card (not a box) opens the note.
  await card.getByText('Before the list').click()
  await expect(editor).toContainText(item)
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(box).toBeChecked()
  // Cards don't move when a checkbox is ticked.
  await expect.poll(async () => (await notes.locator('li.break-inside-avoid').allInnerTexts()).map((t) => t.split('\n')[0])).toEqual(order.map((t) => t.split('\n')[0]))
  // Copy puts the whole note on the clipboard.
  await card.getByRole('button', { name: 'Copy note text' }).click()
  await expect(card.getByRole('button', { name: 'Copied' })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`Before the list\n☑ ${item}`)
  // Edit (pencil) opens the note; a change saves on Done.
  await card.getByRole('link', { name: 'Edit note' }).click()
  await editor.locator('p', { hasText: item }).click()
  await page.keyboard.press('End')
  await page.keyboard.type(' now')
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()
  await expect(notes.getByRole('checkbox', { name: `${item} now` })).toBeChecked()
  expect(problems).toEqual([])
})

// Arranging a project page (tiles): a note at the top, wide, with a photo beside it.
test('arranging the project page: a note at the top with a file beside it', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const desktop = info.project.name === 'desktop'
  const title = `Pinned (${info.project.name})`
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  await page.getByRole('toolbar', { name: 'Add to this project' }).getByRole('button', { name: 'Note', exact: true }).click()
  await page.getByRole('button', { name: 'Create and write' }).click()
  await page.getByLabel('Note title').fill(title)
  await page.getByRole('textbox', { name: 'Note', exact: true }).click()
  await page.keyboard.type('Keep this at the top')
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByRole('heading', { name: 'Winterize boat' })).toBeVisible()

  await page.getByRole('button', { name: 'Arrange' }).click()
  const back = page.getByRole('button', { name: 'Go back to the shared arrangement' })
  if (await back.isVisible()) await back.click() // start from the default
  const tiles = page.getByRole('grid', { name: 'Tiles on this page' })
  await expect(tiles.getByRole('row')).toHaveCount(6)
  const pick = page.getByLabel('Give its own tile')
  const fileLabel = (await pick.locator('option').allTextContents()).find((o) => o.startsWith('File: '))!
  await pick.selectOption({ label: fileLabel })
  await page.getByRole('button', { name: 'Add tile' }).click()
  await pick.selectOption({ label: `Note: ${title}` })
  // (Wait until it's saved: dragging while the list is being replaced can miss.)
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/layout') && r.request().method() === 'PUT'),
    page.getByRole('button', { name: 'Add tile' }).click(),
  ])
  // New tiles go to the top: the note, then the file. Drag the file above the note (rows are
  // dragged by mouse or touch; the ≡ handle is for the keyboard), then the note back above it.
  await expect(tiles.getByRole('row').first()).toContainText(`Note: ${title}`)
  const dragToTop = async (label: string) => {
    await expect(async () => {
      if (!(await tiles.getByRole('row').first().textContent())?.includes(label)) {
        await tiles.getByRole('row').filter({ hasText: label }).dragTo(tiles.getByRole('row').first(), { sourcePosition: { x: 20, y: 20 }, targetPosition: { x: 20, y: 5 } })
      }
      await expect(tiles.getByRole('row').first()).toContainText(label, { timeout: 1000 })
    }).toPass({ timeout: 10_000 })
  }
  await dragToTop(fileLabel)
  await dragToTop(`Note: ${title}`)
  await tiles.getByRole('group', { name: `Width of ${fileLabel}` }).getByRole('button', { name: 'Narrow' }).click()
  await expect(tiles.getByRole('group', { name: `Width of ${fileLabel}` }).getByRole('button', { name: 'Narrow' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Done' }).click()

  // Kept after a reload: the note first, the photo beside it on a computer (below on a phone),
  // both above the tasks; the Notes group no longer repeats the note.
  await page.reload()
  const note = page.getByRole('region', { name: `Note: ${title}` })
  const file = page.getByRole('region', { name: fileLabel })
  await expect(note).toContainText('Keep this at the top')
  const [n, f, tasks] = await Promise.all([note.boundingBox(), file.boundingBox(), page.getByRole('region', { name: 'Open tasks' }).boundingBox()])
  expect(n!.y).toBeLessThan(tasks!.y)
  if (desktop) {
    expect(Math.abs(f!.y - n!.y)).toBeLessThan(2)
    expect(f!.x).toBeGreaterThan(n!.x + n!.width - 1)
  } else {
    expect(f!.y).toBeGreaterThan(n!.y + n!.height - 1)
  }
  await expect(page.getByRole('region', { name: 'Notes' }).getByText(title)).toHaveCount(0)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)

  // Straight on the page, while arranging: drag the list card out of its group to just above
  // the notes, then drop it back on the Lists group.
  await page.getByRole('button', { name: 'Arrange' }).click()
  const listCard = page.locator('[data-movable^="list:"]').filter({ hasText: 'Hardware store' })
  // (Dropped on the tile just below its group, so the drag needn't scroll far.)
  const notesTile = page.getByRole('group', { name: 'Tile: Notes' })
  const listTile = page.getByRole('region', { name: 'List: Hardware store' })
  await expect(async () => {
    if (!(await listTile.count())) await listCard.dragTo(notesTile, { targetPosition: { x: 200, y: 20 } })
    await expect(listTile).toBeVisible({ timeout: 1000 })
  }).toPass({ timeout: 10_000 })
  expect((await listTile.boundingBox())!.y).toBeLessThan((await notesTile.boundingBox())!.y)
  await expect(tiles.getByRole('row').filter({ hasText: 'List: Hardware store' })).toHaveCount(1)
  await expect(async () => {
    if (await listTile.count()) await page.getByRole('group', { name: 'Tile: List: Hardware store' }).dragTo(page.getByRole('group', { name: 'Tile: Lists' }), { targetPosition: { x: 40, y: 10 } })
    await expect(listTile).toHaveCount(0, { timeout: 1000 })
  }).toPass({ timeout: 10_000 })
  await expect(page.getByRole('region', { name: 'Lists' }).getByRole('link', { name: 'Hardware store' })).toBeVisible()
  await page.getByRole('button', { name: 'Done' }).click()

  // Put the note back in its group, then back to the shared arrangement.
  await page.getByRole('button', { name: 'Arrange' }).click()
  await tiles.getByRole('button', { name: `Put Note: ${title} back in its group` }).click()
  await expect(note).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Notes' }).getByText(title)).toBeVisible()
  await page.getByRole('button', { name: 'Go back to the shared arrangement' }).click()
  await expect(tiles.getByRole('row')).toHaveCount(6)
  expect(problems).toEqual([])
})

// A shopping trip: checked-off list items become a purchase with their estimated prices; the
// store, what was actually paid and the receipt are added on its page.
test('recording a purchase from a list, with a receipt', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const name = info.project.name
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  const projectUrl = page.url()
  const pid = projectUrl.split('/').pop()
  const csrf = (await (await page.request.get('/api/v1/auth/session')).json()).csrf_token
  const headers = { 'X-CSRF-Token': csrf, Origin: new URL(projectUrl).origin }
  const list = await (await page.request.post(`/api/v1/projects/${pid}/lists`, { data: { title: `Trip (${name})`, kind: 'parts' }, headers })).json()
  for (const item of [{ text: 'Sandpaper', quantity: '3', price_cents: 150 }, { text: 'Varnish', price_cents: 2499 }]) {
    const added = await (await page.request.post(`/api/v1/lists/${list.id}/items`, { data: item, headers })).json()
    await page.request.patch(`/api/v1/list-items/${added.id}`, { data: { checked: true }, headers })
  }
  await page.goto(`/lists/${list.id}`)
  await page.getByRole('button', { name: 'Record purchase' }).click()

  // The purchase page: the items came with their estimated prices.
  await expect(page.getByRole('heading', { name: `Trip (${name})`, level: 1 })).toBeVisible()
  await expect(page.getByLabel('Items total')).toHaveText(/29\.49/)
  await expect(page.getByLabel('Amount paid (CAD)')).toHaveValue('29.49')
  await page.getByLabel('Store').fill('Harbour Hardware')
  await page.getByLabel('Store').press('Enter')
  // What the varnish really cost.
  await page.getByLabel('Price each of Varnish').fill('22.99')
  await page.getByLabel('Price each of Varnish').press('Enter')
  await expect(page.getByLabel('Items total')).toHaveText(/27\.49/)
  // Paid with tax: the difference shows as tax and other.
  await page.getByLabel('Amount paid (CAD)').fill('31.06')
  await page.getByLabel('Amount paid (CAD)').press('Enter')
  await expect(page.getByText('Tax and other')).toBeVisible()
  await page.getByLabel('Choose the receipt').setInputFiles({ name: `receipt-${name}.pdf`, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n') })
  await expect(page.getByRole('link', { name: `receipt-${name}.pdf` })).toBeVisible()
  // One more item typed in.
  await page.getByLabel('Add an item').fill('Brushes')
  await page.getByLabel('Price each', { exact: true }).fill('4.00')
  await page.getByRole('button', { name: 'Add item', exact: true }).click()
  await expect(page.getByLabel('Items total')).toHaveText(/31\.49/)
  await page.getByRole('button', { name: 'Use the items total as the amount paid' }).click()
  await expect(page.getByLabel('Amount paid (CAD)')).toHaveValue('31.49')

  // On the project: one line, with its details.
  await page.getByRole('link', { name: '← Back to project' }).click()
  const costs = page.getByRole('region', { name: 'Costs' })
  await expect(costs.getByRole('link', { name: `Trip (${name})` })).toBeVisible()
  await expect(costs.getByRole('listitem').filter({ hasText: `Trip (${name})` })).toContainText(/Harbour Hardware · 3 items · receipt/)
  expect(problems).toEqual([])
})

// Contacts from and to a phone (contact cards), and suggestions while typing a list item.
test('a contact card from the phone, and item suggestions', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const name = `Sue Sparks ${info.project.name}`
  await page.goto('/contacts')
  await page.getByLabel('Choose a contact card').setInputFiles({
    name: 'Sue.vcf', mimeType: 'text/vcard',
    buffer: Buffer.from(`BEGIN:VCARD\r\nVERSION:3.0\r\nFN:${name}\r\nORG:Sparks Electric\r\nTEL:555-0142\r\nEND:VCARD\r\n`),
  })
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(page.getByLabel('Company')).toHaveValue('Sparks Electric')
  const card = await page.request.get((await page.getByRole('link', { name: 'Save to phone' }).getAttribute('href'))!)
  expect(await card.text()).toContain(`FN:${name}`)

  // Suggestions: items added before on any list, with their quantity and price.
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  const pid = page.url().split('/').pop()
  const csrf = (await (await page.request.get('/api/v1/auth/session')).json()).csrf_token
  const list = await (await page.request.post(`/api/v1/projects/${pid}/lists`, {
    data: { title: `Next trip (${info.project.name})`, kind: 'shopping' }, headers: { 'X-CSRF-Token': csrf, Origin: new URL(page.url()).origin },
  })).json()
  await page.goto(`/lists/${list.id}`)
  await page.getByLabel('Add item').fill('hose')
  await page.getByRole('button', { name: 'Use suggestion: Hose clamps' }).click()
  await expect(page.getByLabel('Add item')).toHaveValue('Hose clamps')
  await expect(page.getByLabel('Qty')).toHaveValue('4')
  await expect(page.getByText('Price each: $2.50')).toBeVisible()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(row(page, 'Hose clamps').first()).toContainText('$10.00')
  expect(problems).toEqual([])
})

// The user guide in the app: from the footer, between pages, screenshots for this screen size.
test('the Help pages', async ({ page }, info) => {
  const problems = watchForProblems(page)
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Help', exact: true }).last().click()
  await expect(page.getByRole('heading', { name: 'PlanHaven user guide' })).toBeVisible()
  await page.getByRole('link', { name: 'Lists', exact: true }).last().click()
  await expect(page.getByRole('heading', { name: 'Lists', level: 1 })).toBeVisible()
  const shot = page.getByRole('img', { name: 'Edit mode: name, quantity and price each, and delete' }).filter({ visible: true })
  await expect(shot).toHaveCount(1)
  // The phone picture on a phone (390 px wide), the computer one on a computer (1280 px).
  await expect.poll(() => shot.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(0)
  const width = await shot.evaluate((img: HTMLImageElement) => img.naturalWidth)
  expect(info.project.name === 'phone' ? width < 800 : width > 800).toBe(true)
  // A link to another page of the guide stays in the app.
  await page.getByRole('link', { name: 'Quotes, costs and purchases' }).first().click()
  await expect(page.getByRole('heading', { name: 'Quotes, costs and purchases', level: 1 })).toBeVisible()
  await page.getByRole('link', { name: '← All help' }).first().click()
  await expect(page.getByRole('heading', { name: 'PlanHaven user guide' })).toBeVisible()
  expect(problems).toEqual([])
})

// Templates: a list saved and used again; a project's tasks saved and added from the add bar.
test('templates for lists and tasks', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const name = `Boat parts (${info.project.name})`
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  const projectUrl = page.url()
  await page.getByRole('link', { name: 'Hardware store' }).first().click()
  await page.getByRole('button', { name: 'Save as template' }).click()
  await page.getByLabel('Template name').fill(name)
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(page.getByRole('status')).toContainText(`Saved as template “${name}”`)
  await page.getByRole('status').getByRole('link', { name: 'Open' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'In this template' })).toContainText('Hose clamps')
  // Use it: a new list with the same items and estimated prices.
  await page.getByLabel('Project').selectOption({ label: 'Winterize boat' })
  await page.getByRole('button', { name: 'Make this list' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(row(page, 'Hose clamps')).toBeVisible()

  // Tasks: saved from the project, added again from the + Task drawer.
  await page.goto(projectUrl)
  await page.getByRole('button', { name: 'Save tasks as template' }).click()
  await page.getByLabel('Template name').fill(`Winterize (${info.project.name})`)
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(page.getByRole('status')).toContainText('Saved as template')
  const before = await page.getByRole('region', { name: 'Open tasks' }).getByRole('checkbox').count()
  await page.getByRole('toolbar', { name: 'Add to this project' }).getByRole('button', { name: 'Task', exact: true }).click()
  await page.getByLabel('Task template').selectOption({ label: `Winterize (${info.project.name}) (${before})` })
  await page.getByRole('button', { name: 'Use template' }).click()
  await expect(page.getByRole('region', { name: 'Open tasks' }).getByRole('checkbox')).toHaveCount(before * 2)
  expect(problems).toEqual([])
})

// A long list pasted at once, sorted into another list later; an item's details (owner
// requests, 2026-10-02). The add bar stays at the top while the page scrolls.
test('a big list sorted later, and item details', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const tag = info.project.name
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  const bar = page.getByRole('toolbar', { name: 'Add to this project' })
  await page.mouse.wheel(0, 3000)
  await expect(bar).toBeInViewport()
  await bar.getByRole('button', { name: 'List', exact: true }).click()
  for (const title of [`Brain dump ${tag}`, `Marine store ${tag}`]) {
    await page.getByLabel('New list').fill(title)
    await page.getByRole('button', { name: 'Add list' }).click()
    await expect(page.getByRole('link', { name: title })).toBeVisible()
  }
  const store = await page.getByRole('link', { name: `Marine store ${tag}` }).getAttribute('href')
  await page.getByRole('link', { name: `Brain dump ${tag}` }).click()

  await page.getByRole('button', { name: 'Add many at once' }).click()
  await page.getByLabel('Items, one per line').fill(`- Impeller ${tag}\n- Fuel filter ${tag}\n\n3. Groceries ${tag}`)
  await page.getByRole('button', { name: 'Add 3 items' }).click()
  await expect(row(page, `Groceries ${tag}`)).toBeVisible()

  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  const move = page.getByRole('region', { name: 'Move items' })
  await move.getByLabel(`Impeller ${tag}`).check()
  await move.getByLabel(`Fuel filter ${tag}`).check()
  await move.getByLabel('Move to').selectOption({ label: `Marine store ${tag}` })
  await move.getByRole('button', { name: 'Move 2 items' }).click()
  await expect(row(page, `Impeller ${tag}`)).toHaveCount(0)
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(row(page, `Groceries ${tag}`)).toBeVisible()

  // In the other list: details with a website and notes, edited from the details.
  await page.goto(store!)
  await row(page, `Impeller ${tag}`).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('No notes')).toBeVisible()
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await dialog.getByLabel('Website').fill('not a link')
  await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()
  await dialog.getByLabel('Website').fill('https://example.com/impeller')
  await dialog.getByLabel('Notes').fill('Part 47-43026')
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(dialog.getByRole('link', { name: 'https://example.com/impeller' })).toBeVisible()
  await expect(dialog.getByText('Part 47-43026')).toBeVisible()
  await dialog.getByRole('button', { name: 'Close' }).click()
  // Ticking is the circle only.
  await tick(page, `Impeller ${tag}`)
  await expect(page.getByText('In the cart (1)')).toBeVisible()
  await expect(dialog).toHaveCount(0)
  expect(problems).toEqual([])
})

// Suppliers on list items, archived notes, and an asset's maintenance schedule (maintainer's
// testing notes, 2026-10-02).
test('suppliers, archived notes and asset service', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const tag = info.project.name
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  const project = page.url()

  // A supplier made from an item's details, then found in Suppliers (not in Contacts).
  const bar = page.getByRole('toolbar', { name: 'Add to this project' })
  await bar.getByRole('button', { name: 'List', exact: true }).click()
  await page.getByLabel('New list').fill(`Parts run ${tag}`)
  await page.getByLabel('List type').selectOption('parts')
  await page.getByRole('button', { name: 'Add list' }).click()
  await page.getByRole('link', { name: `Parts run ${tag}` }).click()
  await page.getByLabel('Add item').fill(`Bilge pump ${tag}`)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await row(page, `Bilge pump ${tag}`).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await dialog.getByLabel('Price each').fill('89.99')
  await dialog.getByLabel('Supplier').selectOption({ label: '+ New supplier…' })
  await dialog.getByLabel("New supplier's name").fill(`Marine Depot ${tag}`)
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(dialog.getByRole('link', { name: `Marine Depot ${tag}` })).toBeVisible()
  await dialog.getByRole('button', { name: 'Close' }).click()
  await page.goto('/suppliers')
  await expect(page.getByRole('link', { name: `Marine Depot ${tag}` })).toBeVisible()
  await page.goto('/contacts')
  await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible()
  await expect(page.getByRole('link', { name: `Marine Depot ${tag}` })).toHaveCount(0)

  // Archive a note from its card; restore it from Archived.
  const title = `Old notes ${tag}`
  await page.goto(project)
  await bar.getByRole('button', { name: 'Note', exact: true }).click()
  await page.getByLabel('Name of the new note').fill(title)
  await page.getByRole('button', { name: 'Create and write' }).click()
  await page.getByRole('button', { name: 'Done' }).click()
  const notes = page.getByRole('region', { name: 'Notes' })
  await notes.getByRole('button', { name: `Archive ${title}` }).click()
  await expect(notes.getByRole('link', { name: title })).toHaveCount(0)
  await notes.getByText(/^Archived \(\d+\)$/).click()
  await notes.getByRole('listitem').filter({ hasText: title }).getByRole('button', { name: 'Restore' }).click()
  await expect(notes.getByRole('button', { name: `Archive ${title}` })).toBeVisible()

  // An asset with an oil change every 100 hours or 12 months.
  await page.goto('/assets')
  await page.getByLabel('New asset').fill(`Outboard ${tag}`)
  await page.getByRole('button', { name: 'Add asset' }).click()
  const service = page.getByRole('region', { name: 'Service', exact: true })
  await service.getByRole('button', { name: '+ Reading' }).click()
  await service.getByLabel('Hours').fill('410')
  await service.getByRole('button', { name: 'Save reading' }).click()
  await expect(service.getByText('Now: 410 hours')).toBeVisible()
  await service.getByRole('button', { name: '+ Schedule' }).click()
  await service.getByLabel('What').fill('Engine oil')
  await service.getByLabel('Hours').fill('100')
  await service.getByLabel('Months').fill('12')
  await service.getByRole('button', { name: 'Save schedule' }).click()
  const oil = service.getByRole('list', { name: 'Maintenance schedules' }).getByRole('listitem').first()
  await expect(oil).toContainText('Not recorded yet')
  await oil.getByRole('button', { name: 'Mark done' }).click()
  await service.getByLabel('Hours').fill('320')
  await service.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(oil).toContainText('Due soon')
  await expect(oil).toContainText('420 hours')
  expect(problems).toEqual([])
})

// The bell, the notifications list and the notification settings (ADR 0018).
test('notifications: the bell, the list and settings', async ({ page }) => {
  const problems = watchForProblems(page)
  await page.goto('/projects')
  // A test alert makes a notification (the same as "Send a test" in Account).
  const csrf = (await (await page.request.get('/api/v1/auth/session')).json()).csrf_token
  const sent = await page.request.post('/api/v1/push/test', { headers: { 'X-CSRF-Token': csrf, Origin: new URL(page.url()).origin } })
  expect(sent.status()).toBe(204)
  await page.reload()
  const bell = page.getByRole('link', { name: /^Notifications, \d+ unread$/ })
  await expect(bell).toBeVisible()
  await bell.click()
  await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible()
  const list = page.getByRole('list', { name: 'Notifications' })
  await expect(list.getByText('Phone alerts work').first()).toBeVisible()
  await page.getByRole('button', { name: 'Mark all read' }).click()
  await expect(page.getByRole('link', { name: 'Notifications', exact: true })).toBeVisible()

  // Settings in Account: a group set to in-the-app only, and quiet hours; kept after a reload.
  await page.goto('/account')
  const card = page.getByRole('region', { name: 'Notifications settings' })
  await card.getByLabel('Tasks due today and overdue').selectOption({ label: 'In the app only' })
  await expect(card.getByLabel('Quiet hours on')).toBeEnabled() // saved
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/v1/notification-settings') && r.request().method() === 'PUT'
      && (r.request().postDataJSON() as { quiet_from: string | null }).quiet_from !== null),
    card.getByLabel('Quiet hours on').check(),
  ])
  await expect(card.getByLabel('From')).toHaveValue('22:00')
  await page.reload()
  await expect(card.getByLabel('Tasks due today and overdue')).toHaveValue('app')
  await expect(card.getByLabel('Quiet hours on')).toBeChecked()
  await card.getByLabel('Quiet hours on').uncheck()
  await expect(card.getByLabel('Tasks due today and overdue')).toBeEnabled()
  await card.getByLabel('Tasks due today and overdue').selectOption({ label: 'On the phone and in the app' })
  await expect(card.getByLabel('Tasks due today and overdue')).toHaveValue('push')
  // Security notices can't be turned off.
  await expect(card.getByLabel('Sign-ins and security changes').locator('option')).toHaveText([
    'On the phone and in the app', 'In the app only',
  ])
  expect(problems).toEqual([])
})

// Messages (ADR 0018): a one-to-one conversation with Sam (invited in the journey), deleting a
// message, a group, and hiding your online status.
test('messages', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const tag = info.project.name
  await page.goto('/messages')
  await expect(page.getByRole('heading', { name: 'Messages' })).toBeVisible()
  await page.getByRole('button', { name: 'New message' }).click()
  await page.getByRole('list', { name: 'People' }).getByRole('button', { name: /Sam/ }).click()
  await expect(page.getByRole('heading', { name: 'Sam' })).toBeVisible()

  const box = page.getByLabel('Message', { exact: true })
  await box.fill(`Can you pick up oil? (${tag})`)
  await page.getByRole('button', { name: 'Send' }).click()
  const thread = page.getByRole('region', { name: 'Messages' })
  await expect(thread.getByText(`Can you pick up oil? (${tag})`)).toBeVisible()
  await expect(box).toHaveValue('')
  await box.fill(`Wrong chat (${tag})`)
  await page.getByRole('button', { name: 'Send' }).click()
  await thread.getByRole('button', { name: `Delete message: Wrong chat (${tag})` }).click()
  await thread.getByRole('button', { name: 'Tap again to delete this message' }).click()
  await expect(thread.getByText(`Wrong chat (${tag})`)).toHaveCount(0)
  await expect(thread.getByText('Message deleted').first()).toBeVisible()

  // The conversation is listed; a group with a name.
  await page.getByRole('link', { name: '← All messages' }).click()
  await expect(page.getByRole('list', { name: 'Conversations' }).getByRole('link', { name: /Sam/ })).toBeVisible()
  await page.getByRole('button', { name: 'New group' }).click()
  await page.getByLabel('Group name').fill(`Boat crew ${tag}`)
  await page.getByRole('list', { name: 'People' }).getByLabel('Sam').check()
  await page.getByRole('button', { name: 'Start group' }).click()
  await expect(page.getByRole('heading', { name: `Boat crew ${tag}` })).toBeVisible()
  await page.getByRole('button', { name: 'Group', exact: true }).click()
  await expect(page.getByRole('list', { name: 'Members' })).toContainText('Sam')

  // Hide my online status (Account).
  await page.goto('/account')
  const hide = page.getByLabel('Hide my online status')
  await hide.check()
  await page.reload()
  await expect(hide).toBeChecked()
  await hide.uncheck()
  await expect(hide).not.toBeChecked()
  expect(problems).toEqual([])
})

// The welcome tour and "What's new" open again from Help.
test('tour and what is new from Help', async ({ page }) => {
  const problems = watchForProblems(page)
  await page.goto('/help')
  await page.getByRole('button', { name: 'Take the tour again' }).click()
  const tour = page.getByRole('dialog', { name: 'Welcome tour' })
  await expect(tour.getByRole('heading', { name: 'Welcome to PlanHaven' })).toBeVisible()
  await tour.getByRole('button', { name: 'Skip the tour' }).click()
  await expect(tour).toHaveCount(0)
  await page.getByRole('button', { name: "What's new" }).click()
  const news = page.getByRole('dialog', { name: "What's new" })
  // Every release, newest first (the newest's first item, its how-to, then the next item).
  const [first, second] = RELEASES[0].items
  await expect(news.getByRole('heading', { name: first.title, exact: true })).toBeVisible()
  if (first.steps) await expect(news.getByText(first.steps[0], { exact: true })).toBeVisible()
  if (second) {
    await news.getByRole('button', { name: 'Next' }).click()
    await expect(news.getByRole('heading', { name: second.title, exact: true })).toBeVisible()
    await news.getByRole('button', { name: 'Back' }).click()
  }
  // A set-up button takes you there.
  await news.getByRole('button', { name: 'More in Help' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(news).toHaveCount(0)
  expect(problems).toEqual([])
})

// Chores (ADR 0013): one for Sam with a photo, a weekly one for me with a note.
test('chores', async ({ page }, info) => {
  const problems = watchForProblems(page)
  const tag = info.project.name
  await page.goto('/projects')
  await page.getByRole('link', { name: 'Winterize boat' }).click()
  const bar = page.getByRole('toolbar', { name: 'Add to this project' })
  await bar.getByRole('button', { name: 'Task', exact: true }).click()
  for (const title of [`Sweep the dock ${tag}`, `Bins out ${tag}`]) {
    await page.getByLabel('Add a task').fill(title)
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(row(page, title)).toBeVisible()
  }
  await bar.getByRole('button', { name: 'Task', exact: true }).click()

  // For Sam, once, with a photo.
  await row(page, `Sweep the dock ${tag}`).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Chore', exact: true }).click()
  await dialog.getByLabel('Assign to').selectOption({ label: 'Sam' })
  await dialog.getByLabel('Proof when done').selectOption({ label: 'A photo' })
  await dialog.getByRole('button', { name: 'Save' }).click()
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(row(page, `Sweep the dock ${tag}`)).toContainText('Chore for Sam')

  // For me, weekly on Tuesdays at 7 pm, with a note.
  await row(page, `Bins out ${tag}`).click()
  dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Chore', exact: true }).click()
  await dialog.getByLabel('Assign to').selectOption({ label: 'Me' })
  await dialog.getByLabel('Due').fill('2026-10-06T19:00')
  await dialog.getByLabel('Repeats').selectOption('weekly')
  await dialog.getByLabel('Tue').check()
  await dialog.getByLabel('Proof when done').selectOption({ label: 'A short note' })
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(dialog).toContainText('Every week on Tue, with a note')
  await dialog.getByRole('button', { name: 'Close' }).click()

  // My chores: done with a note; a weekly chore moves on a week (I assigned it: no approval).
  await page.goto('/chores')
  const mine = page.getByRole('region', { name: 'My chores' })
  const card = mine.getByRole('listitem').filter({ hasText: `Bins out ${tag}` })
  await expect(card).toContainText('Every week on Tue')
  const firstDue = await card.locator('p.text-stone-500').first().textContent()
  await card.getByRole('button', { name: 'Done' }).click()
  await card.getByLabel('What did you do?').fill('Both bins at the curb')
  await card.getByRole('button', { name: 'Send' }).click()
  await expect(card.locator('p.text-stone-500').first()).not.toHaveText(firstDue!)
  expect(problems).toEqual([])
})
