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
  await input.fill('E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。');
  const sendBtn = panel.getByRole('button', { name: '发送消息' });
  await sendBtn.click();
  await page.waitForTimeout(20000);

  const bubble = panel.locator('[data-testid="markdown-message"]').last();
  console.log('Result text:\n', await bubble.innerText());
  
  const plansText = await page.locator('#schedule-plans').innerText();
  console.log('Plans text:\n', plansText);

  // Take screenshot
  await page.screenshot({ path: path.resolve(__dirname, '../acceptance/screenshots/E02-FRIDAY-TEST.png') });

  // Cancel draft if created
  const cancelBtn = page.getByRole('button', { name: '取消草稿' });
  if (await cancelBtn.isVisible()) {
    console.log('Draft created! Cancelling...');
    await cancelBtn.click();
    await page.waitForTimeout(2000);
  }

  await browser.close();
})();
