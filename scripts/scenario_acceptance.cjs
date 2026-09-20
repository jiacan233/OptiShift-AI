/* Real browser + real API/LLM acceptance. Never confirms, never deletes unknown drafts. */
const { chromium, expect } = require('../frontend/node_modules/@playwright/test');
const { mkdirSync, writeFileSync } = require('node:fs');
const { createHash } = require('node:crypto');
const path = require('node:path');
const WEB = process.env.ACCEPTANCE_URL || 'http://127.0.0.1:4178';
const API = process.env.ACCEPTANCE_API || 'http://127.0.0.1:8018';
const OUT = path.resolve(process.env.ACCEPTANCE_OUTPUT || 'artifacts/scenario-fix/local-browser');
if (!WEB.startsWith('http://127.0.0.1') && process.env.ACCEPTANCE_PRODUCTION !== 'true') throw Error('Set ACCEPTANCE_PRODUCTION=true for the authorized production run');
const WEEK = '2026-10-05';
const M01 = 'E01 周一请假，帮我按最小改动重新排一下，只生成待确认方案。';
const M02 = 'E01 周一周二请假，E02 周三晚班优先，帮我重新排一下，只生成待确认方案。';
const report = { started: new Date().toISOString(), web: WEB, cases: [], cleanup: [], conversations: [], drafts: [], scenarios: [] };
mkdirSync(OUT, { recursive: true });
const save = () => writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(report, null, 2));
function signature(schedule) {
  return { schedule_id: schedule.schedule_id, version: schedule.version,
    hash: createHash('sha256').update(JSON.stringify(schedule.assignments.map(a => [a.employee_id, a.day, a.shift]).sort())).digest('hex') };
}
function conditions(patches) {
  return patches.flatMap(p => p.days.map(d => `${p.employee_id}:${d}:${p.change_type}:${p.shift ?? ''}`)).sort();
}
async function main() {
  const browser = await chromium.launch();
  const admin = await browser.newContext();
  async function get(url) { const r = await admin.request.get(API + url); expect(r.ok(), await r.text()).toBeTruthy(); return r.json(); }
  const week = () => get(`/api/schedules/week-context?week_start=${WEEK}`);
  const initial = await week();
  report.baseline = signature(initial.confirmed_schedule);
  expect(report.baseline.version).toBe(5);
  expect(initial.draft_schedule, 'Existing Draft belongs to someone else; stop safely').toBeNull();
  report.employees = (await get('/api/employees')).employees.map(e => e.id);
  expect(report.employees).toHaveLength(20);
  expect(report.employees).not.toContain('AAA');
  const versions = () => get(`/api/schedules/${report.baseline.schedule_id}/versions`);
  const beforeVersions = (await versions()).versions;
  report.baseline.versions = beforeVersions;

  async function session(name) {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    await page.addInitScript(() => {
      window.acceptanceStreams = [];
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        if (String(args[0]).endsWith('/messages/stream')) {
          const body = JSON.parse(args[1].body);
          const capture = { body, done: false };
          window.acceptanceStreams.push(capture);
          response.clone().text().then(text => { capture.text = text; capture.done = true; });
        }
        return response;
      };
    });
    const response = await page.goto(WEB, { timeout: 60000 });
    if (await page.locator('#submitBtn').count()) {
      report.domainInterstitial = { status: response.status(), title: await page.title() };
      await page.screenshot({ path: path.join(OUT, `${name}-domain.png`) });
      await expect(page.locator('#submitBtn')).toBeEnabled();
      await page.locator('#submitBtn').click();
    }
    await expect(page.getByLabel('选择排班周次')).toBeVisible();
    await page.getByLabel('选择排班周次').selectOption(WEEK);
    await page.getByRole('button', { name: '问问 AI', exact: true }).click();
    const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' });
    await expect(panel.getByRole('button', { name: '新对话', exact: true })).toBeEnabled();
    const ids = await page.evaluate(() => ({ cid: localStorage.getItem('optishift_conversation_id'), workspace: localStorage.getItem('optishift_browser_workspace_id') }));
    report.conversations.push({ ...ids, case: name }); save();
    const state = async () => get(`/api/agent/conversations/${ids.cid}/scenario?browser_workspace_id=${ids.workspace}&week_start=${WEEK}`);
    const turns = [];
    async function receive(previous) {
      await page.waitForFunction(n => window.acceptanceStreams.length > n && window.acceptanceStreams[n].done, previous, { timeout: 310000 });
      const capture = await page.evaluate(n => window.acceptanceStreams[n], previous);
      const frame = capture.text.split(/\r?\n\r?\n/).find(f => /^event: (result|error)/.test(f));
      expect(frame, 'SSE terminal frame').toBeTruthy();
      const terminal = JSON.parse(frame.split('\n').find(l => l.startsWith('data:')).slice(5));
      turns.push({ request: capture.body, terminal });
      if (terminal.schedule_result?.schedule_status === 'draft') report.drafts.push({ schedule_id: terminal.schedule_result.schedule_id, version: terminal.schedule_result.version, client_message_id: capture.body.client_message_id, conversation_id: ids.cid });
      expect(frame.startsWith('event: result'), JSON.stringify(terminal)).toBeTruthy();
      expect(capture.text).not.toMatch(/pydantic\.dev|validation error for|Traceback/);
      await expect(panel.getByRole('textbox', { name: '排班消息' })).toBeEnabled({ timeout: 30000 });
      await expect.poll(async () => signature((await week()).confirmed_schedule)).toEqual(signature(initial.confirmed_schedule));
      return terminal;
    }
    async function send(text) {
      const previous = await page.evaluate(() => window.acceptanceStreams.length);
      await panel.getByRole('textbox', { name: '排班消息' }).fill(text);
      await panel.getByRole('button', { name: '发送消息', exact: true }).click();
      return receive(previous);
    }
    async function finish() {
      writeFileSync(path.join(OUT, `${name}-turns.json`), JSON.stringify(turns, null, 2));
      await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }).catch(() => {});
      const current = await week();
      if (current.draft_schedule) {
        const owned = report.drafts.find(d => d.schedule_id === current.draft_schedule.schedule_id && d.version === current.draft_schedule.version && d.conversation_id === ids.cid);
        expect(owned, 'Only a Draft with captured schedule_id/version/client_message_id may be cleaned').toBeTruthy();
        const cancelled = await admin.request.post(API + '/api/schedule/cancel', { data: { schedule_id: owned.schedule_id, version: owned.version } });
        expect(cancelled.ok()).toBeTruthy();
        report.cleanup.push({ type: 'draft', ...owned, status: 'cancelled' });
      }
      const scenario = await state();
      report.scenarios.push({ conversation_id: ids.cid, week: WEEK, ...scenario });
      const cleared = await admin.request.delete(API + `/api/agent/conversations/${ids.cid}/scenario`, { data: { browser_workspace_id: ids.workspace, week_start: WEEK, expected_revision: scenario.scenario_revision } });
      expect(cleared.ok(), await cleared.text()).toBeTruthy();
      expect((await state()).patches).toEqual([]);
      report.cleanup.push({ type: 'scenario', conversation_id: ids.cid, week: WEEK, revision: scenario.scenario_revision, status: 'cleared' });
      await context.close(); save();
    }
    return { page, panel, ids, state, send, receive, turns, finish };
  }
  async function run(name, fn) {
    if (process.env.ACCEPTANCE_CASES && !process.env.ACCEPTANCE_CASES.split(',').includes(name)) return
    const s = await session(name);
    const entry = { case: name, conversation_id: s.ids.cid, started: new Date().toISOString() };
    try { await fn(s); entry.status = 'PASS'; }
    catch (error) { entry.status = 'FAIL'; entry.error = error.stack; }
    finally { try { await s.finish(); } catch (e) { entry.status = 'FAIL'; entry.cleanupError = e.stack; } report.cases.push(entry); console.log(name, entry.status, entry.error || entry.cleanupError || ''); save(); }
  }
  async function preview(s, text = M01) {
    const t = await s.send(text);
    expect(t.schedule_result.status).toBe('scenario_preview');
    expect(t.schedule_result.strict_feasible).toBe(false);
    expect(t.schedule_result.conflicts.length).toBeGreaterThan(0);
    expect((await week()).draft_schedule).toBeNull();
    await expect(s.page.getByTestId('dismiss-scenario')).toBeVisible();
    await expect(s.page.getByTestId('clear-scenario')).toBeVisible();
    return t;
  }
  await run('A', async s => { for (const text of ['你是谁？', '你能干嘛？', '你能重新排班吗？']) { const t = await s.send(text); expect(t.mutation_requested).toBe(false); expect(t.schedule_result).toBeNull(); } await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0); });
  await run('B', async s => { for (const [text, day] of [['周日为什么安排这么多人？', 'Sun'], ['那周六呢？', 'Sat']]) { const t = await s.send(text); expect(t.mutation_requested).toBe(false); expect(t.assistant_message.metadata_json.query_plan.day).toBe(day); expect(t.assistant_message.content).not.toMatch(/E01.{0,5}请假|E02.{0,6}晚班优先|恢复 E01|上一轮重排建议/); } await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0); });
  await run('C', async s => { const t = await preview(s); expect(t.schedule_result.suggestions.length).toBeGreaterThan(0); });
  for (let i = 1; i <= 3; i++) await run(`D${i}`, async s => { const t = await preview(s, M02); expect(conditions((await s.state()).patches)).toEqual(['E01:Mon:leave:', 'E01:Tue:leave:', 'E02:Wed:preference:evening']); expect(t.assistant_message.metadata_json.conditions).toHaveLength(3); await expect(s.panel.getByTestId('route-conditions').last()).toContainText('E02 周三晚班优先'); });
  await run('E', async s => { const t = await s.send('E01 周一请假，E02 周一请假，帮我分析怎么恢复。'); expect(t.assistant_message.content).not.toMatch(/pydantic|Traceback/); });
  await run('X1', async s => { const t = await preview(s, 'E01 周一请假，E02 周一请假，帮我试排一下，只生成待确认方案。'); const repair = t.schedule_result.suggestions.find(x => x.scenario_patch.employee_id === 'E01'); expect(repair).toBeTruthy(); await s.panel.getByText(`调整建议 · ${t.schedule_result.suggestions.length} 条`, { exact: true }).click(); const previous = await s.page.evaluate(() => window.acceptanceStreams.length); await s.panel.getByTestId(`apply-${repair.suggestion_id}`).click(); const applied = await s.receive(previous); expect(conditions((await s.state()).patches)).toEqual(['E02:Mon:leave:']); expect(applied.schedule_result.strict_feasible).toBe(repair.validation_result.strict_feasible); const actual = (await s.state()).patches.flatMap(p => p.days.map(day => ({ employee_id: p.employee_id, day, type: p.change_type, shift: p.shift }))); expect(actual).toEqual(repair.candidate_changes); });
  await run('F', async s => { await preview(s); const t = await s.send('那如果只让 E01 周一请假呢？'); expect(t.schedule_result.status).toBe('scenario_preview'); expect(conditions((await s.state()).patches)).toEqual(['E01:Mon:leave:']); });
  await run('X2', async s => { await preview(s, 'E01 周一周二请假，E02 周三晚班优先，帮我试排一下。'); const t = await s.send('把 E01 改成只周一请假，E02 周三晚班优先保持不变，再试排。'); expect(t.schedule_result.status).toBe('scenario_preview'); expect(conditions((await s.state()).patches)).toEqual(['E01:Mon:leave:', 'E02:Wed:preference:evening']); });
  await run('G', async s => {
    await preview(s); const before = await s.state(); await s.page.getByTestId('dismiss-scenario').click(); await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0); expect(await s.state()).toEqual(before);
    await s.page.reload(); await expect(s.page.getByTestId('plan-current')).toBeVisible(); await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0);
    await preview(s); await s.page.getByTestId('clear-scenario').click(); await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0); expect((await s.state()).patches).toEqual([]);
    await s.page.reload(); await expect(s.page.getByTestId('plan-current')).toBeVisible(); await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0);
    await preview(s); await s.panel.getByRole('button', { name: '新对话', exact: true }).click(); await expect(s.page.getByTestId('markdown-message')).toHaveCount(0); await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0);
    const newIds = await s.page.evaluate(() => ({ cid: localStorage.getItem('optishift_conversation_id'), workspace: localStorage.getItem('optishift_browser_workspace_id') }));
    expect(newIds.cid).not.toBe(s.ids.cid);
    report.conversations.push({ ...newIds, case: 'G-new-conversation' });
    expect((await get(`/api/agent/conversations/${newIds.cid}/scenario?browser_workspace_id=${newIds.workspace}&week_start=${WEEK}`)).patches).toEqual([]);
  });
  await run('C01', async s => { await preview(s, M02); const t = await s.send('我问一下，你这个周日为什么安排这么多人？'); expect(t.assistant_message.content).not.toMatch(/E01.{0,5}请假|E02.{0,6}晚班优先|恢复 E01|上一轮重排建议/); await expect(s.page.getByTestId('scenario-preview')).toHaveCount(0); });
  await run('H', async s => {
    let terminalDropped = false, replayTriggered = false, streamId, replayId, original;
    s.page.on('request', req => { if (req.url().endsWith('/messages') && req.method() === 'POST') { replayTriggered = true; replayId = req.postDataJSON().client_message_id; } });
    await s.page.route('**/messages/stream', async route => {
      streamId = route.request().postDataJSON().client_message_id;
      const response = await route.fetch({ timeout: 310000 }); const text = await response.text();
      const frames = text.split(/\r?\n\r?\n/); const frame = frames.find(f => f.startsWith('event: result'));
      if (frame) {
        terminalDropped = true;
        original = JSON.parse(frame.split('\n').find(l => l.startsWith('data:')).slice(5));
        const draft = original.schedule_result;
        if (draft?.schedule_status === 'draft') {
          report.drafts.push({ schedule_id: draft.schedule_id, version: draft.version, client_message_id: streamId, conversation_id: s.ids.cid });
          save();
        }
      }
      await route.fulfill({ response, body: frames.filter(f => !/^event: (result|error)/.test(f)).join('\n\n') + '\n\n' });
    });
    await s.panel.getByRole('textbox', { name: '排班消息' }).fill('E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。');
    await s.panel.getByRole('button', { name: '发送消息', exact: true }).click();
    await expect(s.page.getByTestId('plan-draft')).toBeVisible({ timeout: 310000 });
    const draft = original.schedule_result;
    const detail = await get(`/api/agent/conversations/${s.ids.cid}?browser_workspace_id=${s.ids.workspace}`);
    const newRecords = (await versions()).versions.filter(v => !beforeVersions.some(b => b.schedule_id === v.schedule_id));
    const records = newRecords.filter(v => v.status === 'draft');
    report.sse = { terminalDropped, replayTriggered, sameIdUsed: streamId === replayId, streamId, replayId,
      assistantBubbles: await s.panel.getByTestId('markdown-message').count(), draftCards: await s.page.getByTestId('plan-draft').count(),
      assistantRecords: detail.messages.filter(m => m.role === 'assistant').length, userRecords: detail.messages.filter(m => m.role === 'user').length,
      draftRecords: records.length, newVersionRecords: newRecords.length, schedule_id: draft.schedule_id, version: draft.version };
    expect(report.sse).toMatchObject({ terminalDropped: true, replayTriggered: true, sameIdUsed: true, assistantBubbles: 1, draftCards: 1, assistantRecords: 1, userRecords: 1, draftRecords: 1, newVersionRecords: 1 });
    await s.page.reload(); await expect(s.page.getByTestId('plan-draft')).toBeVisible();
  });
  const final = await week(); report.final = { ...signature(final.confirmed_schedule), draft: final.draft_schedule };
  expect(signature(final.confirmed_schedule)).toEqual(signature(initial.confirmed_schedule));
  expect(final.draft_schedule).toBeNull(); report.ended = new Date().toISOString(); save();
  await browser.close();
  if (report.cases.some(c => c.status !== 'PASS')) process.exitCode = 1;
}
main().catch(e => { report.fatal = e.stack; save(); console.error(e); process.exit(1); });
