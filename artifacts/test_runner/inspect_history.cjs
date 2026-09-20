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

  const historyBtn = page.getByRole('button', { name: '历史', exact: true });
  if (await historyBtn.isVisible()) {
    await historyBtn.click();
    await page.waitForTimeout(2000);
    const text = await page.locator('aside.copilot-overlay').innerText();
    console.log('History list:\n', text);
  }
  await browser.close();
})();
