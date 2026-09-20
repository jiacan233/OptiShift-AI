const path = require('path');
const fs = require('fs');
const { chromium } = require(path.resolve(__dirname, '../../frontend/node_modules/@playwright/test'));

(async () => {
  console.log('=== INVESTIGATING TASK 5: E02 FRIDAY TEST ===');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const networkTimeline = [];
  const startEpoch = Date.now();

  function logNet(type, method, url, status = null, details = null) {
    const elapsed = Date.now() - startEpoch;
    const entry = { elapsedMs: elapsed, type, method, url, status, details };
    networkTimeline.push(entry);
    console.log(`[NET +${elapsed}ms] ${type.toUpperCase()} ${method || ''} ${url} ${status || ''}`);
  }

  page.on('request', req => {
    const url = req.url();
    if (url.includes('/api/')) {
      logNet('request', req.method(), url);
    }
  });

  page.on('response', async res => {
    const url = res.url();
    if (url.includes('/api/')) {
      let details = null;
      if (url.includes('/week-context') || url.includes('/validate')) {
        try {
          const text = await res.text();
          details = text.slice(0, 300);
        } catch (_) {}
      }
      logNet('response', null, url, res.status(), details);
    }
  });

  console.log('1. Navigating to page...');
  await page.goto('https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/');
  await page.waitForTimeout(4000);
  const btn = page.locator('#submitBtn');
  if (await btn.count() > 0) {
    console.log('Clicked Tencent interstitial button.');
    await btn.click();
  }
  await page.waitForTimeout(3000);

  // Clean draft if any
  const cancelBtn = page.getByRole('button', { name: '取消草稿' });
  if (await cancelBtn.isVisible()) {
    console.log('Pre-test cleanup: cancelling existing draft...');
    await cancelBtn.click();
    await page.waitForTimeout(3000);
  }

  // Open copilot
  const openBtn = page.getByRole('button', { name: '问问 AI' });
  if (await openBtn.isVisible()) await openBtn.click();
  await page.waitForTimeout(1000);

  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' });
  const newChatBtn = panel.getByRole('button', { name: '新对话' });
  if (await newChatBtn.isVisible()) await newChatBtn.click();
  await page.waitForTimeout(1000);

  const input = panel.getByRole('textbox', { name: '排班消息' });
  await input.fill('E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。');
  
  const sendBtn = panel.getByRole('button', { name: '发送消息' });
  console.log('2. Sending E02 Friday message...');
  const sendTime = Date.now();
  await sendBtn.click();

  // We will poll every 2 seconds for 45 seconds to record the exact state changes!
  const stateSnapshots = [];
  const maxWaitMs = 45000;
  let elapsed = 0;

  while (elapsed < maxWaitMs) {
    await page.waitForTimeout(2000);
    elapsed = Date.now() - sendTime;

    const snap = await page.evaluate(() => {
      const bubble = document.querySelector('[data-testid="markdown-message"]:last-of-type');
      const bubbleText = bubble ? bubble.innerText : '';
      const isSendingSpinner = !!document.querySelector('.animate-spin');
      const plansText = document.getElementById('schedule-plans')?.innerText || '';
      const workbenchText = document.querySelector('[data-schedule-workbench]')?.innerText || '';
      
      const hasReadingPlan = plansText.includes('正在读取方案');
      const hasReadingWeek = workbenchText.includes('正在读取这一周的排班');
      const hasDraftCard = plansText.includes('草稿方案');
      const hasConfirmBtn = workbenchText.includes('确认生效');

      return {
        bubbleSnippet: bubbleText.slice(0, 100),
        hasReadingPlan,
        hasReadingWeek,
        hasDraftCard,
        hasConfirmBtn,
        isSendingSpinner
      };
    });

    snap.elapsedMs = elapsed;
    stateSnapshots.push(snap);
    console.log(`[STATE +${elapsed}ms] bubble="${snap.bubbleSnippet.replace(/\n/g, ' ')}" | readingPlan=${snap.hasReadingPlan} | readingWeek=${snap.hasReadingWeek} | draftCard=${snap.hasDraftCard} | confirmBtn=${snap.hasConfirmBtn}`);

    // Capture screenshot at ~20s to replicate original test condition!
    if (elapsed >= 20000 && elapsed < 23000 && !stateSnapshots.captured20s) {
      stateSnapshots.captured20s = true;
      await page.screenshot({ path: path.resolve(__dirname, '../acceptance/screenshots/TASK5-AT-20S.png') });
      console.log('Captured screenshot at ~20s: TASK5-AT-20S.png');
    }

    if (snap.hasDraftCard && !snap.hasReadingWeek && !snap.hasReadingPlan && elapsed > 25000) {
      console.log('Draft card confirmed rendered and loading completed!');
      break;
    }
  }

  // Wait extra 5s
  await page.waitForTimeout(5000);

  // Take final screenshot
  const finalScreenshotPath = path.resolve(__dirname, '../acceptance/screenshots/TASK5-FINAL-STATE.png');
  await page.screenshot({ path: finalScreenshotPath });
  console.log('Captured final screenshot: TASK5-FINAL-STATE.png');

  // Check final DOM and React state
  const finalDomState = await page.evaluate(() => {
    const plansText = document.getElementById('schedule-plans')?.innerText || '';
    const workbenchText = document.querySelector('[data-schedule-workbench]')?.innerText || '';
    const bubbleText = document.querySelector('[data-testid="markdown-message"]:last-of-type')?.innerText || '';
    const gridCells = Array.from(document.querySelectorAll('[data-shift-cell], .grid div')).map(el => el.innerText.trim()).filter(Boolean);

    // Try reading react fiber or inspecting UI markers
    return {
      plansText,
      workbenchSnippet: workbenchText.slice(0, 400),
      bubbleText,
      hasDraftV6: plansText.includes('v6') && plansText.includes('草稿方案'),
      hasReadingPlan: plansText.includes('正在读取方案'),
      hasReadingWeek: workbenchText.includes('正在读取这一周的排班'),
      e02Cells: gridCells.filter(c => c.includes('E02') || c.includes('张宇')).slice(0, 10),
    };
  });

  console.log('\n--- FINAL DOM STATE ---');
  console.log('hasDraftV6:', finalDomState.hasDraftV6);
  console.log('hasReadingPlan:', finalDomState.hasReadingPlan);
  console.log('hasReadingWeek:', finalDomState.hasReadingWeek);
  console.log('Plans text:\n', finalDomState.plansText);

  // Now test page refresh to verify if v6 persists
  console.log('\n--- TESTING PAGE REFRESH ---');
  await page.reload({ waitUntil: 'load' });
  await page.waitForTimeout(5000);
  const reloadScreenshotPath = path.resolve(__dirname, '../acceptance/screenshots/TASK5-AFTER-RELOAD.png');
  await page.screenshot({ path: reloadScreenshotPath });

  const afterReloadState = await page.evaluate(() => {
    const plansText = document.getElementById('schedule-plans')?.innerText || '';
    const workbenchText = document.querySelector('[data-schedule-workbench]')?.innerText || '';
    return {
      plansText,
      hasDraftV6: plansText.includes('v6') && plansText.includes('草稿方案'),
      hasReadingPlan: plansText.includes('正在读取方案'),
      hasReadingWeek: workbenchText.includes('正在读取这一周的排班'),
    };
  });

  console.log('After reload hasDraftV6:', afterReloadState.hasDraftV6);
  console.log('After reload plans text:\n', afterReloadState.plansText);

  // Cancel draft at end
  const cancelAfter = page.getByRole('button', { name: '取消草稿' });
  if (await cancelAfter.isVisible()) {
    console.log('Cleaning up draft...');
    await cancelAfter.click();
    await page.waitForTimeout(3000);
    console.log('Cleaned up draft.');
  }

  // Write timeline & summary to artifacts
  const report = {
    test: 'Task 5 Investigation',
    date: new Date().toISOString(),
    networkTimeline,
    stateSnapshots,
    finalDomState,
    afterReloadState
  };
  fs.writeFileSync(path.resolve(__dirname, '../acceptance/task5_investigation_result.json'), JSON.stringify(report, null, 2));

  await browser.close();
  console.log('=== INVESTIGATION COMPLETE ===');
})().catch(err => {
  console.error('Error during Task 5 investigation:', err);
  process.exit(1);
});
