import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.API_PORT ?? 8001}`
const WEEK = '2026-09-21'
test.describe.configure({ mode: 'serial' })

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`${API}${path}`, { data })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function openWeek(page: Page) {
  await page.goto('/')
  await expect(page.getByLabel('选择排班周次')).toBeEnabled()
  await page.getByLabel('选择排班周次').selectOption(WEEK)
  await page.getByRole('button', { name: '查看更多分析', exact: true }).click()
}

async function confirmedWeek(request: APIRequestContext, week: string) {
  const response = await request.get(`${API}/api/schedules/week-context?week_start=${week}`)
  expect(response.ok()).toBeTruthy()
  const context = await response.json()
  if (context.confirmed_schedule) return context.confirmed_schedule
  const draft = await post(request, '/api/schedule/generate', { week_start: week })
  return post(request, '/api/schedule/confirm', { schedule_id: draft.schedule_id, version: draft.version })
}

test('following version conflict reloads the week and replaces green success with stale state', async ({ page, request }) => {
  await confirmedWeek(request, WEEK)
  const following = await confirmedWeek(request, '2026-09-28')
  const draft = await post(request, '/api/schedule/generate', { week_start: WEEK })
  await openWeek(page)
  const button = page.getByRole('button', { name: '确认生效', exact: true })
  await expect(button).toBeEnabled()
  await expect(page.getByText('10 / 10 全部通过', { exact: true }).first()).toBeVisible()

  const replacement = await post(request, '/api/schedule/replan', {
    base_schedule_id: following.schedule_id, base_version: following.version,
    changes: [], minimize_changes: true,
  })
  await post(request, '/api/schedule/confirm', { schedule_id: replacement.schedule_id, version: replacement.version })
  const confirmation = page.waitForResponse(response => response.url().endsWith('/api/schedule/confirm'))
  const reload = page.waitForResponse(response => response.url().includes('/api/schedules/week-context?'))
  await button.click()
  const rejected = await confirmation
  expect(rejected.status()).toBe(409)
  expect((await rejected.json()).error.code).toBe('following_dependency_conflict')
  const context = await (await reload).json()
  expect(context.result.validation.passed_count).toBe(10)
  expect(context.result.validation.freshness_valid).toBe(false)
  expect(context.result.validation.confirmable).toBe(false)
  await expect(button).toBeDisabled()
  await expect(page.getByText('草稿已过期 · 请重新生成', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/10\s*\/\s*10.*全部通过/)).toHaveCount(0)
  await openWeek(page)
  await expect(button).toBeDisabled()
  await expect(page.getByText(/10\s*\/\s*10.*全部通过/)).toHaveCount(0)
  await post(request, '/api/schedule/cancel', { schedule_id: draft.schedule_id, version: draft.version })
})

test('a nonconfirmable validation never renders an all-passed summary even when freshness is valid', async ({ page, request }) => {
  const draft = await post(request, '/api/schedule/generate', { week_start: WEEK })
  await page.route('**/api/schedules/week-context?*', async route => {
    const response = await route.fetch()
    const data = await response.json()
    if (data.result?.validation) {
      data.result.validation.confirmable = false
      data.result.validation.freshness_valid = true
    }
    await route.fulfill({ response, json: data })
  })
  await page.route('**/api/schedule/validate', async route => {
    const response = await route.fetch()
    const data = await response.json()
    data.validation.confirmable = false
    data.validation.freshness_valid = true
    await route.fulfill({ response, json: data })
  })
  await openWeek(page)
  await expect(page.getByRole('button', { name: '确认生效', exact: true })).toBeDisabled()
  await expect(page.getByText('草稿不可确认 · 请检查规则或重新生成', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/10\s*\/\s*10.*全部通过/)).toHaveCount(0)
  await post(request, '/api/schedule/cancel', { schedule_id: draft.schedule_id, version: draft.version })
})
