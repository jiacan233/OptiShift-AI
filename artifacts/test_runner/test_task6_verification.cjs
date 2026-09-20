const path = require('path');
const { chromium } = require(path.resolve(__dirname, '../../frontend/node_modules/@playwright/test'));

(async () => {
  console.log('=== TASK 6: DOM MATCH & DB VERIFICATION ===');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

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

  // Open Copilot
  const openBtn = page.getByRole('button', { name: '问问 AI' });
  if (await openBtn.isVisible()) await openBtn.click();
  await page.waitForTimeout(1000);

  const panel = page.getByRole('dialog', { name: 'OptiShift Copilot 智能排班助手' });
  const newChatBtn = panel.getByRole('button', { name: '新对话' });
  if (await newChatBtn.isVisible()) await newChatBtn.click();
  await page.waitForTimeout(1000);

  // Send mutation request to generate a draft
  console.log('Generating draft...');
  const input = panel.getByRole('textbox', { name: '排班消息' });
  await input.fill('E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。');
  const sendBtn = panel.getByRole('button', { name: '发送消息' });
  await sendBtn.click();

  // Wait for draft to be generated and loaded into UI
  console.log('Waiting for draft generation & week loading...');
  await page.waitForFunction(() => {
    const plans = document.getElementById('schedule-plans');
    return plans && plans.innerText.includes('草稿方案') && !plans.innerText.includes('正在读取方案');
  }, { timeout: 60000 });

  console.log('Draft generated successfully! Now analyzing DOM...');

  // Inspect page.locator('text=草稿方案')
  const rawLocator = page.locator('text=草稿方案');
  const rawCount = await rawLocator.count();
  console.log('\n--- PLAYWRIGHT LOCATOR MATCHES ---');
  console.log(`page.locator('text=草稿方案').count() = ${rawCount}`);

  for (let i = 0; i < rawCount; i++) {
    const el = rawLocator.nth(i);
    const info = await el.evaluate(node => ({
      tagName: node.tagName,
      className: node.className,
      id: node.id,
      text: node.innerText.slice(0, 80),
      outerHTML: node.outerHTML.slice(0, 150)
    }));
    console.log(`Match #${i + 1}: <${info.tagName}> class="${info.className}" text="${info.text.replace(/\n/g, ' ')}"`);
  }

  // Count CandidatePlanCard components
  const cardLocator = page.locator('#schedule-plans button:has-text("草稿方案")');
  const cardCount = await cardLocator.count();
  console.log(`\nActual CandidatePlanCard buttons for draft: ${cardCount}`);

  // Count total cards in CandidatePlanSelector
  const totalCards = await page.locator('#schedule-plans .grid > button').count();
  console.log(`Total plan cards in CandidatePlanSelector: ${totalCards}`);

  // Inspect API & Database for week 2026-09-28 and 2026-10-05
  const weekContextUrl = 'https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/api/schedules/week-context?week_start=2026-09-28';
  const ctxRes = await fetch(weekContextUrl);
  const ctxData = await ctxRes.json();
  console.log('\n--- BACKEND DATABASE & API STATE ---');
  console.log('API /schedules/week-context:');
  console.log('  draft_schedule:', ctxData.draft_schedule ? {
    schedule_id: ctxData.draft_schedule.schedule_id,
    version: ctxData.draft_schedule.version,
    status: ctxData.draft_schedule.status,
    parent_schedule_id: ctxData.draft_schedule.parent_schedule_id
  } : null);
  console.log('  confirmed_schedule:', ctxData.confirmed_schedule ? {
    schedule_id: ctxData.confirmed_schedule.schedule_id,
    version: ctxData.confirmed_schedule.version,
    status: ctxData.confirmed_schedule.status
  } : null);
  console.log('  versions in lineage:', ctxData.versions ? ctxData.versions.map(v => `v${v.version} (${v.status}, id=${v.schedule_id})`) : []);

  // Cleanup draft
  const cancelBtnAfter = page.getByRole('button', { name: '取消草稿' });
  if (await cancelBtnAfter.isVisible()) {
    console.log('\nCleaning up draft...');
    await cancelBtnAfter.click();
    await page.waitForTimeout(3000);
  }

  await browser.close();
  console.log('=== TASK 6 INVESTIGATION COMPLETE ===');
})().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
