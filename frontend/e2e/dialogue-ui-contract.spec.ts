import { expect, test } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.API_PORT ?? 8001}`
const WEEK = '2026-09-28'

// Controlled response fixtures verify UI wiring, not LLM semantics or persistence.
test('UI contract: restore condition slots, retain immutable old card identity and gate only draft actions', async ({ page, request }) => {
  const workspace = `ui-contract-${Date.now()}`
  const created = await request.post(`${API}/api/agent/conversations`, { data: { browser_workspace_id: workspace } })
  expect(created.ok()).toBeTruthy()
  const conversation = await created.json()
  const generated = await request.post(`${API}/api/schedule/generate`, { data: { week_start: WEEK, prompt: '' } })
  expect(generated.ok(), await generated.text()).toBeTruthy()
  const draft = await generated.json()
  expect(draft.status).toBe('feasible')
  const detailUrl = `${API}/api/agent/conversations/${conversation.conversation_id}`
  const detail = await (await request.get(`${detailUrl}?browser_workspace_id=${workspace}`)).json()
  const state = {
    schema_version: 1, revision: 4, scenario_revision: 2,
    conditions: [{ id: 'condition-1', source_message_id: 'user-1', changes: [{ employee_id: 'E18', day: 'Thu', shift: 'evening', type: 'assign' }] }],
    proposals: [], pending: [{ id: 'pending-1', source_message_id: 'user-2', employee_id: 'E06', type: 'assign', days: ['Fri'], shift: null }],
    conflicts: [{ code: 'test_conflict', message: 'E18 周四请假与上班条件冲突。' }], warnings: [],
  }
  const messages = ['first-set', 'second-set'].map((set, index) => ({
    message_id: `assistant-${index}`, conversation_id: conversation.conversation_id,
    role: 'assistant', content: `第 ${index + 1} 批建议`, target_week: WEEK, created_at: new Date().toISOString(),
    metadata_json: { suggestions: [{ suggestion_set_id: set, suggestion_id: `${set}-suggestion`, executable: true, display_order: 1, title: `${set} 的调整`, proposed_changes: [{ employee_id: 'E18', day: 'Thu', type: 'preference', shift: 'evening' }], target_week: WEEK }] },
  }))
  await page.addInitScript(({ workspace, id }) => {
    localStorage.setItem('optishift_browser_workspace_id', workspace)
    localStorage.setItem('optishift_conversation_id', id)
    localStorage.setItem('optishift_agent_panel_open', '1')
  }, { workspace, id: conversation.conversation_id })
  await page.route(`${detailUrl}?*`, route => route.fulfill({ json: { ...detail, messages } }))
  await page.route(`${detailUrl}/scenario?*`, route => {
    const week = new URL(route.request().url()).searchParams.get('week_start')
    return route.fulfill({ json: { scenario_revision: 2, dialogue_state: week === WEEK ? state : { ...state, conditions: [], pending: [], conflicts: [] } } })
  })
  const submissions: Array<{ trusted_action: Record<string, unknown> }> = []
  await page.route(`${detailUrl}/messages/stream`, route => {
    submissions.push(route.request().postDataJSON())
    return route.fulfill({ contentType: 'text/event-stream', body: `event: error\ndata: ${JSON.stringify({ code: 'suggestion_stale', message: '测试过期卡片', status: 409 })}\n\n` })
  })
  try {
    await page.goto('/')
    const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' })
    const summary = panel.getByTestId('dialogue-state')
    await expect(summary).toContainText('E18 周四晚班 安排上班')
    await expect(summary).toContainText('E06 周五 安排上班 · 还需补充班次')
    await expect(summary).toContainText('解决冲突后才能执行')
    await page.reload()
    await expect(summary).toContainText('E06 周五 安排上班 · 还需补充班次')
    for (const toggle of await panel.locator('summary').filter({ hasText: '调整建议' }).all()) await toggle.click()
    const oldCard = panel.locator('[data-suggestion-set-id="first-set"]')
    const newCard = panel.locator('[data-suggestion-set-id="second-set"]')
    await expect(oldCard.getByRole('button', { name: '采纳并生成草稿', exact: true })).toBeDisabled()
    await expect(newCard.getByRole('button', { name: '采纳并生成草稿', exact: true })).toBeDisabled()
    for (const [name, execution] of [['仅采纳', 'record'], ['采纳并试排', 'preview']] as const) {
      await expect(oldCard.getByRole('button', { name, exact: true })).toBeEnabled()
      await oldCard.getByRole('button', { name, exact: true }).click()
      await expect(panel.getByRole('button', { name: '新对话', exact: true })).toBeEnabled()
      expect(submissions.at(-1)?.trusted_action).toMatchObject({ suggestion_id: 'first-set-suggestion', suggestion_set_id: 'first-set', execution, target_week: WEEK })
    }
    await expect(panel.getByRole('alert')).toContainText('建议已失效')
    await page.getByLabel('选择排班周次').selectOption('2026-10-05')
    await expect(summary).toHaveCount(0)
    await page.getByLabel('选择排班周次').selectOption(WEEK)
    await expect(summary).toContainText('E06 周五 安排上班 · 还需补充班次')
  } finally {
    const cancelled = await request.post(`${API}/api/schedule/cancel`, { data: { schedule_id: draft.schedule_id, version: draft.version } })
    expect(cancelled.ok()).toBeTruthy()
  }
})
