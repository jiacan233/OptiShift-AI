# -*- coding: utf-8 -*-
"""
OptiShift acceptance runner v2 - handles redirect page + correct UI selectors.
"""
import argparse, json, pathlib, sys, time, datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/"
SS  = pathlib.Path("tests/acceptance/screenshots")
RES = pathlib.Path("tests/acceptance/results")
LLM_TIMEOUT   = 90_000  # ms to wait for LLM reply
SETTLE        =  4_000  # ms settle after streaming

ALL_CASES = {
    "00": {
        "id": "Case 00", "description": "双条件最终重排 - 复现真实故障",
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
        "id": "Case 02", "description": "多轮Slot Filling，不允许每轮失忆",
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
        "id": "Case 03", "description": "Advice Suggestion ID / 第二个方案引用",
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
        "id": "Case 04", "description": "话题切换，测试历史污染",
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
    },
    "05": {
        "id": "Case 05", "description": "口语化Mutation——塞进/排进",
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
        "id": "Case 06", "description": "同一个员工两个条件，防止cross-product/丢条件",
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
        "id": "Case 07", "description": "合法Force Override + 一个正常条件",
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
        "id": "Case 08", "description": "不可突破规则必须真正拒绝 (H01)",
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
    },
    "09": {
        "id": "Case 09", "description": "Pending Draft Gate + 聊天确认不得正式生效",
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
    },
    "10": {
        "id": "Case 10", "description": "跨周上下文 + 两条件Generate",
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


def bypass_redirect(page):
    """Handle the Tencent Cloud redirect/warning page."""
    try:
        btn = page.query_selector("#submitBtn")
        if btn and btn.is_visible():
            print("  [bypass] Clicking redirect confirm button...")
            btn.click()
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  [bypass] No redirect or error: {e}")


def open_ai_panel(page):
    """Open the AI Copilot panel and wait for the input box."""
    # Button: aria-label="打开 AI 助手"
    try:
        btn = page.query_selector('[aria-label="打开 AI 助手"]')
        if btn and btn.is_visible():
            btn.click()
            print("  [panel] Clicked AI assistant button")
            page.wait_for_timeout(2000)
            # Screenshot after click
            page.screenshot(path=str(SS/"panel_open.png"))
            return True
    except Exception as e:
        print(f"  [panel] Error: {e}")
    return False


def find_chat_input(page):
    """Find the chat textarea. Probe confirmed selector: resize-none bg-transparent."""
    for sel in ["textarea.resize-none", "textarea[class*='resize-none']",
                "textarea[class*='bg-transparent']", "textarea"]:
        try:
            for el in page.query_selector_all(sel):
                if el.is_visible():
                    return el
        except Exception:
            pass
    return None



def probe_panel_html(page):
    """Dump body HTML after panel opened to find selectors."""
    html = page.evaluate("document.body.innerHTML")
    path = RES / "panel_html.txt"
    path.write_text(html, encoding="utf-8")
    print(f"  [probe] Panel HTML saved to {path} ({len(html)} chars)")
    return html


def get_last_agent_reply(page) -> str:
    """Extract the last AI message from the chat panel."""
    reply_selectors = [
        "[data-role='assistant']",
        ".assistant-message",
        "[class*='assistant']",
        "[class*='ai-message']",
        "[class*='agent']",
        "[class*='reply']",
        "[class*='response']",
        "[class*='message']:not([class*='user'])",
    ]
    for sel in reply_selectors:
        try:
            els = page.query_selector_all(sel)
            if els:
                return els[-1].inner_text().strip()
        except Exception:
            pass

    # Fallback: get all visible divs with substantial text
    try:
        texts = page.evaluate("""
            () => {
                const divs = Array.from(document.querySelectorAll('div, p, span'));
                return divs
                    .filter(el => el.offsetParent !== null && el.innerText && el.innerText.trim().length > 30)
                    .map(el => ({
                        text: el.innerText.trim().substring(0, 500),
                        class: el.className.substring(0, 100)
                    }))
                    .slice(-10);
            }
        """)
        if texts:
            return texts[-1]["text"]
    except Exception:
        pass
    return "(could not extract reply)"


def wait_for_reply(page, turn_num: int) -> tuple:
    """Wait for LLM to finish. Returns (reply_text, elapsed_ms)."""
    t0 = time.time()

    # Wait for any loading state
    try:
        page.wait_for_function(
            """() => {
                // Look for loading indicators
                const spinners = document.querySelectorAll(
                    '.animate-spin, [class*="loading"], [class*="spinner"], [class*="thinking"]'
                );
                return spinners.length === 0;
            }""",
            timeout=LLM_TIMEOUT,
            polling=1000,
        )
    except PWTimeout:
        print(f"    [warn] Turn {turn_num}: loading timeout after {LLM_TIMEOUT}ms")

    page.wait_for_timeout(SETTLE)
    elapsed = int((time.time() - t0) * 1000)
    reply = get_last_agent_reply(page)
    return reply, elapsed


def start_new_conversation(page):
    """Click 'new conversation' button."""
    selectors = [
        '[aria-label*="新对话"]',
        '[title*="新对话"]',
        'button:has-text("新对话")',
        'button:has-text("新建")',
        '[class*="new-chat"]',
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
    return False


def cancel_draft(page):
    """Cancel any pending draft."""
    for sel in ['button:has-text("取消草稿")', 'button:has-text("放弃")',
                'button:has-text("取消")', '[class*="cancel-draft"]']:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
    return False


def check_draft_exists(page) -> tuple:
    """Returns (exists: bool, text_sample: str)."""
    draft_selectors = [
        '[class*="draft"]', '[data-testid*="draft"]',
        ':has-text("草稿")', ':has-text("待确认")',
        '[class*="pending"]',
    ]
    for sel in draft_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True, el.inner_text()[:300]
        except Exception:
            pass
    return False, ""


def run_case(page, case_key: str, case: dict) -> dict:
    cid = case["id"]
    print(f"\n{'='*60}\nStarting {cid}: {case['description']}\n{'='*60}")

    # Start fresh conversation
    started = start_new_conversation(page)
    if not started:
        print(f"  [warn] Could not start new conversation")

    # Make sure panel is open and find input
    chat_input = find_chat_input(page)
    if not chat_input:
        print("  [panel] Input not found, trying to open AI panel...")
        open_ai_panel(page)
        page.wait_for_timeout(2000)
        # Probe HTML to understand structure
        probe_panel_html(page)
        page.screenshot(path=str(SS/f"{case_key}_after_panel.png"), full_page=True)
        chat_input = find_chat_input(page)

    if not chat_input:
        print(f"  [BLOCKED] Cannot find chat input for {cid}")
        return {
            "case_id": cid, "case_key": case_key,
            "description": case["description"],
            "turns": [{"turn": i+1, "user": t, "reply": "BLOCKED: no input found",
                       "result": "BLOCKED", "bugs": ["UI_NOT_FOUND"]}
                      for i, t in enumerate(case["turns"])],
            "draft_created": False, "overall_result": "BLOCKED",
        }

    turn_results = []
    draft_created = False

    for i, turn_text in enumerate(case["turns"]):
        tn = i + 1
        print(f"  Turn {tn}: {turn_text[:60]}...")

        # Re-find input (may change between turns)
        chat_input = find_chat_input(page)
        if not chat_input:
            turn_results.append({
                "turn": tn, "user": turn_text,
                "reply": "BLOCKED: lost input box",
                "elapsed_ms": 0, "result": "BLOCKED",
                "draft_this_turn": False, "bugs": ["LOST_INPUT"],
            })
            continue

        # Send message
        try:
            chat_input.click()
            chat_input.fill(turn_text)
            page.wait_for_timeout(200)
            chat_input.press("Enter")
        except Exception as e:
            turn_results.append({
                "turn": tn, "user": turn_text,
                "reply": f"BLOCKED: send error {e}",
                "elapsed_ms": 0, "result": "BLOCKED",
                "draft_this_turn": False, "bugs": ["SEND_ERROR"],
            })
            continue

        # Wait for reply
        reply, elapsed = wait_for_reply(page, tn)

        # Screenshot
        ss = SS / f"{case_key}_t{tn:02d}.png"
        try:
            page.screenshot(path=str(ss))
        except Exception:
            ss = None

        # Draft check
        has_draft, draft_text = check_draft_exists(page)
        if has_draft:
            draft_created = True

        # Determine result
        result = "PASS"
        bugs = []
        if not reply or reply.startswith("(") or len(reply) < 5:
            result = "FAIL"
            bugs.append("EMPTY_REPLY")

        # Case-specific checks
        if case_key == "04" and tn == 5:
            if "E17" in reply and "周三" in reply:
                result = "FAIL"
                bugs.append("BUG-B: History contamination at topic switch turn")
        if case_key == "08" and tn == 8:
            if has_draft:
                result = "FAIL"
                bugs.append("BUG-M: Illegal draft created despite H01 violation")
        if case_key == "09" and tn == 6:
            # "确认" should NOT confirm draft
            if "已确认" in reply and "草稿" not in reply:
                result = "FAIL"
                bugs.append("BUG-P: Chat '确认' incorrectly confirmed draft")

        print(f"    => {result} | {elapsed}ms | draft={has_draft} | reply_len={len(reply)}")
        for b in bugs:
            print(f"    BUG: {b}")

        turn_results.append({
            "turn": tn, "user": turn_text,
            "reply": reply[:2500],
            "elapsed_ms": elapsed,
            "screenshot": str(ss) if ss else None,
            "draft_this_turn": has_draft,
            "draft_text": draft_text[:300] if draft_text else "",
            "result": result,
            "bugs": bugs,
        })

    cancel_draft(page)

    fails = [t for t in turn_results if t["result"] == "FAIL"]
    blocks = [t for t in turn_results if t["result"] == "BLOCKED"]
    if len(blocks) == len(turn_results):
        overall = "BLOCKED"
    elif fails:
        overall = "FAIL"
    else:
        overall = "PASS"

    return {
        "case_id": cid, "case_key": case_key,
        "description": case["description"],
        "turns": turn_results,
        "draft_created": draft_created,
        "overall_result": overall,
        "fail_count": len(fails),
        "block_count": len(blocks),
        "total_turns": len(turn_results),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    SS.mkdir(parents=True, exist_ok=True)
    RES.mkdir(parents=True, exist_ok=True)

    cases = [(k, ALL_CASES[k]) for k in args.cases if k in ALL_CASES]
    if not cases:
        print(f"No valid cases: {args.cases}")
        sys.exit(1)

    print(f"Cases to run: {[c[0] for c in cases]}")
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

        print(f"Loading {URL}...")
        page.goto(URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.screenshot(path=str(SS/"01_initial.png"), full_page=True)

        # Handle redirect
        bypass_redirect(page)
        page.screenshot(path=str(SS/"02_after_redirect.png"), full_page=True)

        # Open AI panel
        open_ai_panel(page)
        page.screenshot(path=str(SS/"03_panel_opened.png"), full_page=True)

        # Probe
        probe_panel_html(page)

        # Run cases
        for case_key, case_data in cases:
            res = run_case(page, case_key, case_data)
            all_results.append(res)
            page.wait_for_timeout(2000)

        browser.close()

    end = datetime.datetime.utcnow().isoformat()
    total = len(all_results)
    passed = sum(1 for r in all_results if r["overall_result"] == "PASS")
    failed = sum(1 for r in all_results if r["overall_result"] == "FAIL")
    blocked = sum(1 for r in all_results if r["overall_result"] == "BLOCKED")

    output = {
        "run_start": start, "run_end": end, "url": URL,
        "cases_ran": [c[0] for c in cases],
        "summary": {"total": total, "pass": passed, "fail": failed, "blocked": blocked},
        "results": all_results,
    }

    pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Results: PASS={passed} FAIL={failed} BLOCKED={blocked}")
    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
