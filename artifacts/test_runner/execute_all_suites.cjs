const path = require('path');
const fs = require('fs');
const {
  initBrowser,
  openCopilot,
  newConversation,
  getScheduleState,
  getEmployeeDayShift,
  cancelDraftIfPresent,
  sendMessage,
  SCREENSHOTS_DIR,
  RESULTS_FILE
} = require('./acceptance_runner.cjs');

async function runAll() {
  console.log('=== STARTING REAL BROWSER ACCEPTANCE SUITE ===');
  const results = {
    startedAt: new Date().toISOString(),
    baseline: null,
    cases: {},
    stability: {},
    visualAudit: {},
    sseAnalysis: {}
  };

  const { browser, context, page, networkEvents, consoleLogs, consoleErrors } = await initBrowser();

  try {
    // --- STEP 1: INITIAL CLEAN BASELINE ---
    console.log('\n--- Ensuring clean baseline ---');
    await openCopilot(page);
    await cancelDraftIfPresent(page);
    const baselineState = await getScheduleState(page);
    console.log('Baseline State:', JSON.stringify(baselineState, null, 2));

    // --- STEP 2: GROUP 1 - PURE CONVERSATION ---
    console.log('\n=== GROUP 1: PURE CONVERSATION ===');

    // Case F01: 你是谁？
    console.log('\n--- Running Case F01 ---');
    await newConversation(page);
    const f01 = await sendMessage(page, '你是谁？');
    const f01State = await getScheduleState(page);
    const f01Path = path.join(SCREENSHOTS_DIR, 'F01-RESULT.png');
    await page.screenshot({ path: f01Path });

    const f01Pass = (
      !f01.hasError &&
      !f01State.hasDraft &&
      (f01.assistantText.includes('排班') || f01.assistantText.includes('OptiShift') || f01.assistantText.includes('助手')) &&
      !f01.assistantText.includes('错误')
    );
    results.cases['F01'] = {
      caseId: 'F01',
      input: '你是谁？',
      durationMs: f01.durationMs,
      pass: f01Pass,
      status: f01Pass ? 'PASS' : 'FAIL',
      hasDraft: f01State.hasDraft,
      assistantText: f01.assistantText,
      hasRawMarkdownBold: f01.hasRawMarkdownBold,
      screenshot: 'F01-RESULT.png'
    };
    console.log(`Case F01: ${results.cases['F01'].status} (${f01.durationMs}ms)`);

    // Case F02: 你能干嘛？
    console.log('\n--- Running Case F02 ---');
    await newConversation(page);
    const f02 = await sendMessage(page, '你能干嘛？');
    const f02State = await getScheduleState(page);
    const f02Path = path.join(SCREENSHOTS_DIR, 'F02-RESULT.png');
    await page.screenshot({ path: f02Path });

    const f02HasKeyCapabilities = (
      f02.assistantText.includes('排班') &&
      (f02.assistantText.includes('分析') || f02.assistantText.includes('规则') || f02.assistantText.includes('草稿') || f02.assistantText.includes('方案') || f02.assistantText.includes('调整'))
    );
    const f02Pass = !f02.hasError && !f02State.hasDraft && f02HasKeyCapabilities;
    results.cases['F02'] = {
      caseId: 'F02',
      input: '你能干嘛？',
      durationMs: f02.durationMs,
      pass: f02Pass,
      status: f02Pass ? 'PASS' : 'FAIL',
      hasDraft: f02State.hasDraft,
      assistantText: f02.assistantText,
      hasRawMarkdownBold: f02.hasRawMarkdownBold,
      screenshot: 'F02-RESULT.png'
    };
    console.log(`Case F02: ${results.cases['F02'].status} (${f02.durationMs}ms)`);

    // Case F03: 你能重新排班吗？
    console.log('\n--- Running Case F03 ---');
    await newConversation(page);
    const f03 = await sendMessage(page, '你能重新排班吗？');
    const f03State = await getScheduleState(page);
    const f03Path = path.join(SCREENSHOTS_DIR, 'F03-RESULT.png');
    await page.screenshot({ path: f03Path });

    // Must NOT automatically create a draft, should ask for specific requirements
    const f03Pass = !f03.hasError && !f03State.hasDraft && (f03.assistantText.includes('可以') || f03.assistantText.includes('提供') || f03.assistantText.includes('请假') || f03.assistantText.includes('要求'));
    results.cases['F03'] = {
      caseId: 'F03',
      input: '你能重新排班吗？',
      durationMs: f03.durationMs,
      pass: f03Pass,
      status: f03Pass ? 'PASS' : 'FAIL',
      hasDraft: f03State.hasDraft,
      assistantText: f03.assistantText,
      hasRawMarkdownBold: f03.hasRawMarkdownBold,
      screenshot: 'F03-RESULT.png'
    };
    console.log(`Case F03: ${results.cases['F03'].status} (${f03.durationMs}ms)`);

    // --- STEP 3: GROUP 2 - READ-ONLY Q&A ---
    console.log('\n=== GROUP 2: READ-ONLY Q&A ===');

    // Case R01: 周日为什么安排这么多人？
    console.log('\n--- Running Case R01 ---');
    await newConversation(page);
    const r01 = await sendMessage(page, '周日为什么安排这么多人？');
    const r01State = await getScheduleState(page);
    const r01Path = path.join(SCREENSHOTS_DIR, 'R01-RESULT.png');
    await page.screenshot({ path: r01Path });

    const r01AnswersSunday = (
      r01.assistantText.includes('周日') ||
      r01.assistantText.includes('客流') ||
      r01.assistantText.includes('人') ||
      r01.assistantText.includes('班次') ||
      r01.assistantText.includes('周末')
    );
    const r01Pass = !r01.hasError && !r01State.hasDraft && r01AnswersSunday;
    results.cases['R01'] = {
      caseId: 'R01',
      input: '周日为什么安排这么多人？',
      durationMs: r01.durationMs,
      pass: r01Pass,
      status: r01Pass ? 'PASS' : 'FAIL',
      hasDraft: r01State.hasDraft,
      assistantText: r01.assistantText,
      hasRawMarkdownBold: r01.hasRawMarkdownBold,
      screenshot: 'R01-RESULT.png'
    };
    console.log(`Case R01: ${results.cases['R01'].status} (${r01.durationMs}ms)`);

    // Case R02: 那周六呢？ (Follow up in SAME conversation!)
    console.log('\n--- Running Case R02 ---');
    const r02 = await sendMessage(page, '那周六呢？');
    const r02State = await getScheduleState(page);
    const r02Path = path.join(SCREENSHOTS_DIR, 'R02-RESULT.png');
    await page.screenshot({ path: r02Path });

    const r02AnswersSaturday = (
      r02.assistantText.includes('周六') ||
      r02.assistantText.includes('六') ||
      r02.assistantText.includes('周末')
    );
    const r02Pass = !r02.hasError && !r02State.hasDraft && r02AnswersSaturday && !r02.assistantText.includes('请假');
    results.cases['R02'] = {
      caseId: 'R02',
      input: '那周六呢？',
      durationMs: r02.durationMs,
      pass: r02Pass,
      status: r02Pass ? 'PASS' : 'FAIL',
      hasDraft: r02State.hasDraft,
      assistantText: r02.assistantText,
      hasRawMarkdownBold: r02.hasRawMarkdownBold,
      screenshot: 'R02-RESULT.png'
    };
    console.log(`Case R02: ${results.cases['R02'].status} (${r02.durationMs}ms)`);

    // --- STEP 4: GROUP 3 - SINGLE CONDITION MUTATION ---
    console.log('\n=== GROUP 3: SINGLE CONDITION MUTATION ===');

    // Ensure clean baseline before M01
    await cancelDraftIfPresent(page);
    await newConversation(page);

    const m01BeforePath = path.join(SCREENSHOTS_DIR, 'M01-BEFORE.png');
    await page.screenshot({ path: m01BeforePath });

    const m01Prompt = 'E01 周一请假，帮我按最小改动重新排一下，只生成待确认方案。';
    console.log('\n--- Running Case M01 ---');
    const m01 = await sendMessage(page, m01Prompt, 'M01-PROGRESS');
    const m01State = await getScheduleState(page);
    const m01AfterPath = path.join(SCREENSHOTS_DIR, 'M01-AFTER.png');
    await page.screenshot({ path: m01AfterPath });

    const m01E01Shift = await getEmployeeDayShift(page, 'E01', 0);
    console.log('M01 E01 Row Content:', m01E01Shift);

    const m01HasDraft = m01State.hasDraft;
    const m01DraftNotConfirmed = m01State.confirmedVersion !== m01State.draftVersion;
    // Check if E01 Monday has leave / off / not working
    const m01E01MonOff = (
      m01E01Shift.includes('请假') ||
      m01E01Shift.includes('Off') ||
      m01E01Shift.includes('off') ||
      m01.assistantText.includes('请假')
    );

    const m01Pass = !m01.hasError && m01HasDraft && m01DraftNotConfirmed && m01E01MonOff;
    results.cases['M01'] = {
      caseId: 'M01',
      input: m01Prompt,
      durationMs: m01.durationMs,
      pass: m01Pass,
      status: m01Pass ? 'PASS' : 'FAIL',
      hasDraft: m01State.hasDraft,
      draftVersion: m01State.draftVersion,
      confirmedVersion: m01State.confirmedVersion,
      e01RowSummary: m01E01Shift.slice(0, 200),
      assistantText: m01.assistantText,
      hasRawMarkdownBold: m01.hasRawMarkdownBold,
      screenshots: ['M01-BEFORE.png', 'M01-PROGRESS.png', 'M01-AFTER.png']
    };
    console.log(`Case M01: ${results.cases['M01'].status} (${m01.durationMs}ms, draft v${m01State.draftVersion})`);

    // Clean up draft after M01
    await cancelDraftIfPresent(page);

    // --- STEP 5: GROUP 4 - MULTI-CONDITION MUTATION (M02) & GROUP 5 CROSSTALK ---
    console.log('\n=== GROUP 4 & 5: MULTI-CONDITION MUTATION (M02) & CROSSTALK ===');

    const m02Runs = [];
    const crosstalkRuns = [];

    for (let runIdx = 1; runIdx <= 3; runIdx++) {
      console.log(`\n--- Running M02 Run ${runIdx}/3 ---`);
      await cancelDraftIfPresent(page);
      await newConversation(page);

      const m02Prompt = 'E01 周一周二请假，E02 周三晚班优先，帮我重新排一下，只生成待确认方案。';

      // Capture INPUT screenshot
      const m02InputPath = path.join(SCREENSHOTS_DIR, `M02-INPUT${runIdx > 1 ? `-RUN${runIdx}` : ''}.png`);
      const panel = await openCopilot(page);
      const input = panel.getByRole('textbox', { name: '排班消息' });
      await input.fill(m02Prompt);
      await page.screenshot({ path: m02InputPath });

      const m02 = await sendMessage(
        page,
        m02Prompt,
        runIdx === 1 ? 'M02-PROGRESS' : `M02-PROGRESS-RUN${runIdx}`
      );

      const m02State = await getScheduleState(page);

      // Screenshots
      const m02ResultPath = path.join(SCREENSHOTS_DIR, runIdx === 1 ? 'M02-RESULT.png' : `M02-RESULT-RUN${runIdx}.png`);
      await page.screenshot({ path: m02ResultPath });

      // Close copilot temporarily to capture full schedule workbench
      const closeBtn = panel.locator('button[aria-label="关闭 AI 助手"]');
      if (await closeBtn.isVisible()) await closeBtn.click();
      await page.waitForTimeout(1000);
      const m02SchedulePath = path.join(SCREENSHOTS_DIR, runIdx === 1 ? 'M02-SCHEDULE.png' : `M02-SCHEDULE-RUN${runIdx}.png`);
      await page.screenshot({ path: m02SchedulePath });
      await openCopilot(page);

      // Check condition 1: E01 Mon no shift
      // Check condition 2: E01 Tue no shift
      // Check condition 3: E02 Wed evening preferred
      const e01Row = await getEmployeeDayShift(page, 'E01', 0);
      const e02Row = await getEmployeeDayShift(page, 'E02', 0);

      console.log(`Run ${runIdx} E01 Row:`, e01Row.slice(0, 120));
      console.log(`Run ${runIdx} E02 Row:`, e02Row.slice(0, 120));

      const isClarification = m02.assistantText.includes('请补充') || m02.assistantText.includes('具体员工') || m02.assistantText.includes('哪天');
      const condition1Met = !e01Row.includes('09:00 - 17:00\n早班') || e01Row.includes('请假') || e01Row.includes('Off') || m02.assistantText.includes('周一');
      const condition2Met = e01Row.includes('请假') || e01Row.includes('Off') || m02.assistantText.includes('周二');
      const condition3Met = e02Row.includes('晚班') || m02.assistantText.includes('E02') || m02.assistantText.includes('晚班');

      const m02Pass = !m02.hasError && m02State.hasDraft && !isClarification && condition1Met && condition2Met && condition3Met;

      const runData = {
        run: runIdx,
        durationMs: m02.durationMs,
        pass: m02Pass,
        status: m02Pass ? 'PASS' : 'FAIL',
        hasDraft: m02State.hasDraft,
        draftVersion: m02State.draftVersion,
        isClarification,
        condition1Met,
        condition2Met,
        condition3Met,
        e01Row: e01Row.slice(0, 200),
        e02Row: e02Row.slice(0, 200),
        assistantText: m02.assistantText
      };
      m02Runs.push(runData);
      console.log(`M02 Run ${runIdx}: ${runData.status} (${m02.durationMs}ms, draft v${m02State.draftVersion})`);

      // --- GROUP 5: CROSSTALK TEST (Directly follow up in same conversation!) ---
      console.log(`\n--- Running Crosstalk Test (Run ${runIdx}) ---`);
      const crosstalkPrompt = '我问一下，你这个周日为什么安排这么多人？';
      const c01 = await sendMessage(page, crosstalkPrompt);
      const c01State = await getScheduleState(page);

      const c01Path = path.join(SCREENSHOTS_DIR, runIdx === 1 ? 'C01-RESULT.png' : `C01-RESULT-RUN${runIdx}.png`);
      await page.screenshot({ path: c01Path });

      // Must answer Sunday, and must NOT mention E01 leave / E02 evening / restore availability
      const c01AnswersSunday = (
        c01.assistantText.includes('周日') ||
        c01.assistantText.includes('客流') ||
        c01.assistantText.includes('人') ||
        c01.assistantText.includes('班次') ||
        c01.assistantText.includes('周末')
      );
      const c01HasCrosstalk = (
        c01.assistantText.includes('E01') ||
        c01.assistantText.includes('请假') ||
        c01.assistantText.includes('E02') ||
        c01.assistantText.includes('晚班优先')
      );

      const c01Pass = !c01.hasError && c01AnswersSunday && !c01HasCrosstalk;
      const c01RunData = {
        run: runIdx,
        durationMs: c01.durationMs,
        pass: c01Pass,
        status: c01Pass ? 'PASS' : 'FAIL',
        answersSunday: c01AnswersSunday,
        hasCrosstalk: c01HasCrosstalk,
        assistantText: c01.assistantText
      };
      crosstalkRuns.push(c01RunData);
      console.log(`Crosstalk Run ${runIdx}: ${c01RunData.status} (hasCrosstalk: ${c01HasCrosstalk})`);

      // Clean up draft after this run
      await cancelDraftIfPresent(page);
    }

    const m02PassCount = m02Runs.filter(r => r.pass).length;
    results.cases['M02'] = {
      caseId: 'M02',
      input: 'E01 周一周二请假，E02 周三晚班优先，帮我重新排一下，只生成待确认方案。',
      runs: m02Runs,
      summary: `${m02PassCount}/3 PASS`,
      pass: m02PassCount === 3,
      status: m02PassCount === 3 ? 'PASS' : m02PassCount > 0 ? 'PARTIAL' : 'FAIL'
    };

    const crosstalkPassCount = crosstalkRuns.filter(r => r.pass).length;
    results.cases['C01'] = {
      caseId: 'C01',
      input: '我问一下，你这个周日为什么安排这么多人？',
      runs: crosstalkRuns,
      summary: `${crosstalkPassCount}/3 PASS`,
      pass: crosstalkPassCount === 3,
      status: crosstalkPassCount === 3 ? 'PASS' : crosstalkPassCount > 0 ? 'PARTIAL' : 'FAIL'
    };

    // --- STEP 6: DRAFT CLEANUP FINAL VERIFICATION ---
    console.log('\n=== DRAFT CLEANUP FINAL VERIFICATION ===');
    const cleanupDone = await cancelDraftIfPresent(page);
    const finalState = await getScheduleState(page);
    const cleanupPath = path.join(SCREENSHOTS_DIR, 'CLEANUP-AFTER.png');
    await page.screenshot({ path: cleanupPath });

    results.cases['CLEANUP'] = {
      caseId: 'CLEANUP',
      draftCleaned: !finalState.hasDraft,
      confirmedVersion: finalState.confirmedVersion,
      status: !finalState.hasDraft ? 'PASS' : 'FAIL',
      screenshot: 'CLEANUP-AFTER.png'
    };
    console.log(`Draft Cleanup: ${results.cases['CLEANUP'].status}, Confirmed Version: v${finalState.confirmedVersion}`);

    // --- STEP 7: VISUAL & INTERACTIVE AUDIT ---
    console.log('\n=== VISUAL & INTERACTIVE AUDIT ===');
    const visualAudit = await page.evaluate(() => {
      const panel = document.querySelector('[role="dialog"][aria-label="OptiShift Copilot 智能排班助手"]');
      const isFixed = panel ? window.getComputedStyle(panel).position === 'fixed' : false;
      const workbench = document.querySelector('[data-schedule-workbench]');
      const workbenchWidth = workbench ? workbench.getBoundingClientRect().width : 0;
      
      // Check for raw markdown bolding in assistant messages
      const bubbles = Array.from(document.querySelectorAll('[data-testid="markdown-message"]'));
      let rawBoldFound = false;
      for (const b of bubbles) {
        if (b.innerText.includes('**')) {
          rawBoldFound = true;
          break;
        }
      }

      return {
        isPanelFixedOverlay: isFixed,
        workbenchWidth,
        rawMarkdownBoldFound: rawBoldFound,
        panelComputedWidth: panel ? window.getComputedStyle(panel).width : '0'
      };
    });
    results.visualAudit = visualAudit;
    console.log('Visual Audit:', JSON.stringify(visualAudit, null, 2));

    // Save all results
    results.networkSummary = {
      totalRequests: networkEvents.length,
      streamRequests: networkEvents.filter(e => e.url.includes('/messages/stream')).length,
      scheduleRequests: networkEvents.filter(e => e.url.includes('/api/schedule/')).length
    };
    results.consoleErrors = consoleErrors;

    fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
    console.log(`\n=== ACCEPTANCE TEST RUN COMPLETED. RESULTS SAVED TO ${RESULTS_FILE} ===`);

  } catch (err) {
    console.error('Fatal error during test run:', err);
    results.fatalError = err.toString();
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
  } finally {
    await browser.close();
  }
}

runAll().catch(err => {
  console.error('Unhandled top-level error:', err);
  process.exit(1);
});
