import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { observeAgentStream, readAgentStream } from './stream-helper'

const API = 'http://127.0.0.1:8001'
const WORKSPACE = 'bw_playwright_agent_acceptance'
const WEEK_39 = '2026-09-21'
const WEEK_40 = '2026-09-28'
const WEEK_41 = '2026-10-05'

let conversationId: string | null = null
let confirmedWeek40: { schedule_id: string; version: number } | null = null

async function setBrowserIdentity(page: Page, activeConversation = conversationId) {
  await page.addInitScript(({ workspace, conversation }) => {
    localStorage.setItem('optishift_browser_workspace_id', workspace)
    if (conversation) localStorage.setItem('optishift_conversation_id', conversation)
    else localStorage.removeItem('optishift_conversation_id')
  }, { workspace: WORKSPACE, conversation: activeConversation })
}

async function openWorkbench(page: Page, weekStart?: string, activeConversation = conversationId) {
  await setBrowserIdentity(page, activeConversation)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '排班工作台' })).toBeVisible()
  await expect(page.getByLabel('选择排班周次')).toBeEnabled()
  if (weekStart) {
    await page.getByLabel('选择排班周次').selectOption(weekStart)
    await expect(page.getByLabel('选择排班周次')).toHaveValue(weekStart)
  }
}

