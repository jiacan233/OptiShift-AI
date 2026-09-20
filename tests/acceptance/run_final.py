# -*- coding: utf-8 -*-
"""
OptiShift Multi-Turn Acceptance Runner — FINAL VERSION
Confirmed selectors:
  - Textarea:        textarea[class*='resize-none']
  - AI panel btn:    [aria-label="打开 AI 助手"]
  - Redirect btn:    #submitBtn
  - Reply done:      div[class*='border-blue-100'][class*='rounded-xl']
  - New chat:        button with text 新对话 OR pencil icon
"""
import argparse, json, pathlib, sys, time, datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/"
SS  = pathlib.Path("tests/acceptance/screenshots")
RES = pathlib.Path("tests/acceptance/results")
LLM_POLL_INTERVAL = 1   # seconds between polls
LLM_MAX_WAIT      = 90  # seconds max wait per turn
SETTLE            = 3   # seconds settle after reply detected

ALL_CASES = {
    "00": {
        "id": "Case 00", "description": "双条件最终重排",
        "turns": [
            "E02这周为啥没排班？",
            "我想把E02排进去，你有什么建议吗？",
            "如果尽量少改其他人，你建议把他放哪？",
            "那就重新排，把E02排进本周。",
            "周二。",
            "晚班。",
            "先别生成，再加一个条件：E17周三请假。你先分析一下这两个条件一起会怎样。",
            "把你现在理解的两个排班条件复述给我。",
            "可以，就按这两个条件重新排班，生成草稿。",
        ],
    },
    "01": {
        "id": "Case 01", "description": "AI建议→建议引用→第二个条件→真正执行",
        "turns": [
            "E02这周为什么一个班都没有？",
            "我想让E02这周上班，你帮我看看放哪里比较合适，先不要改。",
            "如果目标是尽量少改现在的排班，你最推荐哪个班次？为什么？",
            "还有别的方案吗？给我两个候选。",
            "第二个方案具体会影响哪些人？",
            "如果采用第二个方案，再加一个条件：E20周五请假，会怎么样？先分析，不生成。",
            "把最终准备执行的两个要求列出来，我确认一下。",
            "好，按这两个条件重新排班。",
        ],
    },
    "02": {
        "id": "Case 02", "description": "多轮Slot Filling不失忆",
        "turns": [
            "我想重新排一下本周，把E02安排进去。",
            "就周二。",
            "晚班。",
            "先别生成。你现在理解我要改什么？",
            "再加一个要求，E20周五请假。",
            "这两个条件放一起会影响哪些班次？",
            "尽量少动其他人的班，告诉我你准备怎么改。",
            "现在按\"E02周二晚班上班 + E20周五请假\"重新排班。",
        ],
    },
    "03": {
        "id": "Case 03", "description": "第二个方案引用",
        "turns": [
            "看一下这周哪些班次比较适合再放一个人进去？",
            "如果是E02呢？",
            "给我两个不同的调整方案，先不要生成。",
            "第二个方案为什么这么调？",
            "第二个方案如果再加E11周四晚班优先，会怎么样？",
            "先做反事实分析，看两个要求一起能不能满足所有硬约束。",
            "把你准备使用的两个变更条件和目标周复述给我。",
            "可以，按第二个方案加上E11周四晚班优先，重新排班。",
        ],
    },
    "04": {
        "id": "Case 04", "description": "话题切换历史污染",
        "turns": [
            "如果E17周三请假，会有什么影响？",
            "给我两个解决建议。",
            "第二条为什么？",
            "先别改，我只是分析。",
            "换个问题：周日早班为什么安排现在这些人？",
            "那E02这周为什么没排班？",
            "好，现在回到调整：E17周三请假，同时把E02放到周二晚班。先分析这两个要求。",
            "没问题的话，就按这两个条件重新排。",
        ],
        "special": {"turn5_check_no_E17": True},
    },
    "05": {
        "id": "Case 05", "description": "口语化塞进/排进",
        "turns": [
            "周二晚班现在是什么情况？",
            "我感觉这班人不少，那如果把E02塞进去会怎么样？",
            "那如果是周四早班呢？",
            "先别动。我还希望E11周四晚上优先上。",
            "你对比一下：E02周二晚班+E11周四晚班优先，跟现在不改有什么区别？",
            "预计主要会换掉谁？",
            "如果所有硬约束都能满足，就尽量少动其他人。",
            "需要重新排班：把E02排进周二晚班，同时E11周四晚班优先。",
        ],
    },
    "06": {
        "id": "Case 06", "description": "同员工两条件防cross-product",
        "turns": [
            "E02这周现在是什么排班情况？",
            "如果让E02周二晚班上，会有什么影响？",
            "我还希望他周五晚班也优先安排。",
            "先别生成，检查一下这样会不会让E02一周班次太多。",
            "连续工作天数呢？",
            "晚班接第二天早班的规则有没有风险？",
            "把你现在理解的两个条件逐条列出来。",
            "按这两个条件重新排班，尽量少改其他人。",
        ],
    },
    "07": {
        "id": "Case 07", "description": "Force Override + 正常条件",
        "turns": [
            "E17为什么周一不能排？",
            "如果一定让E17周一早班上，会违反什么规则？",
            "有没有完全合规的替代方案？",
            "先不要生成。",
            "另外我还想正常把E02安排到周二晚班。",
            "先一起分析这两个要求：E17周一早班强制上班；E02周二晚班正常上班。不要生成。",
            "我明确授权：只允许突破R08，仅限E17、周一、早班。E02周二晚班必须正常满足所有规则。除此之外不授权任何规则违规。",
            "按刚才两个条件强制生成草稿。",
        ],
    },
    "08": {
        "id": "Case 08", "description": "Protected Rule H01必须拒绝",
        "turns": [
            "E02周一现在有班吗？",
            "如果让E02周一早班和晚班都上会怎样？",
            "这会违反哪条规则？",
            "先不要修改。",
            "另外加一个正常条件：E17周三请假。",
            "如果要求：E02周一早晚都上，同时E17周三请假，系统能生成吗？",
            "即使我说强制，也不要绕过不可突破规则。你告诉我会怎么处理。",
            "尝试按这两个要求生成；如果H01不可突破，就必须明确拒绝，且不能产生非法Draft。",
        ],
        "special": {"turn8_must_reject_not_draft": True},
    },
    "09": {
        "id": "Case 09", "description": "Pending Draft Gate + 聊天确认不得生效",
        "turns": [
            "这周有什么可以优化的地方？",
            "如果想把E02加入排班，你建议怎么调？",
            "先分析：E02周二晚班上班，E17周三请假。",
            "好，就按这两个条件重新排班。",
            "这版具体改了哪些人？",
            "确认。",
            "现在这版到底是正式排班还是待确认草稿？",
            "我现在再要求E20周五请假并重新排一次，可以吗？",
        ],
        "special": {"turn6_no_confirm": True, "turn8_pending_gate": True},
    },
    "10": {
        "id": "Case 10", "description": "跨周上下文两条件Generate",
        "turns": [
            "我现在工作台看的是哪一周？",
            "下周有没有正式排班？",
            "回到本周，E02为什么没有排班？",
            "如果是下周，我想让E02周二晚班优先。",
            "再加一个条件，下周E20周三请假。",
            "先分析下周这两个条件一起是否可行。",
            "把目标周、员工、日期、班次、两个条件完整复述一次。",
            "好，为下周按这两个条件生成排班草稿。",
        ],
    },
}


