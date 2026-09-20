import { expect, test, type APIRequestContext } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.API_PORT ?? 8001}`
const WEEK = '2026-09-21'
type Identity = { schedule_id: string; version: number }

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`${API}${path}`, { data })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function reoptimize(request: APIRequestContext, base: Identity) {
  return post(request, '/api/schedule/replan', {
    base_schedule_id: base.schedule_id, base_version: base.version, changes: [], minimize_changes: true,
  })
}

test.describe.serial('canonical draft confirmation', () => {
  let active: Identity

  test('real Agent/Solver draft v5 confirms over v4 with next week active, double click and reload', async ({ page, request }, testInfo) => {
    const errors: string[] = []
    page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`) })
    page.on('pageerror', error => errors.push(error.message))
    let base = await post(request, '/api/schedule/generate', { week_start: WEEK })
    for (let version = 1; version <= 4; version++) {
      if (version > 1) base = await reoptimize(request, base)
      base = await post(request, '/api/schedule/confirm', { schedule_id: base.schedule_id, version: base.version })
    }
    const next = await post(request, '/api/schedule/generate', { week_start: '2026-09-28' })
    await post(request, '/api/schedule/confirm', { schedule_id: next.schedule_id, version: next.version })
    await page.goto('/')
    await expect(page.getByLabel('选择排班周次')).toBeEnabled()
    await page.getByLabel('选择排班周次').selectOption(WEEK)
    await page.getByRole('button', { name: /生成新排班/ }).click()
    await expect(page.getByText('已生成草稿 v5', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '关闭 AI 助手', exact: true }).click()
    const draft = await (await request.get(`${API}/api/schedules/latest?status=draft&week_start=${WEEK}`)).json()
    expect(draft.version).toBe(5)
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    let calls = 0
    await page.route('**/api/schedule/confirm', async route => {
      calls++
      await gate
      await route.continue() // Delayed real request; success is never mocked.
    })
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/schedule/confirm'))
    const button = page.getByRole('button', { name: '确认生效', exact: true })
    await button.evaluate(element => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click() })
    const loading = page.getByRole('button', { name: '正在处理…', exact: true })
    await expect(loading).toBeDisabled()
    await expect(loading).toHaveAttribute('aria-busy', 'true')
    release()
    const response = await responsePromise
    expect(response.request().postDataJSON()).toEqual({ schedule_id: draft.schedule_id, version: 5, week_start: WEEK })
    expect(response.status()).toBe(200)
    const result = await response.json()
    active = { schedule_id: result.schedule_id, version: result.version }
    await expect(page.getByText('排班 v5 已确认并生效。', { exact: true })).toBeVisible()
    await expect(page.getByText('已生成草稿 v5', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: /第39周 · v5.*已确认生效/ })).toBeVisible()
    await page.reload()
    await expect(page.getByLabel('选择排班周次')).toBeEnabled()
    await page.getByLabel('选择排班周次').selectOption(WEEK)
    await expect(page.getByRole('heading', { name: /第39周 · v5.*已确认生效/ })).toBeVisible()
    await expect(page.getByRole('button', { name: '确认生效', exact: true })).toHaveCount(0)
    expect(calls).toBe(1)
    expect(errors).toEqual([])
    const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${WEEK}`)).json()
    expect(context.confirmed_schedule.schedule_id).toBe(draft.schedule_id)
    expect(context.draft_schedule).toBeNull()
    await testInfo.attach('confirm-network', { contentType: 'application/json', body: JSON.stringify({
      method: response.request().method(), url: response.url(), body: response.request().postDataJSON(),
      status: response.status(), schedule_id: result.schedule_id, version: result.version, schedule_status: result.schedule_status,
    }, null, 2) })
  })

  for (const [status, code, message] of [
    [404, 'entity_not_found', '该草稿已失效，请重新生成排班。'],
    [409, 'version_conflict', '正式排班已经更新，请刷新当前周后再试。'],
    [422, 'validation_error', '确认请求参数异常，请刷新后重试。'],
    [500, 'internal_error', '确认失败，请稍后重试。'],
  ] as const) {
    test(`UI contract: HTTP ${status} preserves draft, logs details and enables retry`, async ({ page, request }) => {
      const draft = await reoptimize(request, active)
      const logs: Promise<string>[] = []
      page.on('console', entry => {
        if (entry.type() === 'error') logs.push(Promise.all(entry.args().map(arg => arg.jsonValue())).then(args => JSON.stringify(args)))
      })
      await page.route('**/api/schedule/confirm', route => route.fulfill({
        status, json: { error: { code, message: 'test failure', details: { marker: 'confirm-detail' } } },
      }))
      try {
        await page.goto('/')
        const button = page.getByRole('button', { name: '确认生效', exact: true })
        await button.click()
        await expect(page.getByRole('alert')).toContainText(message)
        await expect(button).toBeEnabled()
        await expect(page.getByText(`已生成草稿 v${draft.version}`, { exact: true })).toBeVisible()
        await expect(page.getByText(/已确认并生效。/)).toHaveCount(0)
        expect((await Promise.all(logs)).some(line => line.includes('draft_confirmation_failed') && line.includes(String(status)) && line.includes(code) && line.includes('confirm-detail'))).toBeTruthy()
      } finally {
        await post(request, '/api/schedule/cancel', { schedule_id: draft.schedule_id, version: draft.version })
      }
    })
  }

  test('successful commit with failed canonical reload never displays success notice', async ({ page, request }) => {
    const draft = await reoptimize(request, active)
    await page.goto('/')
    await expect(page.getByRole('button', { name: '确认生效', exact: true })).toBeEnabled()
    await page.route('**/api/schedules/week-context?*', route => route.fulfill({ status: 500, json: { error: { code: 'internal_error', message: '读取失败' } } }))
    const response = page.waitForResponse(response => response.url().endsWith('/api/schedule/confirm'))
    await page.getByRole('button', { name: '确认生效', exact: true }).click()
    expect((await response).status()).toBe(200)
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText(/已确认并生效。/)).toHaveCount(0)
    await page.unroute('**/api/schedules/week-context?*')
    await page.reload()
    await expect(page.getByLabel('选择排班周次')).toBeEnabled()
    await page.getByLabel('选择排班周次').selectOption(WEEK)
    await expect(page.getByRole('heading', { name: new RegExp(`第39周 · v${draft.version}.*已确认生效`) })).toBeVisible()
  })
})
