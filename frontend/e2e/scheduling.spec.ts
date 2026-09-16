import { expect, test, type Page } from '@playwright/test'

interface ScheduleResult {
  status: string
  schedule_id?: string
  version?: number
  schedule_status?: string
  schedule?: { status: string; assignments: unknown[] }
  validation?: { passed: boolean; passed_count: number; total: number }
  diff?: {
    changed_shifts: number
    removed: Array<{ employee_id: string }>
  }
  conflicts?: unknown[]
  generated_valid_schedule?: boolean
}

const versionsPanel = (page: Page) => page.locator('section').filter({
  has: page.getByRole('heading', { name: '排班版本' }),
})

test.describe.serial('AI 智能排班完整流程', () => {
  test('正常生成会显示完整排班并通过 10/10 硬约束', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '还没有排班' })).toBeVisible()

    const generateResponsePromise = page.waitForResponse((response) => (
      response.url().endsWith('/api/schedule/generate')
      && response.request().method() === 'POST'
    ))
    await page.getByRole('button', { name: /正常生成/ }).click()
    const generateResponse = await generateResponsePromise
    expect(generateResponse.ok()).toBeTruthy()

    const result = await generateResponse.json() as ScheduleResult
    expect(result.status).toBe('feasible')
    expect(result.schedule_status).toBe('draft')
    expect(result.version).toBe(1)
    expect(result.schedule?.assignments.length).toBeGreaterThan(0)
    expect(result.validation).toMatchObject({ passed: true, passed_count: 10, total: 10 })

    await expect(page.getByText('Draft v1 等待确认', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: /· v1 draft/i })).toBeVisible()
    await expect(page.getByText('10 / 10 PASS', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /^查看 (Mon|Tue|Wed|Thu|Fri|Sat|Sun) (morning|evening) 班次详情$/ })).toHaveCount(14)

    const confirmResponsePromise = page.waitForResponse((response) => (
      response.url().endsWith('/api/schedule/confirm')
      && response.request().method() === 'POST'
    ))
    await page.getByRole('button', { name: '确认变更' }).click()
    const confirmResponse = await confirmResponsePromise
    expect(confirmResponse.ok()).toBeTruthy()

    await expect(page.getByRole('status')).toContainText('排班 v1 已确认并生效。')
    await expect(page.getByRole('heading', { name: /· v1 confirmed/i })).toBeVisible()
    await expect(versionsPanel(page).getByText('v1 · confirmed', { exact: true })).toBeVisible()
  })

  test('E02 周五请假会展示差异，确认后产生 v2 正式版本', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /· v1 confirmed/i })).toBeVisible()

    const replanResponsePromise = page.waitForResponse((response) => (
      response.url().endsWith('/api/schedule/replan')
      && response.request().method() === 'POST'
    ))
    await page.getByRole('button', { name: /E02 临时请假/ }).click()
    const replanResponse = await replanResponsePromise
    expect(replanResponse.ok()).toBeTruthy()

    const result = await replanResponse.json() as ScheduleResult
    expect(result.status).toBe('feasible')
    expect(result.schedule_status).toBe('draft')
    expect(result.version).toBe(2)
    expect(result.validation).toMatchObject({ passed: true, passed_count: 10, total: 10 })
    expect(result.diff?.changed_shifts).toBeGreaterThan(0)
    expect(result.diff?.removed.some((assignment) => assignment.employee_id === 'E02')).toBeTruthy()

    await expect(page.getByText('Draft v2 等待确认', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: /· v2 draft/i })).toBeVisible()
    await expect(page.getByText('10 / 10 PASS', { exact: true })).toBeVisible()
    const diffPanel = page.locator('section').filter({ hasText: 'Ghost Diff' })
    await expect(diffPanel).toBeVisible()
    await expect(diffPanel.getByText('E02', { exact: true }).first()).toBeVisible()
    await expect(versionsPanel(page).getByText('v2 · draft', { exact: true })).toBeVisible()
    await expect(versionsPanel(page).getByText('v1 · confirmed', { exact: true })).toBeVisible()

    const confirmResponsePromise = page.waitForResponse((response) => (
      response.url().endsWith('/api/schedule/confirm')
      && response.request().method() === 'POST'
    ))
    await page.getByRole('button', { name: '确认变更' }).click()
    const confirmResponse = await confirmResponsePromise
    expect(confirmResponse.ok()).toBeTruthy()
    const confirmed = await confirmResponse.json() as ScheduleResult
    expect(confirmed).toMatchObject({ status: 'confirmed', version: 2, schedule_status: 'confirmed' })

    await expect(page.getByRole('status')).toContainText('排班 v2 已确认并生效。')
    await expect(page.getByRole('heading', { name: /· v2 confirmed/i })).toBeVisible()
    await expect(page.getByText('Draft v2 等待确认', { exact: true })).toHaveCount(0)
    await expect(versionsPanel(page).getByText('v2 · confirmed', { exact: true })).toBeVisible()
    await expect(versionsPanel(page).getByText('v1 · confirmed', { exact: true })).toBeVisible()
  })

  test('不可行请求会展示冲突且不会生成非法草稿', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /· v2 confirmed/i })).toBeVisible()

    const infeasibleResponsePromise = page.waitForResponse((response) => (
      response.url().endsWith('/api/schedule/generate')
      && response.request().method() === 'POST'
    ))
    await page.getByRole('button', { name: /周日店长全请假/ }).click()
    const infeasibleResponse = await infeasibleResponsePromise
    expect(infeasibleResponse.ok()).toBeTruthy()

    const result = await infeasibleResponse.json() as ScheduleResult
    expect(result.status).toBe('infeasible')
    expect(result.generated_valid_schedule).toBe(false)
    expect(result.conflicts?.length).toBeGreaterThan(0)
    expect('schedule' in result).toBe(false)

    await expect(page.getByText('未生成非法排班', { exact: true })).toBeVisible()
    await expect(page.getByText(/shortage \d+/).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: /· v2 confirmed/i })).toBeVisible()
    await expect(page.getByText(/Draft v\d+ 等待确认/)).toHaveCount(0)
    await expect(page.getByRole('button', { name: '确认变更' })).toHaveCount(0)
    await expect(versionsPanel(page).getByText('v2 · confirmed', { exact: true })).toBeVisible()
  })
})