async function openAgent(page: Page) {
  if (!await page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' }).isVisible().catch(() => false)) {
    await page.getByRole('button', { name: '问问 AI' }).click()
  }
  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' })
  await expect(panel).toBeVisible()
  await expect(panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…')).toBeEnabled()
  return panel
}

async function sendMessage(page: Page, content: string) {
  const panel = await openAgent(page)
  await observeAgentStream(page)
  const responsePromise = page.waitForResponse((response) => (
    response.url().includes('/api/agent/conversations/')
    && response.url().endsWith('/messages/stream')
    && response.request().method() === 'POST'
  ))
  await panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…').fill(content)
  await panel.getByRole('button', { name: '发送消息' }).click()
  await responsePromise
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
  return readAgentStream(page)
}

async function rememberConversation(page: Page) {
  conversationId = await page.evaluate(() => localStorage.getItem('optishift_conversation_id'))
  expect(conversationId).toMatch(/^conv_/)
  return conversationId!
}

async function seedConfirmedWeek40(request: APIRequestContext) {
  if (confirmedWeek40) return confirmedWeek40
  const generated = await request.post(`${API}/api/schedule/generate`, {
    data: { week_start: WEEK_40, prompt: 'Playwright 初始化第40周排班' },
  })
  expect(generated.ok()).toBeTruthy()
  const draft = await generated.json()
  const confirmed = await request.post(`${API}/api/schedule/confirm`, {
    data: { schedule_id: draft.schedule_id, version: draft.version },
  })
  expect(confirmed.ok()).toBeTruthy()
  confirmedWeek40 = await confirmed.json()
  return confirmedWeek40!
}

test.describe.serial('持久化排班 Agent 验收', () => {
  test('场景 1：默认周次同时显示 ISO 周和日期范围', async ({ page }) => {
    await openWorkbench(page)

    await expect(page.getByText(/^\d{4}年第\d+周$/).first()).toBeVisible()
    await expect(page.getByText(/^\d{2}月\d{2}日 - \d{2}月\d{2}日 · 未生成$/)).toBeVisible()
  })

  test('场景 2：上一周和下一周同步更新工作台、版本与 Agent 上下文', async ({ page, request }) => {
    await seedConfirmedWeek40(request)
    await openWorkbench(page, WEEK_40)
    await openAgent(page)

    await expect(page.getByRole('heading', { name: /2026年第40周 · v1/ })).toBeVisible()
    await page.getByRole('button', { name: '展开排班深度分析与版本历史' }).click()
    await expect(page.getByRole('heading', { name: '当前周版本记录' })).toBeVisible()
    await expect(page.getByText('当前上下文：2026年第40周')).toBeVisible()

    await page.getByRole('button', { name: '下一周' }).click()
    await expect(page.getByLabel('选择排班周次')).toHaveValue(WEEK_41)
    await expect(page.getByText('这一周还没有排班')).toBeVisible()
    await expect(page.getByText('当前上下文：2026年第41周')).toBeVisible()

    await page.getByRole('button', { name: '上一周' }).click()
    await expect(page.getByLabel('选择排班周次')).toHaveValue(WEEK_40)
    await expect(page.getByRole('button', { name: /^查看周[一二三四五六日](早班|晚班)详情$/ })).toHaveCount(14)
    await expect(page.getByText('版本 1 · 已确认生效')).toBeVisible()
    await expect(page.getByText('当前上下文：2026年第40周')).toBeVisible()
  })

  test('场景 3：周次选择器可直接选择第39、40、41周', async ({ page }) => {
    await openWorkbench(page, WEEK_40)
    const selector = page.getByLabel('选择排班周次')

    await expect(selector.locator(`option[value="${WEEK_39}"]`)).toContainText('第39周')
    await expect(selector.locator(`option[value="${WEEK_40}"]`)).toContainText('第40周')
    await expect(selector.locator(`option[value="${WEEK_41}"]`)).toContainText('第41周')
    await selector.selectOption(WEEK_39)
    await expect(page.getByText('2026年第39周').first()).toBeVisible()
    await selector.selectOption(WEEK_41)
    await expect(page.getByText('2026年第41周').first()).toBeVisible()
    await selector.selectOption(WEEK_40)
  })

  test('场景 4：问问 AI 打开右侧 Agent Panel', async ({ page }) => {
    await openWorkbench(page, WEEK_40)

    const panel = await openAgent(page)

    await expect(panel.getByRole('heading', { name: 'OptiShift Copilot' })).toBeVisible()
    await expect(panel).toHaveAttribute('data-agent-panel', 'open')
  })

  test('场景 5：项目说明问题得到回答且排班不变', async ({ page }) => {
    await openWorkbench(page, WEEK_40, null)
    const before = await page.getByRole('heading', { name: /2026年第40周 · v1/ }).textContent()

    const response = await sendMessage(page, '你知道我们的项目怎么排班吗？')

    expect(response.ok()).toBeTruthy()
    expect((await response.json()).intent).toBe('ask')
    await expect(page.getByText(/CP-SAT Solver/)).toBeVisible()
    await expect(page.getByRole('heading', { name: /2026年第40周 · v1/ })).toHaveText(before!)
    await rememberConversation(page)
  })

  test('场景 6：第40周优化建议只返回 Advice，不创建 Draft', async ({ page, request }) => {
    await openWorkbench(page, WEEK_40)

    const response = await sendMessage(page, '第40周有什么优化建议？')
    const payload = await response.json()

    expect(payload.intent).toBe('advice')
    expect(payload.schedule_result).toBeNull()
    await page.locator('[data-agent-panel] summary').filter({ hasText: '调整建议' }).last().click()
    await expect(page.getByText('suggestion_1')).toBeVisible()
    await expect(page.getByText('suggestion_2')).toBeVisible()
    const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${WEEK_40}`)).json()
    expect(context.draft_schedule).toBeNull()
  })

  test('场景 7：第二条为什么能解析 suggestion_2', async ({ page }) => {
    await openWorkbench(page, WEEK_40)

    const response = await sendMessage(page, '第二条为什么？')
    const payload = await response.json()

    expect(payload.intent).toBe('explain')
    expect(payload.assistant_message.metadata_json.referenced_suggestion.suggestion_id).toBe('suggestion_2')
    await expect(page.getByText(/复核工作量均衡/).last()).toBeVisible()
  })

  test('场景 8：按这个改经过 Version Guard 并生成 Replan Draft', async ({ page }) => {
    await openWorkbench(page, WEEK_40)

    const response = await sendMessage(page, '按这个改。')
    const payload = await response.json()

    expect(response.ok()).toBeTruthy()
    expect(payload.intent).toBe('replan')
    expect(payload.schedule_result.schedule_status).toBe('draft')
    expect(payload.assistant_message.metadata_json.version_guard).toBeTruthy()
    await expect(page.getByText('已生成草稿 v2')).toBeVisible()
  })

  test('场景 9：工作台展示 Draft、Diff 和 Validation', async ({ page }) => {
    await openWorkbench(page, WEEK_40)

    await expect(page.getByText('已生成草稿 v2')).toBeVisible()
    await expect(page.getByRole('region', { name: '方案对比与优劣势分析' })).toBeVisible()
    await page.getByRole('button', { name: '展开排班深度分析与版本历史' }).click()
    await expect(page.getByText('硬约束检查')).toBeVisible()
    await expect(page.getByText('10 / 10 项 全部通过')).toBeVisible()
    await expect(page.getByText('版本 2 · 待确认草稿')).toBeVisible()
  })

  test('场景 10：已有 Draft 时第二次 Mutation 返回 draft_pending', async ({ page }) => {
    await openWorkbench(page, WEEK_40)

    const response = await sendMessage(page, '第40周再帮我生成一版。')

    expect(response.status()).toBe(409)
    expect((await response.json()).error.code).toBe('draft_pending')
    await expect(page.getByText('已有待确认草稿', { exact: true })).toBeVisible()
    await expect(page.getByText('已生成草稿 v2')).toBeVisible()
  })

  test('场景 11：刷新页面恢复 Draft 与完整 Conversation', async ({ page }) => {
    await openWorkbench(page, WEEK_40)
    await openAgent(page)
    await expect(page.getByText('第40周再帮我生成一版。')).toBeVisible()

    await page.reload()

    await expect(page.getByText('已生成草稿 v2')).toBeVisible()
    await openAgent(page)
    await expect(page.getByText('你知道我们的项目怎么排班吗？', { exact: true }).last()).toBeVisible()
    await expect(page.getByText('按这个改。')).toBeVisible()
  })

  test('场景 12：历史列表保留多个 Conversation 并恢复旧对话全部消息', async ({ page }) => {
    await openWorkbench(page, WEEK_40)
    const panel = await openAgent(page)
    const oldConversation = conversationId
    await panel.getByRole('button', { name: '新对话' }).click()
    await sendMessage(page, '这是新的历史对话。')
    await rememberConversation(page)
    expect(conversationId).not.toBe(oldConversation)

    await panel.getByRole('button', { name: '历史' }).click()
    await expect(panel.getByText('今天')).toBeVisible()
    await expect(panel.getByText('你知道我们的项目怎么排班吗？', { exact: true })).toBeVisible()
    await panel.getByText('你知道我们的项目怎么排班吗？', { exact: true }).click()

    await expect(panel.getByText('第40周有什么优化建议？', { exact: true })).toBeVisible()
    await expect(panel.getByText('按这个改。', { exact: true })).toBeVisible()
    await rememberConversation(page)
    expect(conversationId).toBe(oldConversation)
  })

  test('场景 13：恢复第39周历史对话会同步 Agent Context 与工作台周次', async ({ page }) => {
    await openWorkbench(page, WEEK_40)
    let panel = await openAgent(page)
    await panel.getByRole('button', { name: '新对话' }).click()
    await sendMessage(page, '2026年第39周怎么样？')
    const week39Conversation = await rememberConversation(page)
    await expect(page.getByLabel('选择排班周次')).toHaveValue(WEEK_39)

    panel = await openAgent(page)
    await panel.getByRole('button', { name: '新对话' }).click()
    await sendMessage(page, '2026年第40周怎么样？')
    const historyLoaded = page.waitForResponse((response) => (
      response.request().method() === 'GET'
      && response.url().includes('/api/agent/conversations?')
    ))
    await panel.getByRole('button', { name: '历史' }).click()
    await historyLoaded
    await panel.locator(`[data-conversation-id="${week39Conversation}"]`).click()

    await expect(panel.getByText('当前上下文：2026年第39周')).toBeVisible()
    await expect(page.getByLabel('选择排班周次')).toHaveValue(WEEK_39)
    await rememberConversation(page)
    expect(conversationId).toBe(week39Conversation)
  })

  test('场景 14：网络重试复用 client_message_id 且不会重复生成 Draft', async ({ page, request }) => {
    await openWorkbench(page, WEEK_41)
    const panel = await openAgent(page)
    await panel.getByRole('button', { name: '新对话' }).click()
    let dropped = false
    await page.route('**/api/agent/conversations/*/messages/stream', async (route) => {
      if (!dropped) {
        dropped = true
        await route.fetch()
        await route.abort('failed')
        return
      }
      await route.continue()
    })

    await panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…').fill('第41周帮我生成一版。')
    await panel.getByRole('button', { name: '发送消息' }).click()
    await expect(panel.getByText('网络连接异常')).toBeVisible()
    await panel.getByRole('button', { name: '使用同一请求标识重试' }).click()
    await expect(page.getByText('已生成草稿 v1')).toBeVisible()
    await page.unroute('**/api/agent/conversations/*/messages/stream')

    const currentId = await rememberConversation(page)
    const detail = await (await request.get(`${API}/api/agent/conversations/${currentId}?browser_workspace_id=${WORKSPACE}`)).json()
    const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${WEEK_41}`)).json()
    expect(detail.messages).toHaveLength(2)
    expect(context.versions.filter((item: { status: string }) => item.status === 'draft')).toHaveLength(1)
  })

  test('场景 15：Generate 使用工作台当前 active week', async ({ page }) => {
    await openWorkbench(page, WEEK_41)
    await page.getByRole('button', { name: '取消草稿' }).click()
    await expect(page.getByText('这一周还没有排班')).toBeVisible()
    let sentBody: Record<string, unknown> | null = null
    const requestPromise = page.waitForRequest((request) => {
      if (!request.url().includes('/api/agent/conversations/') || !request.url().endsWith('/messages/stream')) return false
      sentBody = request.postDataJSON()
      return true
    })

    await page.getByRole('button', { name: /生成新排班/ }).click()
    await requestPromise
    await expect(page.getByText('已生成草稿 v1')).toBeVisible()

    expect(sentBody?.current_week_start).toBe(WEEK_41)
    expect((sentBody?.trusted_action as { target_week?: string }).target_week).toBe(WEEK_41)
  })

  test('场景 16：Conversation 中输入确认不能正式 Confirm Schedule', async ({ page, request }) => {
    await openWorkbench(page, WEEK_41)
    let confirmRequests = 0
    page.on('request', (requestEvent) => {
      if (requestEvent.url().endsWith('/api/schedule/confirm')) confirmRequests += 1
    })

    const response = await sendMessage(page, '确认。')
    const payload = await response.json()
    const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${WEEK_41}`)).json()

    expect(payload.intent).toBe('ask')
    expect(payload.mutation_requested).toBe(false)
    expect(confirmRequests).toBe(0)
    expect(context.confirmed_schedule).toBeNull()
    expect(context.draft_schedule.status).toBe('draft')
    await expect(page.getByText(/聊天不能直接确认排班/)).toBeVisible()
  })

  test('场景 17：历史诊断保留在聊天，刷新不恢复工作台面板', async ({ page }) => {
    await openWorkbench(page, WEEK_41)
    const conversation = await page.evaluate(() => localStorage.getItem('optishift_conversation_id'))
    expect(conversation).toMatch(/^conv_/)
    const now = new Date().toISOString()
    const infeasible = {
      status: 'infeasible',
      conflicts: [{ rule_id: 'R01', day: 'Mon', shift: 'morning', required: 1, available: 0, shortage: 1 }],
      blocking_candidates: [],
      diagnosis: null,
      message: 'No valid schedule exists.',
      generated_valid_schedule: false,
    }
    const userMessage = {
      message_id: 'mock_user_infeasible',
      conversation_id: conversation,
      role: 'user',
      content: '第41周帮我生成一版。',
      target_week: WEEK_41,
      mutation_requested: true,
      intent: 'generate',
      metadata_json: {},
      created_at: now,
    }
    const assistantMessage = {
      message_id: 'mock_assistant_infeasible',
      conversation_id: conversation,
      role: 'assistant',
      content: '**重点**\n\n- 第一项\n- 第二项\n\n# 标题\n\n`inline`\n\n```\ncode block\n```\n\n> 引用',
      target_week: WEEK_41,
      mutation_requested: true,
      intent: 'generate',
      metadata_json: { infeasible_result: infeasible },
      created_at: now,
    }
    const detail = {
      conversation: { conversation_id: conversation, title: 'mock', browser_workspace_id: WORKSPACE, status: 'active', created_at: now, updated_at: now },
      messages: [userMessage, assistantMessage],
      tool_calls: [],
    }
    await page.route(`${API}/api/agent/conversations/${conversation}/messages/stream`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: result\ndata: ' + JSON.stringify({
        user_message: userMessage,
        assistant_message: assistantMessage,
        intent: 'generate',
        mutation_requested: true,
        context: { target_week: WEEK_41, iso_year: 2026, iso_week: 41, display_schedule_id: null, display_schedule_version: null, confirmed_schedule_id: null, confirmed_schedule_version: null },
        tool_calls: [],
        schedule_result: infeasible,
      }) + '\n\n' })
    })
    await page.route(`${API}/api/agent/conversations/${conversation}**`, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
      } else {
        await route.fallback()
      }
    })

    await sendMessage(page, '第41周帮我生成一版。')
    await expect(page.getByTestId('markdown-message').locator('strong')).toHaveText('重点')
    await expect(page.getByTestId('markdown-message').locator('ul li')).toHaveCount(2)
    await expect(page.getByTestId('markdown-message').locator('h1')).toHaveText('标题')
    await expect(page.getByTestId('markdown-message').locator('code').filter({ hasText: 'inline' })).toBeVisible()
    await expect(page.getByTestId('markdown-message').locator('pre')).toContainText('code block')
    await expect(page.getByTestId('markdown-message').locator('blockquote')).toContainText('引用')
    await expect(page.getByTestId('infeasible-summary')).toBeVisible()
    await expect(page.getByText('覆盖缺口')).toBeVisible()
    await expect(page.getByText('这一周还没有排班')).not.toBeVisible()

    await page.reload()
    await expect(page.getByTestId('infeasible-summary')).toBeVisible()
    await expect(page.getByTestId('scenario-preview')).toHaveCount(0)
    await expect(page.getByText('这一周还没有排班')).not.toBeVisible()
    await page.unroute(`${API}/api/agent/conversations/${conversation}/messages/stream`)
    await page.unroute(`${API}/api/agent/conversations/${conversation}**`)
  })
})