# ── helpers ──────────────────────────────────────────────────────────────────

def log(msg: str):
    """UTF-8 safe print."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode(), flush=True)


def bypass_redirect(page):
    sb = page.query_selector("#submitBtn")
    if sb and sb.is_visible():
        sb.click()
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(2)
        return True
    return False


def open_ai_panel(page):
    btn = page.query_selector('[aria-label="打开 AI 助手"]')
    if btn and btn.is_visible():
        btn.click()
        time.sleep(3)
        return True
    return False


def find_textarea(page):
    for sel in ["textarea[class*='resize-none']", "textarea[class*='bg-transparent']", "textarea"]:
        for el in page.query_selector_all(sel):
            if el.is_visible():
                return el
    return None


def start_new_conversation(page):
    """Try to start a new conversation."""
    # Look for 新对话 button or + icon in copilot panel header
    for sel in [
        'button[title*="新对话"]', 'button[aria-label*="新对话"]',
        'button[title*="新建"]',   'button[aria-label*="新建"]',
        'button[title*="New"]',    'button[aria-label*="New"]',
    ]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.click()
            time.sleep(1.5)
            return True
    # Try finding a button near the chat panel with text 新对话
    try:
        el = page.get_by_role("button", name="新对话")
        if el.is_visible():
            el.click()
            time.sleep(1.5)
            return True
    except Exception:
        pass
    return False


def get_page_text_len(page) -> int:
    """Quick measure of copilot text length for change detection."""
    try:
        return page.evaluate(
            "() => { const el = document.querySelector('.soft-scrollbar') "
            "|| document.querySelector('.copilot-overlay'); "
            "return el ? (el.innerText||'').length : 0; }"
        )
    except Exception:
        return 0


def wait_for_reply(page, prev_reply_count: int) -> tuple:
    """
    Wait for LLM reply. Two-stage detection:
    1. Primary: exec-record div count increases (tool-call turns, fast ~3-15s)
    2. Fallback: copilot text length grows by >80 chars (conversational turns, max 30s)
    Returns (reply_text, elapsed_ms, exec_record_text, new_count).
    """
    t0 = time.time()
    baseline_len = get_page_text_len(page)
    found = False

    for tick in range(LLM_MAX_WAIT * 2):  # 0.5s each → max 90s
        time.sleep(0.5)
        elapsed_so_far = time.time() - t0

        # Primary: exec-record div appeared
        exec_divs = page.query_selector_all(
            "div[class*='border-blue-100'][class*='rounded-xl']")
        if len(exec_divs) > prev_reply_count:
            time.sleep(SETTLE)
            found = True
            break

        # Fallback: text grew substantially (conversational reply, no tool call)
        if elapsed_so_far > 5:  # don't check too early
            cur_len = get_page_text_len(page)
            if cur_len - baseline_len > 80:
                # Wait a bit more for streaming to finish
                time.sleep(4)
                break

    elapsed = int((time.time() - t0) * 1000)

    exec_divs = page.query_selector_all(
        "div[class*='border-blue-100'][class*='rounded-xl']")
    new_count = len(exec_divs)
    exec_text = ""
    if exec_divs:
        try:
            exec_text = exec_divs[-1].inner_text().strip()
        except Exception:
            pass

    # Extract AI reply from soft-scrollbar chat container, skip exec-record divs
    reply = ""
    try:
        reply = page.evaluate("""
            () => {
                const container = document.querySelector('.soft-scrollbar')
                    || document.querySelector('[class*="soft-scrollbar"]')
                    || document.querySelector('.copilot-overlay');
                if (!container) return '(no container)';
                const elems = Array.from(container.querySelectorAll('div,p,li'));
                const candidates = elems.filter(el => {
                    if (!el.offsetParent) return false;
                    const cls = el.className || '';
                    if (cls.includes('border-blue-100')) return false;
                    const t = (el.innerText || '').trim();
                    if (t.length < 15 || t.length > 4000) return false;
                    if (el.querySelectorAll('div').length > 6) return false;
                    return true;
                });
                return candidates.slice(-4).map(el =>
                    (el.innerText||'').trim()).join('\\n---\\n');
            }
        """) or ""
    except Exception as e:
        reply = f"(js err: {e})"

    return reply, elapsed, exec_text, new_count


def check_draft(page) -> tuple:
    """Returns (has_draft: bool, draft_sample: str)."""
    for sel in ["[class*='draft']", "[class*='pending']",
                "div:has-text('草稿')", "div:has-text('待确认')"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True, el.inner_text()[:300]
        except Exception:
            pass
    return False, ""


def cancel_draft(page):
    for sel in ['button:has-text("取消草稿")', 'button:has-text("放弃草稿")',
                'button[aria-label*="取消"]']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(1)
                return True
        except Exception:
            pass
    return False


def take_screenshot(path: pathlib.Path, page) -> str:
    try:
        page.screenshot(path=str(path))
        return str(path)
    except Exception:
        return ""


# ── bug detection ─────────────────────────────────────────────────────────────

def detect_bugs(case_key: str, turn_num: int, reply: str, has_draft: bool,
                exec_text: str) -> list:
    bugs = []
    r = reply.lower()

    # Empty reply
    if not reply or len(reply) < 10:
        bugs.append({"id": "BUG-EMPTY-REPLY", "sev": "P1",
                     "desc": f"Agent reply too short or empty (len={len(reply)})"})

    # Case 04 Turn 5: topic switch should NOT mention E17
    if case_key == "04" and turn_num == 5:
        if "e17" in r or "周三" in reply:
            bugs.append({"id": "BUG-B-HISTORY-CONTAMINATION", "sev": "P1",
                         "desc": "Topic switch turn: reply still mentions E17/周三 from prior topic"})

    # Case 08 Turn 8: H01 protected - must NOT create draft
    if case_key == "08" and turn_num == 8:
        if has_draft:
            bugs.append({"id": "BUG-M-H01-VIOLATED", "sev": "P0",
                         "desc": "H01 Protected Rule violated: illegal draft created for double-shift same day"})
        if "h01" not in r and "不可突破" not in reply and "拒绝" not in reply:
            bugs.append({"id": "BUG-M-H01-NOT-MENTIONED", "sev": "P1",
                         "desc": "H01 not explicitly mentioned in refusal"})

    # Case 09 Turn 6: "确认" chat msg must NOT confirm draft
    if case_key == "09" and turn_num == 6:
        if "已确认" in reply and "草稿" not in reply:
            bugs.append({"id": "BUG-P-CHAT-CONFIRM", "sev": "P0",
                         "desc": "Chat '确认' incorrectly confirmed the draft as official schedule"})

    # Case 02 Turn 4: must remember E02 + Tue + evening
    if case_key == "02" and turn_num == 4:
        has_e02 = "e02" in r
        has_tue = "周二" in reply or "tuesday" in r or "tue" in r
        has_eve = "晚班" in reply or "evening" in r or "night" in r
        if not has_e02:
            bugs.append({"id": "BUG-A-LOST-EMPLOYEE", "sev": "P0",
                         "desc": "Turn 4 slot-fill check: E02 not mentioned (memory lost)"})
        if not has_tue:
            bugs.append({"id": "BUG-A-LOST-DAY", "sev": "P0",
                         "desc": "Turn 4 slot-fill check: 周二 (Tuesday) not mentioned (memory lost)"})
        if not has_eve:
            bugs.append({"id": "BUG-A-LOST-SHIFT", "sev": "P0",
                         "desc": "Turn 4 slot-fill check: 晚班 (evening) not mentioned (memory lost)"})

    # Case 06 Turn 7: must list BOTH E02 conditions correctly
    if case_key == "06" and turn_num == 7:
        has_tue = "周二" in reply
        has_fri = "周五" in reply
        has_eve1 = "晚班" in reply
        if not (has_tue and has_fri and has_eve1):
            bugs.append({"id": "BUG-F-CONDITION-INCOMPLETE", "sev": "P1",
                         "desc": f"Turn 7 condition recap missing: 周二={has_tue} 周五={has_fri} 晚班={has_eve1}"})

    # Check Solver called for mutation turns
    mutation_final_turns = {
        "00": 9, "01": 8, "02": 8, "03": 8,
        "04": 8, "05": 8, "06": 8, "07": 8, "09": 4,
    }
    if case_key in mutation_final_turns and turn_num == mutation_final_turns[case_key]:
        solver_called = "排班" in exec_text or "solver" in exec_text.lower() or "cp-sat" in exec_text.lower()
        if not solver_called and not has_draft:
            bugs.append({"id": "BUG-J-SOLVER-NOT-CALLED", "sev": "P0",
                         "desc": f"Final mutation turn: Solver not called and no Draft created"})

    return bugs


# ── main case runner ──────────────────────────────────────────────────────────

def run_case(page, case_key: str, case: dict) -> dict:
    cid = case["id"]
    log(f"\n{'='*55}\n{cid}: {case['description']}\n{'='*55}")

    # New conversation
    if not start_new_conversation(page):
        log("  [warn] Could not start new conversation, continuing anyway")

    # Ensure textarea available
    ta = find_textarea(page)
    if not ta:
        open_ai_panel(page)
        time.sleep(2)
        ta = find_textarea(page)

    if not ta:
        log(f"  [BLOCKED] No textarea found for {cid}")
        take_screenshot(SS / f"{case_key}_BLOCKED.png", page)
        return {
            "case_id": cid, "case_key": case_key,
            "description": case["description"],
            "turns": [{"turn": i+1, "user": t, "reply": "BLOCKED",
                       "result": "BLOCKED", "bugs": []}
                      for i, t in enumerate(case["turns"])],
            "overall_result": "BLOCKED",
            "draft_created": False,
            "bugs_found": [{"id": "BUG-ENV-UI", "sev": "P0",
                            "desc": "Cannot find chat input - UI selector mismatch"}],
        }

    turn_results = []
    all_bugs = []
    draft_created = False
    reply_count = 0  # number of AI replies seen so far

    for i, turn_text in enumerate(case["turns"]):
        tn = i + 1
        log(f"  Turn {tn}/{len(case['turns'])}: {turn_text[:55]}...")

        # Find textarea fresh each turn
        ta = find_textarea(page)
        if not ta:
            log(f"    [warn] Textarea lost at turn {tn}")
            turn_results.append({
                "turn": tn, "user": turn_text, "reply": "BLOCKED: textarea lost",
                "elapsed_ms": 0, "result": "BLOCKED", "bugs": [],
                "draft_this_turn": False,
            })
            continue

        # Send message
        try:
            ta.click()
            ta.fill(turn_text)
            time.sleep(0.2)
            ta.press("Enter")
        except Exception as e:
            log(f"    [err] Send failed: {e}")
            turn_results.append({
                "turn": tn, "user": turn_text, "reply": f"BLOCKED: {e}",
                "elapsed_ms": 0, "result": "BLOCKED", "bugs": [],
                "draft_this_turn": False,
            })
            continue

        # Wait for reply
        reply, elapsed, exec_text, reply_count = wait_for_reply(page, reply_count)

        # Check draft
        has_draft, draft_sample = check_draft(page)
        if has_draft:
            draft_created = True

        # Take screenshot on certain turns or if draft detected
        ss_path = ""
        if tn in (1, len(case["turns"])) or has_draft or exec_text:
            ss_path = take_screenshot(SS / f"{case_key}_t{tn:02d}.png", page)

        # Bug detection
        bugs = detect_bugs(case_key, tn, reply, has_draft, exec_text)
        all_bugs.extend(bugs)

        # Result
        result = "FAIL" if bugs else "PASS"
        if not reply or len(reply) < 5:
            result = "FAIL"

        log(f"    => {result} | {elapsed}ms | draft={has_draft} | reply_len={len(reply)}")
        for b in bugs:
            log(f"    [{b['sev']}] {b['id']}: {b['desc']}")

        turn_results.append({
            "turn": tn,
            "user": turn_text,
            "reply": reply[:2000],
            "exec_record": exec_text[:500],
            "elapsed_ms": elapsed,
            "screenshot": ss_path,
            "draft_this_turn": has_draft,
            "draft_sample": draft_sample[:200],
            "result": result,
            "bugs": bugs,
        })

    # Cancel any draft
    if cancel_draft(page):
        log("  [ok] Draft cancelled")

    # Overall result
    fails = [t for t in turn_results if t["result"] == "FAIL"]
    blocks = [t for t in turn_results if t["result"] == "BLOCKED"]
    if len(blocks) == len(turn_results):
        overall = "BLOCKED"
    elif fails or any(b["sev"] == "P0" for b in all_bugs):
        overall = "FAIL"
    else:
        overall = "PASS"

    log(f"  {cid} => {overall} | bugs: {len(all_bugs)}")
    return {
        "case_id": cid, "case_key": case_key,
        "description": case["description"],
        "turns": turn_results,
        "draft_created": draft_created,
        "overall_result": overall,
        "bugs_found": all_bugs,
        "fail_count": len(fails),
        "block_count": len(blocks),
        "total_turns": len(turn_results),
    }


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    SS.mkdir(parents=True, exist_ok=True)
    RES.mkdir(parents=True, exist_ok=True)

    cases = [(k, ALL_CASES[k]) for k in args.cases if k in ALL_CASES]
    if not cases:
        log(f"No valid cases: {args.cases}")
        sys.exit(1)

    log(f"Running: {[c[0] for c in cases]}")
    start = datetime.datetime.utcnow().isoformat()
    all_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = ctx.new_page()

        log(f"Loading {URL} ...")
        page.goto(URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        take_screenshot(SS / f"{'_'.join(args.cases)}_01_init.png", page)

        if bypass_redirect(page):
            log("  [ok] Redirect bypassed")
            take_screenshot(SS / f"{'_'.join(args.cases)}_02_app.png", page)

        if open_ai_panel(page):
            log("  [ok] AI panel opened")
            take_screenshot(SS / f"{'_'.join(args.cases)}_03_panel.png", page)

        for case_key, case_data in cases:
            res = run_case(page, case_key, case_data)
            all_results.append(res)
            # Save incremental results after each case
            _save(args.output, start, args.cases, all_results)
            time.sleep(2)

        browser.close()

    _save(args.output, start, args.cases, all_results)

    total = len(all_results)
    passed  = sum(1 for r in all_results if r["overall_result"] == "PASS")
    failed  = sum(1 for r in all_results if r["overall_result"] == "FAIL")
    blocked = sum(1 for r in all_results if r["overall_result"] == "BLOCKED")
    log(f"\n{'='*55}")
    log(f"DONE | PASS={passed} FAIL={failed} BLOCKED={blocked} | {args.output}")


def _save(output_path, start, cases_ran, results):
    data = {
        "run_start": start,
        "run_end": datetime.datetime.utcnow().isoformat(),
        "url": URL,
        "cases_ran": cases_ran,
        "results": results,
    }
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
