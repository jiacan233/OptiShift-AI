const path = require('path');
const fs = require('fs');
const { chromium } = require(path.resolve(__dirname, '../../frontend/node_modules/@playwright/test'));

const PROD_URL = 'https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/';
const SCREENSHOTS_DIR = path.resolve(__dirname, '../acceptance/screenshots');
const RESULTS_FILE = path.resolve(__dirname, '../acceptance/test_results.json');

fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

async function initBrowser() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });
  const page = await context.newPage();

  const networkEvents = [];
  const consoleLogs = [];
  const consoleErrors = [];

  page.on('console', msg => {
    const text = msg.text();
    consoleLogs.push({ time: Date.now(), type: msg.type(), text });
    if (msg.type() === 'error') {
      consoleErrors.push(text);
    }
  });

  page.on('pageerror', err => {
    consoleErrors.push('PAGE_ERROR: ' + err.toString());
  });

  page.on('request', req => {
    if (req.url().includes('/messages/stream') || req.url().includes('/api/schedule/')) {
      networkEvents.push({ time: Date.now(), type: 'request', url: req.url(), method: req.method() });
    }
  });

  page.on('response', async res => {
    if (res.url().includes('/messages/stream') || res.url().includes('/api/schedule/')) {
      networkEvents.push({
        time: Date.now(),
        type: 'response',
        url: res.url(),
        status: res.status()
      });
    }
  });

  console.log('Navigating to', PROD_URL);
  await page.goto(PROD_URL, { waitUntil: 'load', timeout: 60000 });

  // Handle Tencent Cloud interstitial page if present
  const title = await page.title();
  if (title.includes('风险提醒') || (await page.$('#submitBtn'))) {
    console.log('Detected Tencent Cloud interstitial page. Waiting 4s for countdown...');
    await page.waitForTimeout(4000);
    const submitBtn = page.locator('#submitBtn');
    if (await submitBtn.count() > 0) {
      await submitBtn.click();
      console.log('Clicked submitBtn on interstitial page.');
      await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
    }
  }

  await page.waitForTimeout(3000);
  return { browser, context, page, networkEvents, consoleLogs, consoleErrors };
}

async function openCopilot(page) {
  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' });
  if (!(await panel.isVisible())) {
    const btn = page.getByRole('button', { name: '问问 AI' });
    if (await btn.isVisible()) {
      await btn.click();
    } else {
      await page.locator('button[aria-label="打开 AI 助手"]').click();
    }
    await page.waitForTimeout(1000);
  }
  return panel;
}

async function newConversation(page) {
  const panel = await openCopilot(page);
  const newChatBtn = panel.getByRole('button', { name: '新对话' });
  if (await newChatBtn.isVisible() && await newChatBtn.isEnabled()) {
    await newChatBtn.click();
    await page.waitForTimeout(1000);
  }
}

async function getScheduleState(page) {
  return await page.evaluate(() => {
    const plansSec = document.getElementById('schedule-plans');
    const plansText = plansSec ? plansSec.innerText : '';
    const hasDraft = plansText.includes('草稿方案') && plansText.includes('待确认');
    
    // Confirmed version
    const confirmedMatch = plansText.match(/当前版\s*v(\d+)/) || plansText.match(/当前正式生效的排班.*?v(\d+)/);
    // Draft version
    const draftMatch = plansText.match(/已生成草稿\s*v(\d+)/) || plansText.match(/草稿方案.*?v(\d+)/);

    // Look for E01 and E02 cells in workbench grid
    const e01Cells = [];
    const e02Cells = [];
    
    const rows = Array.from(document.querySelectorAll('[data-schedule-grid-container] .grid, .grid'));
    for (const r of rows) {
      const text = r.innerText || '';
      if (text.includes('E01') || text.includes('林逸')) {
        const cells = Array.from(r.querySelectorAll('.rounded-xl, [data-shift-cell], div')).map(c => c.innerText.trim()).filter(Boolean);
        e01Cells.push(...cells);
      }
      if (text.includes('E02') || text.includes('张宇')) {
        const cells = Array.from(r.querySelectorAll('.rounded-xl, [data-shift-cell], div')).map(c => c.innerText.trim()).filter(Boolean);
        e02Cells.push(...cells);
      }
    }

    return {
      plansText,
      hasDraft,
      confirmedVersion: confirmedMatch ? confirmedMatch[1] : 'unknown',
      draftVersion: draftMatch ? draftMatch[1] : null,
      e01Summary: e01Cells.slice(0, 15).join(' | '),
      e02Summary: e02Cells.slice(0, 15).join(' | ')
    };
  });
}

