import { expect, test } from '@playwright/test'
import { observeAgentStream, readAgentStream } from './stream-helper'

test('历史建议之后按周日查询，并只读验证移除人员，保留时间线', async ({ page, request }) => {
  const api = 'http://127.0.0.1:8001'
  const week = '2026-09-28'
  const initial = await (await request.get(`${api}/api/schedules/week-context?week_start=${week}`)).json()
  if (!initial.display_schedule) {
    const seeded = await request.post(`${api}/api/schedule/generate`, { data: { week_start: week, prompt: '' } })
    expect(seeded.ok()).toBeTruthy()
    expect((await seeded.json()).status).toBe('feasible')
  }
  await page.goto('/')
  await expect(page.getByLabel('选择排班周次')).toBeEnabled()
  await page.getByLabel('选择排班周次').selectOption(week)
  await page.getByRole('button', { name: '问问 AI' }).click()
  const panel = page.getByRole('dialog', { name: 'OptiShift AI 智能排班助手' })
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
  await observeAgentStream(page)
  async function send(text: string) {
    const response = page.waitForResponse(r => r.url().endsWith('/messages/stream'))
    await panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…').fill(text)
    await panel.getByRole('button', { name: '发送消息' }).click()
    await response
    await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
    const stream = await readAgentStream(page)
    expect(stream.ok()).toBeTruthy()
    return stream.json()
  }
  const before = await (await request.get(`${api}/api/schedules/week-context?week_start=${week}`)).json()
  const advice = await send('E01 周一请假会有什么影响，给我建议。')
  expect(advice.assistant_message.metadata_json.suggestions.length).toBeGreaterThan(0)
  const staffing = await send('周日为什么 7 个人，6 个人不是够了吗？')
  const meta = staffing.assistant_message.metadata_json
  expect(meta.query_plan.reference_mode).toBe('none')
  expect(meta.query_plan.day).toBe('Sun')
  expect(staffing.tool_calls.map((c: { tool_name: string }) => c.tool_name)).toEqual(['get_current_schedule', 'analyze_staffing'])
  expect(meta.read_analysis.status).toBe('analyzed')
  expect(meta.read_analysis.slots.map((s: { shift: string }) => s.shift)).toEqual(['morning', 'evening'])
  await expect(panel.getByText(/周日早班：实际/).last()).toBeVisible()
  const result = await send('周日早班少一个人行不行？')
  expect(result.schedule_result).toBeNull()
  expect(result.tool_calls.map((c: { tool_name: string }) => c.tool_name)).toEqual(['get_current_schedule', 'analyze_counterfactual'])
  expect(result.assistant_message.metadata_json.execution_events.some((e: { stage: string; status: string }) => e.stage === 'counterfactual' && e.status === 'completed')).toBeTruthy()
  await expect(panel.getByRole('list', { name: '执行进度' }).last()).toContainText('只读验证移除和替代方案')
  await expect(panel.getByText('当前只是分析，没有修改排班。', { exact: true }).last()).toBeVisible()
  expect(await (await request.get(`${api}/api/schedules/week-context?week_start=${week}`)).json()).toEqual(before)
  await page.reload()
  if (!await panel.isVisible()) await page.getByRole('button', { name: '问问 AI' }).click()
  await expect(panel.getByText('当前只是分析，没有修改排班。', { exact: true }).last()).toBeVisible()
})
