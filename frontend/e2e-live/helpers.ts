import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'

export const API = process.env.OPTISHIFT_LIVE_API_URL ?? `http://127.0.0.1:${process.env.OPTISHIFT_LIVE_API_PORT ?? '8127'}`
export const WEEK = '2026-09-28'

export async function openAgent(page: Page) {
  await page.goto('/')
  await page.getByLabel('选择排班周次').selectOption(WEEK)
  await page.getByRole('button', { name: '问问 AI', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' })
  await expect(panel.getByRole('button', { name: '新对话', exact: true })).toBeEnabled({ timeout: 60_000 })
  return panel
}

export async function send(panel: Locator, text: string) {
  const input = panel.getByRole('textbox', { name: '排班消息' })
  await expect(input).toBeEnabled({ timeout: 60_000 })
  await input.fill(text)
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(input).toBeEnabled({ timeout: 300_000 })
}

export async function identity(page: Page) {
  return page.evaluate(() => ({
    conversation: localStorage.getItem('optishift_conversation_id'),
    workspace: localStorage.getItem('optishift_browser_workspace_id'),
  }))
}

export async function scenario(request: APIRequestContext, ids: { conversation: string | null; workspace: string | null }) {
  expect(ids.conversation).toBeTruthy()
  expect(ids.workspace).toBeTruthy()
  const response = await request.get(`${API}/api/agent/conversations/${ids.conversation}/scenario`, { params: { browser_workspace_id: ids.workspace!, week_start: WEEK } })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}
