import { expect, test, type Page } from '@playwright/test'
import { observeAgentStream, readAgentStream } from './stream-helper'

const API = 'http://127.0.0.1:8001'
const WEEK = '2026-09-28'
const PROMPT = 'E01 周一请假，E02 周一请假，帮我试排一下，只生成待确认方案。'

test('Scenario exit clears backend state, preserves history and cannot resurrect after refresh', async ({ page, request }) => {
  await page.goto('/')
  await page.getByLabel('选择排班周次').selectOption(WEEK)
  await page.getByRole('button', { name: '问问 AI', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' })
  await expect(panel.getByRole('button', { name: '新对话', exact: true })).toBeEnabled()
  const ids = await page.evaluate(() => ({ cid: localStorage.getItem('optishift_conversation_id'), workspace: localStorage.getItem('optishift_browser_workspace_id') }))
  async function scenario() {
    const response = await request.get(`${API}/api/agent/conversations/${ids.cid}/scenario`, { params: { browser_workspace_id: ids.workspace!, week_start: WEEK } })
    expect(response.ok()).toBeTruthy()
    return response.json()
  }
  async function preview(p: Page) {
    await observeAgentStream(p)
    const response = p.waitForResponse(r => r.url().endsWith('/messages/stream'))
    await panel.getByRole('textbox', { name: '排班消息' }).fill(PROMPT)
    await panel.getByRole('button', { name: '发送消息', exact: true }).click()
    await response
    const turn = await readAgentStream(p)
    expect(turn.ok(), JSON.stringify(await turn.json())).toBeTruthy()
    expect((await turn.json()).schedule_result.status).toBe('scenario_preview')
    await expect(p.getByTestId('clear-scenario')).toBeEnabled()
  }
  await preview(page)
  const before = await scenario()
  await page.getByTestId('dismiss-scenario').click()
  await expect(page.getByTestId('scenario-preview')).toHaveCount(0)
  expect(await scenario()).toEqual(before)
  await page.reload()
  await expect(panel.getByRole('textbox', { name: '排班消息' })).toBeEnabled()
  await expect(page.getByTestId('scenario-preview')).toHaveCount(0)
  await preview(page)
  await page.getByTestId('clear-scenario').click()
  await expect(page.getByTestId('scenario-preview')).toHaveCount(0)
  expect((await scenario()).patches).toEqual([])
  await page.reload()
  await expect(panel.getByRole('textbox', { name: '排班消息' })).toBeEnabled()
  await expect(page.getByTestId('scenario-preview')).toHaveCount(0)
  await preview(page)
  await panel.getByRole('button', { name: '新对话', exact: true }).click()
  await expect(panel.getByTestId('markdown-message')).toHaveCount(0)
  await expect(page.getByTestId('scenario-preview')).toHaveCount(0)
  const cleared = await request.delete(`${API}/api/agent/conversations/${ids.cid}/scenario`, { data: { browser_workspace_id: ids.workspace, week_start: WEEK, expected_revision: (await scenario()).scenario_revision } })
  expect(cleared.ok()).toBeTruthy()
  // Restore the actual old conversation via browser storage and a full page load.
  await page.evaluate(id => localStorage.setItem('optishift_conversation_id', id!), ids.cid)
  await page.reload()
  await expect(panel.getByTestId('markdown-message').first()).toBeVisible()
  await expect(page.getByTestId('scenario-preview')).toHaveCount(0)
})
