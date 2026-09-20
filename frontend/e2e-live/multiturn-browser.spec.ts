import { expect, test } from '@playwright/test'
import { identity, openAgent, scenario, send, API, WEEK } from './helpers'

test.describe.serial('real Provider browser acceptance', () => {
  test('B: slot filling survives a browser refresh', async ({ page, request }) => {
    const panel = await openAgent(page)
    await send(panel, '我想调一个人的排班。')
    await send(panel, 'E18。')
    await send(panel, '想让他上班。')
    await send(panel, '周四。')
    await send(panel, '晚班。')
    const before = await scenario(request, await identity(page))
    expect(before.dialogue_state.conditions.some((item: { changes: Array<{ employee_id: string; day: string; shift: string; type: string }> }) => item.changes.some(change => change.employee_id === 'E18' && change.day === 'Thu' && change.shift === 'evening' && change.type === 'assign'))).toBeTruthy()
    await page.reload()
    const restored = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' })
    await expect(restored.getByTestId('dialogue-state')).toContainText('E18')
    await send(restored, '先别生成，你告诉我现在理解我要干嘛。')
    await send(restored, '再加一个条件，E06周五请假。')
    const after = await scenario(request, await identity(page))
    expect(after.dialogue_state.conditions.flatMap((item: { changes: unknown[] }) => item.changes)).toEqual(expect.arrayContaining([
      expect.objectContaining({ employee_id: 'E06', day: 'Fri', type: 'leave' }),
    ]))
  })

  test('G: date correction removes the old day without changing the employee or shift', async ({ page, request }) => {
    const panel = await openAgent(page)
    await send(panel, '我想让E19周六晚班优先。')
    await send(panel, '你先告诉我你理解的具体条件是什么。')
    await send(panel, '等等，我说错了，不是周六，是周日。')
    await send(panel, '班次还是晚班。')
    await send(panel, '另外E15周六请假。')
    const state = (await scenario(request, await identity(page))).dialogue_state
    const changes = state.conditions.flatMap((item: { changes: unknown[] }) => item.changes) as Array<Record<string, unknown>>
    expect(changes).toEqual(expect.arrayContaining([
      expect.objectContaining({ employee_id: 'E19', day: 'Sun', shift: 'evening', type: 'preference' }),
      expect.objectContaining({ employee_id: 'E15', day: 'Sat', type: 'leave' }),
    ]))
    expect(changes).not.toEqual(expect.arrayContaining([expect.objectContaining({ employee_id: 'E19', day: 'Sat' })]))
  })

  test('H: suggestion cards retain immutable batch identity', async ({ page }) => {
    const panel = await openAgent(page)
    await send(panel, '你先分析这周员工工作量有没有明显不均衡的。')
    await send(panel, '如果想让工作量公平一点，你给我一个优化方案，先不要执行。')
    await send(panel, '把你的方案拆成具体调整，一条一条告诉我。')
    const cards = panel.locator('[data-suggestion-set-id]')
    await expect(cards.first()).toBeVisible({ timeout: 60_000 })
    const firstSet = await cards.first().getAttribute('data-suggestion-set-id')
    const firstId = await cards.first().getAttribute('data-suggestion-id')
    expect(firstSet).toBeTruthy()
    expect(firstId).toBeTruthy()
    await send(panel, '再给我一批不同的公平优化方案，先不要执行。')
    await expect.poll(async () => cards.evaluateAll(items => new Set(items.map(item => item.getAttribute('data-suggestion-set-id'))).size), { timeout: 60_000 }).toBeGreaterThanOrEqual(2)
    expect(await cards.first().getAttribute('data-suggestion-set-id')).toBe(firstSet)
    expect(await cards.first().getAttribute('data-suggestion-id')).toBe(firstId)
    const oldRecord = cards.first().getByRole('button', { name: '仅采纳', exact: true })
    await oldRecord.click()
    await expect(panel.getByRole('textbox', { name: '排班消息' })).toBeEnabled({ timeout: 300_000 })
  })

  test('J: explicit remembered conditions restore from the server after reload', async ({ page, request }) => {
    const panel = await openAgent(page)
    await send(panel, '如果E03周五请假会怎样？')
    await send(panel, '再加一个条件，E18周五晚班优先。')
    await send(panel, '先不要生成，你把这两个条件记住。')
    const ids = await identity(page)
    const before = await scenario(request, ids)
    await page.reload()
    await expect(page.getByTestId('dialogue-state')).toContainText('E18')
    const after = await scenario(request, await identity(page))
    expect(after.dialogue_state.revision).toBe(before.dialogue_state.revision)
    expect(after.dialogue_state.conditions.flatMap((item: { changes: unknown[] }) => item.changes)).toEqual(expect.arrayContaining([
      expect.objectContaining({ employee_id: 'E18', day: 'Fri', shift: 'evening', type: 'preference' }),
    ]))
    await send(page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' }), '其中E03那个不要了。')
    await send(page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' }), '改成E06周三早班优先。')
    const final = await scenario(request, await identity(page))
    const changes = final.dialogue_state.conditions.flatMap((item: { changes: unknown[] }) => item.changes) as Array<Record<string, unknown>>
    expect(changes).not.toEqual(expect.arrayContaining([expect.objectContaining({ employee_id: 'E03', day: 'Fri' })]))
    expect(changes).toEqual(expect.arrayContaining([expect.objectContaining({ employee_id: 'E06', day: 'Wed', shift: 'morning', type: 'preference' })]))
  })

  test('draft gate and chat confirmation: cancel through workbench, never confirm from chat', async ({ page, request }) => {
    const panel = await openAgent(page)
    let confirmations = 0
    page.on('request', event => { if (event.url().endsWith('/api/schedule/confirm')) confirmations += 1 })
    await send(panel, '帮我生成当前周排班，只生成待确认草稿。')
    const context = await (await request.get(`${API}/api/schedules/week-context?week_start=${WEEK}`)).json()
    if (context.draft_schedule) {
      await send(panel, '确认。')
      expect(confirmations).toBe(0)
      await page.getByRole('button', { name: '关闭 AI 助手' }).click()
      await expect(page.getByRole('button', { name: '取消草稿', exact: true })).toBeVisible()
      await page.getByRole('button', { name: '取消草稿', exact: true }).click()
      expect((await (await request.get(`${API}/api/schedules/week-context?week_start=${WEEK}`)).json()).draft_schedule).toBeNull()
    }
  })
})
