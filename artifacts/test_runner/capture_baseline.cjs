const path = require('path');
const { chromium } = require(path.resolve(__dirname, '../../frontend/node_modules/@playwright/test'));
const fs = require('fs');

const PROD_URL = 'https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/';
const SCREENSHOTS_DIR = path.resolve(__dirname, '../acceptance/screenshots');

async function run() {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });
  const page = await context.newPage();

  const consoleLogs = [];
  const consoleErrors = [];
  page.on('console', msg => {
    const text = msg.text();
    consoleLogs.push(`[${msg.type()}] ${text}`);
    if (msg.type() === 'error') {
      consoleErrors.push(text);
    }
  });

  const pageErrors = [];
  page.on('pageerror', err => {
    pageErrors.push(err.toString());
  });

  console.log('Navigating to:', PROD_URL);
  const response = await page.goto(PROD_URL, { waitUntil: 'load', timeout: 45000 });
  console.log('Initial HTTP Status:', response.status());
  console.log('Initial Title:', await page.title());

  let interstitialBypassed = false;
  // Check if interstitial page
  const title = await page.title();
  if (title.includes('风险提醒') || (await page.$('#submitBtn'))) {
    console.log('Detected Tencent Cloud interstitial page ("风险提醒"). Waiting 4s for countdown...');
    await page.waitForTimeout(4000);
    const submitBtn = page.locator('#submitBtn');
    await submitBtn.click();
    console.log('Clicked submitBtn on interstitial page.');
    await page.waitForNavigation({ waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
    interstitialBypassed = true;
  } else {
    await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  }

  console.log('Current URL:', page.url());
  console.log('Current Title:', await page.title());

  // Wait for main elements
  await page.waitForTimeout(3000);

  // Take BASELINE-01: Main Schedule Workbench
  const baseline01Path = path.join(SCREENSHOTS_DIR, 'BASELINE-01.png');
  await page.screenshot({ path: baseline01Path, fullPage: false });
  console.log('Saved BASELINE-01 to', baseline01Path);

  // Extract page info
  const pageText = await page.innerText('body');
  
  // Extract week
  const weekSelectorValue = await page.locator('select').first().inputValue().catch(() => 'N/A');
  
  // Check drafts and versions
  const hasDraftCard = await page.locator('text=草稿方案').count() > 0;
  const draftBadge = await page.locator('text=待确认').count() > 0;
  const currentPlanBadge = await page.locator('text=当前版').count() > 0;
  
  // Check employee rows
  const employeeRows = await page.locator('[data-schedule-grid-container] .grid, table tr, [data-employee-row]').count();
  const employeesListText = await page.locator('text=员工主数据').locator('..').innerText().catch(() => '');

  // Open Copilot
  console.log('Opening AI Copilot...');
  const openCopilotBtn = page.getByRole('button', { name: '问问 AI' });
  if (await openCopilotBtn.isVisible()) {
    await openCopilotBtn.click();
  } else {
    const sidebarBotBtn = page.locator('button[aria-label="打开 AI 助手"]');
    await sidebarBotBtn.click();
  }

  await page.waitForTimeout(2000);
  const copilotDialog = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' });
  const copilotVisible = await copilotDialog.isVisible();
  console.log('Copilot dialog visible:', copilotVisible);

  // Check Copilot AI status
  const aiStatusText = await copilotDialog.innerText().catch(() => '');

  // Test "检测 AI" button in Copilot
  const checkLlmBtn = copilotDialog.getByRole('button', { name: '检测 AI 联通状态' });
  let llmCheckResult = 'Not clicked';
  if (await checkLlmBtn.isVisible()) {
    console.log('Clicking "检测 AI" button in Copilot...');
    await checkLlmBtn.click();
    await page.waitForTimeout(6000);
    const healthText = await copilotDialog.locator('[aria-live="polite"]').innerText().catch(() => 'No health text');
    llmCheckResult = healthText;
    console.log('LLM Check Result:', healthText);
  }

  // Take BASELINE-02: With Copilot Open
  const baseline02Path = path.join(SCREENSHOTS_DIR, 'BASELINE-02.png');
  await page.screenshot({ path: baseline02Path, fullPage: false });
  console.log('Saved BASELINE-02 to', baseline02Path);

  const report = {
    url: page.url(),
    title: await page.title(),
    initialHttpStatus: response.status(),
    interstitialPageEncountered: interstitialBypassed,
    selectedWeek: weekSelectorValue,
    hasDraftCard,
    draftBadge,
    currentPlanBadge,
    copilotVisible,
    llmCheckResult,
    consoleLogsCount: consoleLogs.length,
    consoleErrors,
    pageErrors,
    bodySnippet: pageText.slice(0, 1000)
  };

  fs.writeFileSync(path.join(__dirname, '../acceptance/baseline_report.json'), JSON.stringify(report, null, 2));
  console.log('Baseline investigation report saved.');

  await browser.close();
}

run().catch(err => {
  console.error('Fatal in capture_baseline:', err);
  process.exit(1);
});
