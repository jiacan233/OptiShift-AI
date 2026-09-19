import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { observeAgentStream, readAgentStream } from './stream-helper'

const API = 'http://127.0.0.1:8001'
const WEEK = '2026-09-28'
const PANEL = 'OptiShift Copilot 智能排班助手'

async function weekContext(request: APIRequestContext) {
  const response = await request.get(`${API}/api/schedules/week-context?week_start=${WEEK}`)
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}
async function generate(request: APIRequestContext) {
  const response = await request.post(`${API}/api/schedule/generate`, { data: { week_start: WEEK, prompt: '' } })
  expect(response.ok(), await response.text()).toBeTruthy()
  const result = await response.json()
  expect(result.schedule_status).toBe('draft')
  return result
}
async function openWeek(page: Page, request: APIRequestContext) {
  const context = await weekContext(request)
  if (context.draft_schedule) {
    const cancelled = await request.post(`${API}/api/schedule/cancel`, { data: { schedule_id: context.draft_schedule.schedule_id, version: context.draft_schedule.version } })
    expect(cancelled.ok()).toBeTruthy()
  }
  if (!context.confirmed_schedule) {
    const draft = await generate(request)
    const confirmed = await request.post(`${API}/api/schedule/confirm`, { data: { schedule_id: draft.schedule_id, version: draft.version } })
    expect(confirmed.ok()).toBeTruthy()
  }
  await page.route('**/api/schedules/latest?*', async route => {
    const url = new URL(route.request().url())
    url.searchParams.set('week_start', WEEK)
    const response = await route.fetch({ url: url.toString() })
    await route.fulfill({ response })
  })
  await page.goto('/')
  await expect(page.getByLabel('选择排班周次')).toHaveValue(WEEK)
}
async function openCopilot(page: Page) {
  const panel = page.getByRole('dialog', { name: PANEL })
  if (!await panel.isVisible()) await page.getByRole('button', { name: '问问 AI' }).click()
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
  return panel
}
for (const width of [1440, 1024]) {
  test(`桌面 ${width}px：浮窗不改变工作台、Grid 或日期列宽`, async ({ page, request }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await openWeek(page, request)
    const workbench = page.locator('[data-schedule-workbench]')
    const grid = page.locator('[data-schedule-grid-container]')
    const columns = page.getByText('员工主数据 · 资质与岗位', { exact: true }).locator('..')
    const before = { workbench: await workbench.boundingBox(), grid: await grid.boundingBox(), columns: await columns.evaluate(el => getComputedStyle(el).gridTemplateColumns) }
    const panel = await openCopilot(page)
    await expect(panel).toHaveCSS('position', 'fixed')
    expect(await panel.evaluate(el => el.parentElement === document.body)).toBe(true)
    const box = (await panel.boundingBox())!
    expect(box.y).toBe(24)
    expect(width - box.x - box.width).toBe(24)
    expect(900 - box.y - box.height).toBe(24)
    expect(box.width).toBe(width >= 1280 ? 460 : 420)
    expect(await panel.evaluate(el => getComputedStyle(el).borderRadius)).toBe('24px')
    expect(Math.abs((await workbench.boundingBox())!.width - before.workbench!.width)).toBeLessThan(0.5)
    expect(Math.abs((await grid.boundingBox())!.width - before.grid!.width)).toBeLessThan(0.5)
    expect(await columns.evaluate(el => getComputedStyle(el).gridTemplateColumns)).toBe(before.columns)
    await testInfo.attach('layout-widths', { body: JSON.stringify({ before, after: { workbench: await workbench.boundingBox(), grid: await grid.boundingBox(), columns: await columns.evaluate(el => getComputedStyle(el).gridTemplateColumns) }, panel: box }, null, 2), contentType: 'application/json' })
    await page.screenshot({ path: testInfo.outputPath('desktop-copilot.png') })
    await page.getByRole('button', { name: '规则中心', exact: true }).click()
    await expect(page.getByRole('heading', { name: '规则中心', exact: true, level: 1 })).toBeVisible()
    await panel.getByRole('button', { name: '关闭 AI 助手' }).click()
    await expect(panel).toHaveCount(0)
  })
}
test('手机：Copilot 使用全屏且可正常关闭', async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openWeek(page, request)
  const panel = await openCopilot(page)
  expect(await panel.boundingBox()).toEqual({ x: 0, y: 0, width: 390, height: 844 })
  await expect(panel.getByRole('textbox', { name: '排班消息' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('mobile-copilot.png') })
  await panel.getByRole('button', { name: '关闭 AI 助手' }).click()
  await expect(panel).toHaveCount(0)
})
test('真实发送：Shift+Enter 换行、Enter 发送、执行记录与历史恢复', async ({ page, request }) => {
  await openWeek(page, request)
  const panel = await openCopilot(page)
  await observeAgentStream(page)
  const input = panel.getByRole('textbox', { name: '排班消息' })
  let count = 0
  page.on('request', req => { if (req.url().endsWith('/messages/stream')) count++ })
  await input.fill('帮我检查当前排班有没有违反规则。')
  await input.press('Shift+Enter')
  await expect(input).toHaveValue('帮我检查当前排班有没有违反规则。\n')
  expect(count).toBe(0)
  const response = page.waitForResponse(res => res.url().endsWith('/messages/stream'))
  await input.press('Enter')
  await response
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
  const stream = await readAgentStream(page)
  expect(stream.ok()).toBe(true)
  expect(count).toBe(1)
  await expect(panel.getByRole('list', { name: '执行进度' })).toBeVisible()
  const tools = panel.locator('details').filter({ has: page.locator('summary', { hasText: '工具执行记录' }) }).first()
  await tools.locator('summary').first().click()
  const payload = await stream.json()
  expect(payload.tool_calls.length).toBeGreaterThan(0)
  for (const call of payload.tool_calls) await expect(tools).toContainText(call.tool_name)
  await expect(panel.getByRole('list', { name: '执行进度' })).toContainText('校验排班规则完成')
  const id = await page.evaluate(() => localStorage.getItem('optishift_conversation_id'))
  await panel.getByRole('button', { name: '新对话' }).click()
  await expect(input).toHaveValue('')
  await expect(panel.getByText('你好，我是排班助手')).toBeVisible()
  await panel.getByRole('button', { name: '历史', exact: true }).click()
  await panel.locator(`[data-conversation-id="${id}"]`).click()
  await expect(panel.getByRole('list', { name: '执行进度' })).toBeVisible()
  await expect(panel.getByText('帮我检查当前排班有没有违反规则。', { exact: true }).last()).toBeVisible()
})
test('AI 联通检测展示服务端耗时和失败详情', async ({ page, request }) => {
  await openWeek(page, request)
  const panel = await openCopilot(page)
  let checks = 0
  await page.route('**/health/llm', async route => {
    checks++
    await route.fulfill({ json: checks === 1 ? {
      enabled: true, key_present: true, model: 'health-fixture', status: 'ok',
      checks: { basic_chat: { status: 'ok', latency_ms: 73 }, structured_output: { status: 'ok', latency_ms: 91 } },
    } : {
      enabled: true, key_present: true, model: 'health-fixture', status: 'degraded',
      checks: { basic_chat: { status: 'ok', latency_ms: 75 }, structured_output: { status: 'error', error_type: 'schema_error', message: '结构化响应不符合协议' } },
    } })
  })
  await panel.getByRole('button', { name: '检测 AI 联通状态' }).click()
  await expect(panel.getByText('AI 联通正常', { exact: true })).toBeVisible()
  await expect(panel).toContainText('73 ms')
  await expect(panel).toContainText('91 ms')
  await panel.getByRole('button', { name: '检测 AI 联通状态' }).click()
  await expect(panel).toContainText('Agent 结构化输出不可用')
  await expect(panel).toContainText('结构化响应不符合协议')
  expect(checks).toBe(2)
})
test('方案区域：预览不写入，真实 Draft Cancel / Confirm 及空候选状态', async ({ page, request }) => {
  await openWeek(page, request)
  const baseline = (await weekContext(request)).confirmed_schedule
  const first = await generate(request)
  await page.reload()
  const plans = page.getByRole('region', { name: '智能排班方案选择' })
  await expect(plans.getByRole('button', { name: '确认生效', exact: true })).toBeEnabled()
  await expect(plans).toContainText('暂无候选方案')
  await expect(plans.getByRole('button', { name: /方案 [ABC]/ })).toHaveCount(0)
  let writes = 0
  page.on('request', req => { if (req.method() === 'POST' && req.url().includes('/api/schedule/')) writes++ })
  await plans.getByRole('button', { name: /当前版/ }).click()
  await expect(plans).toContainText('当前正式版本')
  await expect(plans.getByRole('button', { name: '确认生效', exact: true })).toHaveCount(0)
  await plans.getByRole('button', { name: /草稿方案/ }).click()
  expect(writes).toBe(0)
  const cancel = page.waitForRequest(req => req.url().endsWith('/api/schedule/cancel'))
  await plans.getByRole('button', { name: '取消草稿' }).click()
  expect((await cancel).postDataJSON()).toEqual({ schedule_id: first.schedule_id, version: first.version })
  await expect(plans.getByRole('button', { name: '取消草稿' })).toHaveCount(0)
  expect((await weekContext(request)).confirmed_schedule.schedule_id).toBe(baseline.schedule_id)
  const second = await generate(request)
  await page.reload()
  await expect(plans.getByRole('button', { name: '确认生效', exact: true })).toBeEnabled()
  const confirm = page.waitForRequest(req => req.url().endsWith('/api/schedule/confirm'))
  await plans.getByRole('button', { name: '确认生效', exact: true }).click()
  expect((await confirm).postDataJSON()).toEqual({ schedule_id: second.schedule_id, version: second.version })
  await expect(plans.getByRole('button', { name: '确认生效', exact: true })).toHaveCount(0)
  const context = await weekContext(request)
  expect(context.draft_schedule).toBeNull()
  expect(context.confirmed_schedule.schedule_id).toBe(second.schedule_id)
})
