import { expect, test } from '@playwright/test'
import { observeAgentStream, readAgentStream } from './stream-helper'

const API = 'http://127.0.0.1:8001'

test('明确请假授权生成草稿、刷新、确认并保留违规账本', async ({ page, request }) => {
  // 1. Verify 20 employees and canonical leave days in Master Data via API and Employees Page
  const empResp = await (await request.get(`${API}/api/employees`)).json()
  const employees = empResp.employees
  expect(employees).toHaveLength(20)
  expect(employees.find((e: { id: string }) => e.id === 'E01').leave_days).toContain('Wed')
  expect(employees.find((e: { id: string }) => e.id === 'E06').leave_days).toContain('Tue')
  expect(employees.find((e: { id: string }) => e.id === 'E17').leave_days).toContain('Mon')
  expect(employees.find((e: { id: string }) => e.id === 'E20').leave_days).toContain('Thu')

  await page.goto('/')
  // Navigate to Employees page
  await page.getByRole('button', { name: '员工管理' }).click()
  await expect(page.getByRole('heading', { name: '员工档案与技能中心' })).toBeVisible()
  await expect(page.getByText('20 / 20 名员工')).toBeVisible()
  await expect(page.getByText('E17')).toBeVisible()
  await expect(page.getByText('E18')).toBeVisible()
  await expect(page.getByText('E19')).toBeVisible()
  await expect(page.getByText('E20')).toBeVisible()

  // Switch back to Workbench
  await page.getByRole('button', { name: '排班工作台' }).click()
  await expect(page.getByLabel('选择排班周次')).toBeEnabled()

  const latest = await (await request.get(`${API}/api/schedules/latest?status=confirmed`)).json()
  const week = latest?.week_start ?? '2026-09-28'
  const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${week}`)).json()
  if (context.draft_schedule) {
    const cancelled = await request.post(`${API}/api/schedule/cancel`, { data: {
      schedule_id: context.draft_schedule.schedule_id, version: context.draft_schedule.version,
    } })
    expect(cancelled.ok()).toBeTruthy()
  }

  await page.getByLabel('选择排班周次').selectOption(week)

  // 2. Non-force schedule has no warning banner
  await expect(page.getByText('强制排班方案 · 非标准合规')).not.toBeVisible()

  // 3. Open Agent and request explicit force override for E01 Wed morning (canonical leave day)
  await page.getByRole('button', { name: '问问 AI' }).click()
  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' })
  await observeAgentStream(page)
  const responsePromise = page.waitForResponse((response) => response.url().endsWith('/messages/stream') && response.request().method() === 'POST')
  await panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…').fill('我知道 E01 周三请假，但就是让 E01 周三早班上班。')
  await panel.getByRole('button', { name: '发送消息' }).click()
  await responsePromise
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
  const response = await readAgentStream(page)
  expect(response.ok()).toBeTruthy()
  const result = (await response.json()).schedule_result
  expect(result.compliance_status).toBe('authorized_violations')
  expect(result.validation.passed).toBe(false)
  expect(result.validation.confirmable).toBe(true)
  expect(result.authorized_violations).toHaveLength(1)
  expect(result.authorized_violations[0].rule_id).toBe('R08')
  expect(result.authorized_violations[0].employee_id).toBe('E01')
  expect(result.authorized_violations[0].day).toBe('Wed')
  expect(result.authorized_violations[0].shift).toBe('morning')

  // Close AI panel to inspect workbench
  await panel.getByRole('button', { name: '关闭 AI 助手', exact: true }).click()

  // 4. Force R08 schedule displays warning banner with all mandatory checkpoints
  const warningBanner = page.getByText('强制排班方案 · 非标准合规')
  await expect(warningBanner).toBeVisible()
  await expect(page.getByText('非标准合规').first()).toBeVisible()
  await expect(page.getByText('R08').first()).toBeVisible()
  await expect(page.getByText('E01').first()).toBeVisible()
  await expect(page.getByText('周三').first()).toBeVisible()
  await expect(page.getByText('早班').first()).toBeVisible()
  await expect(page.getByText('该违规由用户明确授权。').first()).toBeVisible()
  await expect(page.getByText('强制方案 · 存在 1 项已授权规则冲突')).toBeVisible()

  // Verify slot details
  const slot = page.getByRole('button', { name: '查看周三早班详情' })
  await expect(slot).toContainText('E01')
  await expect(slot).toContainText('R08')
  await slot.click()
  const drawer = page.getByRole('complementary', { name: '班次详情' })
  await expect(drawer.getByText('E01 原本该日请假或不可用，本次按用户明确授权安排该班次。')).toBeVisible()
  await drawer.getByRole('button', { name: '关闭', exact: true }).click()

  // 5. Confirm button is '确认非合规强制方案'
  const confirm = page.getByRole('button', { name: '确认非合规强制方案' })
  await expect(confirm).toBeVisible()
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(confirm).not.toBeVisible()

  // 6. After reload, confirmed schedule retains Force warning banner and confirmed tag
  await page.reload()
  await page.getByLabel('选择排班周次').selectOption(week)
  await expect(page.getByText('强制排班方案 · 非标准合规')).toBeVisible()
  await expect(page.getByText('已确认 · 强制方案 · 存在 1 项已授权规则冲突').first()).toBeVisible()

  const stored = await (await request.get(`${API}/api/schedules/week-context?week_start=${week}`)).json()
  expect(stored.result.lifecycle_status).toBe('confirmed')
  expect(stored.result.compliance_status).toBe('authorized_violations')
  expect(stored.result.validation.passed).toBe(false)
  expect(stored.result.validation.authorized_violations).toHaveLength(1)
})
