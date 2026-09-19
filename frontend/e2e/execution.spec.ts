import { expect, test } from '@playwright/test'

test('执行进度在最终结果前更新，支持分片和心跳并显示路由超时', async ({ page }) => {
  await page.addInitScript(() => {
    const original = window.fetch
    window.fetch = async (...args) => {
      if (!String(args[0]).endsWith('/messages/stream')) return original(...args)
      const input = JSON.parse(String(args[1]?.body))
      const encoder = new TextEncoder()
      let controller: ReadableStreamDefaultController<Uint8Array>
      const stream = new ReadableStream<Uint8Array>({ start(value) { controller = value } })
      const emit = (kind: string, data: unknown) => {
        const frame = encoder.encode(`event: ${kind}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`)
        controller.enqueue(frame.slice(0, 17))
        controller.enqueue(frame.slice(17))
      }
      const event = { event_id: 'started', operation_id: 'route', turn_id: 'test-turn',
        client_message_id: input.client_message_id, stage: 'agent_route', status: 'started',
        label: '理解排班请求', timestamp: new Date().toISOString(), duration_ms: null, details: {} }
      emit('execution', event)
      emit('heartbeat', {})
      Object.assign(window, {
        failExecution: () => {
          emit('execution', { ...event, event_id: 'failed', status: 'failed', duration_ms: 50021,
            details: { error_type: 'read_timeout', latency_ms: 50021 } })
          emit('error', { code: 'ai_unavailable', status: 503,
            message: 'AI Provider 等待响应超过 50 秒。',
            details: { stage: 'agent_route', error_type: 'read_timeout', latency_ms: 50021 } })
          controller.close()
        },
      })
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
  })
  await page.goto('/')
  await expect(page.getByLabel('选择排班周次')).toBeEnabled()
  await page.getByRole('button', { name: '问问 AI' }).click()
  const panel = page.getByRole('dialog', { name: 'OptiShift AI 智能排班助手' })
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
  await panel.getByPlaceholder('问排班、规则，或描述需要调整的内容…').fill('2026年第41周 E01 周一请假')
  await panel.getByRole('button', { name: '发送消息' }).click()
  const timeline = panel.getByRole('list', { name: '执行进度' })
  await expect(timeline).toBeVisible()
  await expect(timeline).toContainText('理解排班请求…')
  await expect(panel.getByRole('button', { name: '新对话' })).toBeDisabled()
  await expect(timeline.getByRole('listitem')).toHaveCount(1)
  await page.evaluate(() => (window as unknown as { failExecution(): void }).failExecution())
  await expect(timeline).toContainText('理解排班请求失败')
  await expect(timeline).toContainText('50.0 秒')
  await expect(panel).toContainText('类型：read_timeout')
  await expect(panel).toContainText('阶段：理解排班请求')
  await expect(panel.getByRole('button', { name: '新对话' })).toBeEnabled()
})
