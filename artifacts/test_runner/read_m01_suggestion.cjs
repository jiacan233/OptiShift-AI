const path = require('path');
const { chromium } = require(path.resolve(__dirname, '../../frontend/node_modules/@playwright/test'));

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/');
  await page.waitForTimeout(4000);
  const btn = page.locator('#submitBtn');
  if (await btn.count() > 0) await btn.click();
  await page.waitForTimeout(3000);

  const openBtn = page.getByRole('button', { name: '问问 AI' });
  if (await openBtn.isVisible()) await openBtn.click();
  await page.waitForTimeout(1000);

  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' });
  const input = panel.getByRole('textbox', { name: '排班消息' });
  await input.fill('E01 周一请假，帮我按最小改动重新排一下，只生成待确认方案。');
  const sendBtn = panel.getByRole('button', { name: '发送消息' });
  await sendBtn.click();
  await page.waitForTimeout(16000);

  const suggestionDetails = panel.locator('details:has-text("调整建议")');
  if (await suggestionDetails.count() > 0) {
    await suggestionDetails.click();
    await page.waitForTimeout(1000);
    console.log('Suggestion content:\n', await suggestionDetails.innerText());
  }

  const scenarioBanner = page.locator('text=SCENARIO PREVIEW');
  if (await scenarioBanner.count() > 0) {
    console.log('Scenario Banner text:\n', await scenarioBanner.locator('..').innerText());
  }

  // Also read conflict diagnostics if present
  const conflictView = page.locator('#schedule-conflicts, [data-conflict-view]');
  if (await conflictView.count() > 0) {
    console.log('Conflict View text:\n', await conflictView.innerText());
  }

  await browser.close();
})();
