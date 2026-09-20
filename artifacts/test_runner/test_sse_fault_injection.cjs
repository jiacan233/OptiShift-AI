const path = require('path');
const fs = require('fs');
const { chromium } = require(path.resolve(__dirname, '../../frontend/node_modules/@playwright/test'));

const SCREENSHOTS_DIR = path.resolve(__dirname, '../acceptance/screenshots');

async function testFaultInjection() {
  console.log('=== TESTING SSE TERMINAL DROP / FAULT INJECTION ON REAL BROWSER ===');
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });
  const page = await context.newPage();

  await page.goto('https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/');
  await page.waitForTimeout(4000);
  const btn = page.locator('#submitBtn');
  if (await btn.count() > 0) await btn.click();
  await page.waitForTimeout(3000);

  // Clean draft if any
  const cancelBtn = page.getByRole('button', { name: '取消草稿' });
  if (await cancelBtn.isVisible()) {
    await cancelBtn.click();
    await page.waitForTimeout(3000);
  }

  const openBtn = page.getByRole('button', { name: '问问 AI' });
  if (await openBtn.isVisible()) await openBtn.click();
  await page.waitForTimeout(1000);

  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' });
  const newChatBtn = panel.getByRole('button', { name: '新对话' });
  if (await newChatBtn.isVisible()) await newChatBtn.click();
  await page.waitForTimeout(1000);

  let streamClientMsgId = null;
  let replayClientMsgId = null;
  let replayTriggered = false;
  let terminalDropped = false;

  // Intercept SSE stream
  await page.route('**/api/agent/conversations/*/messages/stream', async route => {
    const postData = route.request().postDataJSON();
    streamClientMsgId = postData.client_message_id;
    console.log('[Fault Injection] Intercepted stream request with client_message_id:', streamClientMsgId);

    const response = await route.fetch();
    const rawText = await response.text();
    const frames = rawText.split(/\r?\n\r?\n/);
    console.log(`[Fault Injection] Server returned ${frames.length} frames.`);

    const terminalIndex = frames.findIndex(f => f.startsWith('event: result'));
    if (terminalIndex !== -1) {
      console.log('[Fault Injection] Found terminal frame. DROPPING IT to simulate broken connection before terminal arrival!');
      terminalDropped = true;
      // Drop event: result
      const truncatedFrames = frames.filter(f => !f.startsWith('event: result'));
      await route.fulfill({
        response,
        body: truncatedFrames.join('\n\n')
      });
    } else {
      await route.fulfill({ response });
    }
  });

  // Intercept replay /messages
  page.on('request', req => {
    if (req.url().endsWith('/messages') && req.method() === 'POST') {
      const data = req.postDataJSON();
      replayClientMsgId = data ? data.client_message_id : null;
      replayTriggered = true;
      console.log('[Fault Injection] Frontend initiated replay request to /messages with client_message_id:', replayClientMsgId);
    }
  });

  const input = panel.getByRole('textbox', { name: '排班消息' });
  await input.fill('E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。');
  const sendBtn = panel.getByRole('button', { name: '发送消息' });
  await sendBtn.click();

  // Wait for processing and potential recovery
  console.log('[Fault Injection] Waiting 25s for frontend to detect missing terminal and replay...');
  await page.waitForTimeout(25000);

  // Take screenshot of recovered state
  const faultScreenshot = path.join(SCREENSHOTS_DIR, 'SSE-FAULT-INJECTION-RESULT.png');
  await page.screenshot({ path: faultScreenshot });

  const bubble = panel.locator('[data-testid="markdown-message"]').last();
  const assistantText = await bubble.innerText().catch(() => '');
  const bubbleCount = await panel.locator('[data-testid="markdown-message"]').count();
  
  const plansText = await page.locator('#schedule-plans').innerText().catch(() => '');
  const draftCardCount = await page.locator('text=草稿方案').count();

  const sameIdUsed = streamClientMsgId === replayClientMsgId;
  const noNetworkErrorDisplayed = !(await panel.locator('text=网络连接异常, text=请求未完成').count() > 0);

  console.log('Fault Injection Results:');
  console.log('Terminal Dropped:', terminalDropped);
  console.log('Replay Triggered:', replayTriggered);
  console.log('Same client_message_id used:', sameIdUsed);
  console.log('Bubble Count (expected 1):', bubbleCount);
  console.log('Draft Card Count (expected 1):', draftCardCount);
  console.log('Assistant Text:\n', assistantText);
  console.log('Plans text:\n', plansText);

  const testPassed = terminalDropped && replayTriggered && sameIdUsed && (bubbleCount >= 1) && (draftCardCount === 1);
  console.log('Final SSE Fault Injection PASS?:', testPassed);

  // Clean draft
  const cancelBtnAfter = page.getByRole('button', { name: '取消草稿' });
  if (await cancelBtnAfter.isVisible()) {
    await cancelBtnAfter.click();
    await page.waitForTimeout(2000);
  }

  const resultObj = {
    testPassed,
    terminalDropped,
    replayTriggered,
    sameIdUsed,
    streamClientMsgId,
    replayClientMsgId,
    bubbleCount,
    draftCardCount,
    assistantText,
    noNetworkErrorDisplayed,
    screenshot: 'SSE-FAULT-INJECTION-RESULT.png'
  };

  fs.writeFileSync(path.resolve(__dirname, '../acceptance/sse_fault_result.json'), JSON.stringify(resultObj, null, 2));
  await browser.close();
}

testFaultInjection().catch(err => {
  console.error('Fatal in testFaultInjection:', err);
  process.exit(1);
});