async function getEmployeeDayShift(page, employeeId, dayIndex) {
  // Day indices: 0 = Mon, 1 = Tue, 2 = Wed, 3 = Thu, 4 = Fri, 5 = Sat, 6 = Sun
  return await page.evaluate(({ empId, dayIdx }) => {
    // Find row containing empId
    const textNodes = Array.from(document.querySelectorAll('*'));
    let targetRow = null;
    for (const el of textNodes) {
      if ((el.innerText || '').includes(empId) && el.children.length > 5) {
        targetRow = el;
        break;
      }
    }
    // Alternatively find by employee text
    const rows = Array.from(document.querySelectorAll('[data-schedule-grid-container] > div, table tr, [data-schedule-workbench] .grid'));
    for (const r of rows) {
      if (r.innerText.includes(empId)) {
        return r.innerText;
      }
    }
    return targetRow ? targetRow.innerText : 'ROW_NOT_FOUND';
  }, { empId: employeeId, dayIdx: dayIndex });
}

async function cancelDraftIfPresent(page) {
  const cancelBtn = page.getByRole('button', { name: '取消草稿' });
  if (await cancelBtn.isVisible()) {
    console.log('Draft detected. Clicking "取消草稿"...');
    await cancelBtn.click();
    await page.waitForTimeout(3000);
    console.log('Draft cancelled.');
    return true;
  }
  return false;
}

async function sendMessage(page, prompt, onProgressScreenshotName = null) {
  const panel = await openCopilot(page);
  const input = panel.getByRole('textbox', { name: '排班消息' });
  await input.click();
  await input.fill(prompt);

  const startTime = Date.now();
  const sendBtn = panel.getByRole('button', { name: '发送消息' });

  // Start listening for response
  const responsePromise = page.waitForResponse(
    res => res.url().includes('/messages/stream'),
    { timeout: 180000 }
  ).catch(e => ({ error: e.toString() }));

  await sendBtn.click();
  console.log(`[${new Date().toLocaleTimeString()}] Sent message: "${prompt}"`);

  // Wait a moment for sending state to register
  await page.waitForTimeout(2000);

  if (onProgressScreenshotName) {
    // Capture progress screenshot while processing
    const progressPath = path.join(SCREENSHOTS_DIR, `${onProgressScreenshotName}.png`);
    await page.screenshot({ path: progressPath });
    console.log(`Captured progress screenshot: ${progressPath}`);
  }

  // Wait for stream response to finish
  const streamRes = await responsePromise;
  console.log(`Stream response received in ${Date.now() - startTime}ms. Status:`, streamRes.status ? streamRes.status() : streamRes.error);

  // Wait until sending spinner is gone and assistant message is rendered
  let waitCount = 0;
  while (waitCount < 60) {
    const isSending = await panel.locator('.animate-spin').count() > 0;
    const isProcessing = (await panel.innerText()).includes('正在处理请求');
    if (!isSending && !isProcessing) {
      break;
    }
    await page.waitForTimeout(1000);
    waitCount++;
  }
  await page.waitForTimeout(2000);

  const durationMs = Date.now() - startTime;

  // Extract last assistant message text and elements
  const assistantBubble = panel.locator('[data-testid="markdown-message"]').last();
  const assistantText = await assistantBubble.innerText().catch(() => '');
  const rawHtml = await assistantBubble.innerHTML().catch(() => '');

  // Check for raw markdown bold marks
  const hasRawMarkdownBold = assistantText.includes('**');
  const hasStrongTag = rawHtml.includes('<strong');

  // Check if agentError is present
  const errorAlert = panel.locator('[role="alert"]');
  const hasError = await errorAlert.count() > 0;
  const errorText = hasError ? await errorAlert.innerText() : null;

  return {
    prompt,
    durationMs,
    streamStatus: streamRes.status ? streamRes.status() : null,
    assistantText,
    rawHtmlSnippet: rawHtml.slice(0, 300),
    hasRawMarkdownBold,
    hasStrongTag,
    hasError,
    errorText
  };
}

module.exports = {
  initBrowser,
  openCopilot,
  newConversation,
  getScheduleState,
  getEmployeeDayShift,
  cancelDraftIfPresent,
  sendMessage,
  SCREENSHOTS_DIR,
  RESULTS_FILE
};
