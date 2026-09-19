import { expect, test } from '@playwright/test'
import { observeAgentStream, readAgentStream } from './stream-helper'

const API = 'http://127.0.0.1:8001'

test('明确请假授权生成草稿、刷新、确认并保留违规账本', async ({ page, request }) => {
  const latest = await (await request.get(`${API}/api/schedules/latest?status=confirmed`)).json()
  const week = latest?.week_start ?? '2026-09-28'
  const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${week}`)).json()
  if (context.draft_schedule) {
    const cancelled = await request.post(`${API}/api/schedule/cancel`, { data: {
      schedule_id: context.draft_schedule.schedule_id, version: context.draft_schedule.version,
    } })
    expect(cancelled.ok()).toBeTruthy()
  }
  const leave = await request.patch(`${API}/api/employees/E01`, { data: { leave_days: ['Mon'] } })
  expect(leave.ok()).toBeTruthy()
  await page.goto('/')
  await expect(page.getByLabel('选择排班周次')).toBeEnabled()
  await page.getByLabel('选择排班周次').selectOption(week)
  await page.getByRole('button', { name: '问问 AI' }).click()
  const panel = page.getByRole('dialog', { name: 'OptiShift AI 智能排班助手' })
  await observeAgentStream(page)
  const responsePromise = page.waitForResponse((response) => response.url().endsWith('/messages/stream') && response.request().method() === 'POST')
  await panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…').fill('我知道 E01 周一请假，但就是让 E01 周一早班上班。')
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
  await page.reload()
  await expect(page.getByText('存在 1 项已授权规则例外', { exact: true })).toBeVisible()
  await expect(page.getByText('9 项满足 · 1 项已授权例外').first()).toBeVisible()
  await panel.getByRole('button', { name: '关闭 AI 助手', exact: true }).click()
  const slot = page.getByRole('button', { name: '查看周一早班详情' })
  await expect(slot).toContainText('E01')
  await expect(slot).toContainText('R08 已授权例外')
  await slot.click()
  const drawer = page.getByRole('complementary', { name: '班次详情' })
  await expect(drawer.getByText('E01 原本该日请假或不可用，本次按用户明确授权安排该班次。')).toBeVisible()
  await drawer.getByRole('button', { name: '关闭', exact: true }).click()
  const confirm = page.getByRole('button', { name: '确认含例外的排班' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(confirm).not.toBeVisible()
  await page.reload()
  await page.getByLabel('选择排班周次').selectOption(week)
  await expect(page.getByText('存在 1 项已授权规则例外', { exact: true })).toBeVisible()
  await expect(page.getByText('存在 1 项已接受规则例外').first()).toBeVisible()
  const stored = await (await request.get(`${API}/api/schedules/week-context?week_start=${week}`)).json()
  expect(stored.result.lifecycle_status).toBe('confirmed')
  expect(stored.result.compliance_status).toBe('authorized_violations')
  expect(stored.result.validation.passed).toBe(false)
  const employees = await (await request.get(`${API}/api/employees`)).json()
  expect(employees.employees.find((item: { id: string }) => item.id === 'E01').leave_days).toContain('Mon')
})
