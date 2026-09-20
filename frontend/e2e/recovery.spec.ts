import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8001'
// Keep the recovery fixture on the same target week that the following
// scheduling suite seeds. The Playwright web server is shared by specs, and
// the first generated week establishes the known-empty history boundary.
const RECOVERY_WEEK = '2026-09-28'

test('真实 save_draft 后丢失 terminal，自动 SAME-ID replay 且仅有一个草稿', async ({ page, request }) => {
  await page.goto('/')
  await expect(page.getByLabel('选择排班周次')).toBeEnabled()
  await page.getByLabel('选择排班周次').selectOption(RECOVERY_WEEK)
  await expect(page.getByLabel('选择排班周次')).toHaveValue(RECOVERY_WEEK)
  const week = RECOVERY_WEEK
  const before = await (await request.get(`${API}/api/schedules/week-context?week_start=${week}`)).json()
  expect(before.draft_schedule).toBeNull()
  await page.getByRole('button', { name: '问问 AI' }).click()
  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' })
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
  let streamBody: Record<string, unknown> = {}
  let replayBody: Record<string, unknown> = {}
  let originalTurn: import('../src/types').AgentTurnResult | null = null
  let replayCount = 0
  let saved: { schedule_id: string; version: number } | null = null
  await page.route('**/api/agent/conversations/*/messages/stream', async route => {
    streamBody = route.request().postDataJSON()
    const response = await route.fetch()
    const frames = (await response.text()).split(/\r?\n\r?\n/)
    const terminal = frames.find(f => f.startsWith('event: result'))
    expect(terminal).toBeTruthy()
    originalTurn = JSON.parse(terminal!.split('\n').find(l => l.startsWith('data:'))!.slice(5))
    const events = frames.filter(f => f.startsWith('event: execution')).map(f => JSON.parse(f.split('\n')[1].slice(5)))
    expect(events.filter(e => e.stage === 'save_draft' && e.status === 'completed')).toHaveLength(1)
    const result = originalTurn!.schedule_result!
    expect(result.status).toBe('feasible')
    if (result.status === 'feasible') saved = { schedule_id: result.schedule_id, version: result.version }
    // Forward the real execution frames, deliberately drop only the terminal.
    await route.fulfill({ response, body: frames.filter(f => !f.startsWith('event: result')).join('\n\n') })
  })
  await page.route('**/api/agent/conversations/*/messages', async route => {
    replayCount++
    replayBody = route.request().postDataJSON()
    const response = await route.fetch()
    expect(await response.json()).toEqual(originalTurn)
    await route.fulfill({ response })
  })
  try {
    await panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…').fill('帮我生成本周排班，只生成待确认草稿')
    await panel.getByRole('button', { name: '发送消息' }).click()
    await expect(page.getByRole('button', { name: '取消草稿', exact: true })).toBeVisible()
    await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
    await expect(panel.getByText('网络连接异常', { exact: true })).toHaveCount(0)
    expect(replayCount).toBe(1)
    expect(replayBody).toEqual(streamBody)
    const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${week}`)).json()
    expect(context.versions.length).toBe(before.versions.length + 1)
    expect(context.versions.filter((v: { status: string }) => v.status === 'draft')).toHaveLength(1)
    expect(context.confirmed_schedule).toEqual(before.confirmed_schedule)
    const ids = await page.evaluate(() => ({ conversation: localStorage.getItem('optishift_conversation_id'), workspace: localStorage.getItem('optishift_browser_workspace_id') }))
    const detail = await (await request.get(`${API}/api/agent/conversations/${ids.conversation}?browser_workspace_id=${ids.workspace}`)).json()
    expect(detail.messages).toHaveLength(2)
  } finally {
    if (saved) expect((await request.post(`${API}/api/schedule/cancel`, { data: saved })).ok()).toBeTruthy()
  }
})

// Exercise the production browser client with controlled transport outcomes;
// these are transport regressions, not REAL LLM evaluations.
for (const mode of ['result', 'processing', 'reader_failure', 'error', 'network_error_frame', '503', 'exhausted', 'hung'] as const) {
  test(`SSE recovery boundary: ${mode}`, async ({ page }) => {
    await page.goto('/')
    const outcome = await page.evaluate(async mode => {
      const modulePath = '/src/api/client.ts'
      const { api } = await import(/* @vite-ignore */ modulePath)
      const original = window.fetch
      const calls: { url: string; body: unknown }[] = []
      const input = { browser_workspace_id: 'recovery-boundary', client_message_id: 'same-id', content: 'test' }
      const turn = { marker: 'persisted' }
      const encode = (kind: string, value: unknown) => `event: ${kind}\ndata: ${JSON.stringify(value)}\n\n`
      const problem = (code: string) => ({ code, message: code, status: 409 })
      let replay = 0
      window.fetch = async (url, options) => {
        calls.push({ url: String(url), body: JSON.parse(String(options?.body)) })
        if (String(url).endsWith('/stream')) {
          if (mode === '503') return Response.json({ error: problem('conversation_busy') }, { status: 503 })
          if (mode === 'result') return new Response(encode('result', turn))
          if (mode === 'error' || mode === 'network_error_frame') return new Response(encode('error', problem(mode === 'error' ? 'draft_pending' : 'network_error')))
          if (mode === 'reader_failure') return new Response(new ReadableStream({ start(c) { c.error(new TypeError('transport lost')) } }))
          return new Response(encode('heartbeat', {}))
        }
        replay++
        if (mode === 'hung') return new Promise<Response>((_, reject) => options?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
        if (mode === 'exhausted' || (mode === 'processing' && replay === 1)) return Response.json({ error: problem('message_processing') }, { status: 409 })
        return Response.json(turn)
      }
      const started = Date.now()
      try {
        const result = await api.agent.streamMessage('conversation', input, () => {})
        return { result, calls, code: '', elapsed: Date.now() - started, expected: input }
      } catch (error) {
        return { result: null, calls, code: (error as { problem: { code: string } }).problem.code, elapsed: Date.now() - started, expected: input }
      } finally { window.fetch = original }
    }, mode)
    const messageCalls = outcome.calls.filter(c => c.url.includes('/messages'))
    expect(messageCalls.every(c => {
      const body = c.body as typeof outcome.expected
      return body.browser_workspace_id === outcome.expected.browser_workspace_id
        && body.client_message_id === outcome.expected.client_message_id
        && body.content === outcome.expected.content
    })).toBeTruthy()
    if (['result', 'processing', 'reader_failure', '503', 'error', 'network_error_frame'].includes(mode)) {
      expect(messageCalls).toHaveLength(mode === 'result' ? 1 : mode === 'processing' ? 3 : mode === 'reader_failure' ? 2 : 1)
    }
    if (['result', 'processing', 'reader_failure'].includes(mode)) {
      expect(outcome.result).toEqual({ marker: 'persisted' })
    } else if (mode === 'exhausted' || mode === 'hung') {
      expect(outcome.code).toBe('result_pending')
      expect(outcome.elapsed).toBeLessThan(23_000)
    } else {
      expect(outcome.calls).toHaveLength(1)
      expect(outcome.code).toBe(mode === '503' ? 'conversation_busy' : mode === 'error' ? 'draft_pending' : 'network_error')
    }
  })
}
