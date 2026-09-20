# -*- coding: utf-8 -*-
"""
OptiShift Multi-Turn Agent Acceptance Test Runner
Runs a subset of cases (passed via --cases argument) against the live URL.
Each case uses a fresh conversation context and records full Agent replies.
"""
import argparse
import json
import os
import sys
import time
import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/"
SCREENSHOT_DIR = Path("tests/acceptance/screenshots")
RESULTS_DIR = Path("tests/acceptance/results")
LLM_RESPONSE_TIMEOUT_MS = 90_000   # 90s per turn for LLM
STREAM_SETTLE_MS = 4_000            # extra settle time after stream

ALL_CASES = {
    "00": {
        "id": "Case 00",
        "description": "双条件最终重排 - 复现真实故障",
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
        "checks": {
            "must_contain_draft": True,
            "draft_conditions": ["E02", "周二", "晚班", "E17", "周三"],
        },
    },
    "01": {
        "id": "Case 01",
        "description": "AI建议 → 建议引用 → 第二个条件 → 真正执行",
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
        "checks": {"must_contain_draft": True},
    },
    "02": {
        "id": "Case 02",
        "description": "多轮Slot Filling，不允许每轮失忆",
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
        "checks": {"must_contain_draft": True},
    },
    "03": {
        "id": "Case 03",
        "description": "Advice Suggestion ID / 第二个方案引用",
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
        "checks": {"must_contain_draft": True},
    },
    "04": {
        "id": "Case 04",
        "description": "话题切换，测试历史污染",
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
        "checks": {
            "turn5_must_not_mention_E17": True,
            "must_contain_draft": True,
        },
    },
    "05": {
        "id": "Case 05",
        "description": "口语化Mutation — 塞进/排进",
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
        "checks": {"must_contain_draft": True},
    },
    "06": {
        "id": "Case 06",
        "description": "同一个员工两个条件，防止cross-product/丢条件",
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
        "checks": {
            "turn7_must_list_both_conditions": True,
            "must_contain_draft": True,
        },
    },
    "07": {
        "id": "Case 07",
        "description": "合法Force Override + 一个正常条件",
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
        "checks": {
            "must_contain_draft": True,
            "must_mention_R08": True,
            "must_not_violate_other_rules": True,
        },
    },
    "08": {
        "id": "Case 08",
        "description": "不可突破规则必须真正拒绝 (H01)",
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
        "checks": {
            "must_mention_H01": True,
            "must_NOT_create_illegal_draft": True,
        },
    },
    "09": {
        "id": "Case 09",
        "description": "Pending Draft Gate + 聊天确认不得正式生效",
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
        "checks": {
            "turn4_creates_draft": True,
            "turn6_must_NOT_confirm": True,
            "turn7_must_say_draft_not_confirmed": True,
            "turn8_must_trigger_pending_gate": True,
        },
    },
    "10": {
        "id": "Case 10",
        "description": "跨周上下文 + 两条件Generate",
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
        "checks": {
            "must_contain_draft": True,
            "draft_must_be_next_week": True,
        },
    },
}


def wait_for_agent_response(page, turn_index: int, case_id: str) -> str:
    """
    Wait for the LLM to finish streaming its response.
    Returns the text of the last agent message.
    """
    # Strategy: wait for the loading indicator to disappear, then grab reply text
    try:
        # Wait for any loading spinner to appear first (max 5s)
        try:
            page.wait_for_selector(".message-loading, [data-testid='loading'], .animate-spin",
                                   timeout=5000)
        except PWTimeout:
            pass  # spinner may not appear if response is immediate

        # Wait for spinner to disappear (means streaming done)
        try:
            page.wait_for_selector(".message-loading, [data-testid='loading'], .animate-spin",
                                   state="detached", timeout=LLM_RESPONSE_TIMEOUT_MS)
        except PWTimeout:
            pass  # if no spinner found, proceed

        # Additional settle time
        page.wait_for_timeout(STREAM_SETTLE_MS)

        # Grab all assistant message blocks - take the last one
        messages = page.query_selector_all(
            "[data-role='assistant'], .assistant-message, .ai-message, "
            "[class*='assistant'], [class*='ai-reply'], [class*='agent-message']"
        )
        if messages:
            return messages[-1].inner_text().strip()

        # Fallback: grab all chat bubbles and take last one that looks like AI
        all_msgs = page.query_selector_all(".message, .chat-message, [class*='message']")
        if all_msgs:
            return all_msgs[-1].inner_text().strip()

        return "(could not extract reply)"

    except Exception as e:
        return f"(error extracting reply: {e})"


def find_input_box(page):
    """Try multiple selectors to find the chat input."""
    selectors = [
        "textarea[placeholder*='消息']",
        "textarea[placeholder*='输入']",
        "textarea[placeholder*='message']",
        "input[placeholder*='消息']",
        "input[placeholder*='输入']",
        "[role='textbox']",
        "textarea",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            pass
    return None


def find_new_chat_button(page):
    """Try multiple selectors for 'new conversation' button."""
    selectors = [
        "button:has-text('新对话')",
        "button:has-text('新建')",
        "button:has-text('New')",
        "[aria-label*='新对话']",
        "[title*='新对话']",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            pass
    return None


def open_copilot_panel(page):
    """Open the AI copilot panel if not already open."""
    try:
        # Check if already open
        if page.query_selector("[placeholder*='消息'], textarea[placeholder*='输入']"):
            return True

        btn_selectors = [
            "button:has-text('问问 AI')",
            "button:has-text('AI')",
            "button:has-text('智能')",
            "[aria-label*='AI']",
            "[title*='AI']",
        ]
        for sel in btn_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(2000)
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def cancel_draft_if_exists(page):
    """Cancel any pending draft to avoid contamination."""
    cancel_selectors = [
        "button:has-text('取消草稿')",
        "button:has-text('放弃草稿')",
        "button:has-text('取消')",
        "button:has-text('Cancel')",
    ]
    for sel in cancel_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
    return False


def run_case(page, case_key: str, case: dict, screenshot_dir: Path) -> dict:
    """Run a single case and return structured results."""
    case_id = case["id"]
    print(f"\n{'='*60}")
    print(f"Starting {case_id}: {case['description']}")
    print(f"{'='*60}")

    # Try to start a new conversation
    new_chat_btn = find_new_chat_button(page)
    if new_chat_btn:
        new_chat_btn.click()
        page.wait_for_timeout(2000)
        print(f"  [OK] Started new conversation for {case_id}")
    else:
        print(f"  [WARN] Could not find 'new conversation' button for {case_id}")
        # Try refreshing
        page.reload()
        page.wait_for_load_state("networkidle")
        open_copilot_panel(page)

    turn_results = []
    draft_created = False
    draft_text = ""

    for i, turn_text in enumerate(case["turns"]):
        turn_num = i + 1
        print(f"  Turn {turn_num}: {turn_text[:50]}...")

        # Find input
        input_box = find_input_box(page)
        if not input_box:
            open_copilot_panel(page)
            input_box = find_input_box(page)
        if not input_box:
            turn_results.append({
                "turn": turn_num,
                "user": turn_text,
                "reply": "(BLOCKED: could not find input box)",
                "result": "BLOCKED",
            })
            continue

        # Send message
        try:
            input_box.click()
            input_box.fill(turn_text)
            page.wait_for_timeout(300)
            input_box.press("Enter")
        except Exception as e:
            turn_results.append({
                "turn": turn_num,
                "user": turn_text,
                "reply": f"(BLOCKED: send failed - {e})",
                "result": "BLOCKED",
            })
            continue

        # Wait and capture reply
        t0 = time.time()
        reply = wait_for_agent_response(page, turn_num, case_id)
        elapsed_ms = int((time.time() - t0) * 1000)

        # Take screenshot
        ss_path = screenshot_dir / f"{case_key}_t{turn_num:02d}.png"
        try:
            page.screenshot(path=str(ss_path), full_page=False)
        except Exception:
            ss_path = None

        # Check for draft
        draft_indicators = [
            "[class*='draft']", "[class*='Draft']",
            "[data-testid*='draft']",
            ":has-text('草稿')", ":has-text('待确认')", ":has-text('Draft')",
        ]
        this_turn_draft = False
        for sel in draft_indicators:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    this_turn_draft = True
                    draft_text = el.inner_text()[:500]
                    draft_created = True
                    break
            except Exception:
                pass

        # Determine result (basic heuristic, investigators will refine)
        result = "PASS"
        bugs = []

        # Check for obvious failures
        if not reply or reply.startswith("("):
            result = "FAIL"
            bugs.append("Could not extract agent reply")
        elif len(reply) < 10:
            result = "FAIL"
            bugs.append("Reply suspiciously short")

        # Case-specific checks
        if case_key == "04" and turn_num == 5:
            # Turn 5 must ONLY be about Sunday morning shift, not E17
            if "E17" in reply and "周三" in reply:
                result = "FAIL"
                bugs.append("BUG-B: History contamination - Turn 5 still mentions E17/Wed after topic switch")

        if case_key == "08":
            # Should NOT create a draft (H01 violation)
            if turn_num == 8 and this_turn_draft:
                result = "FAIL"
                bugs.append("BUG-M: H01 Protected Rule violated - illegal draft created")

        print(f"    => {result} | {elapsed_ms}ms | draft={this_turn_draft}")
        if bugs:
            for b in bugs:
                print(f"    BUG: {b}")

        turn_results.append({
            "turn": turn_num,
            "user": turn_text,
            "reply": reply[:2000],  # truncate for JSON
            "reply_length": len(reply),
            "elapsed_ms": elapsed_ms,
            "screenshot": str(ss_path) if ss_path else None,
            "draft_created_this_turn": this_turn_draft,
            "result": result,
            "bugs": bugs,
        })

    # Cancel any draft to clean up
    cancelled = cancel_draft_if_exists(page)
    if cancelled:
        print(f"  [OK] Draft cancelled for {case_id}")

    # Overall case result
    failed_turns = [t for t in turn_results if t["result"] == "FAIL"]
    blocked_turns = [t for t in turn_results if t["result"] == "BLOCKED"]
    if blocked_turns and len(blocked_turns) == len(turn_results):
        overall = "BLOCKED"
    elif failed_turns:
        overall = "FAIL"
    else:
        overall = "PASS"

    return {
        "case_id": case_id,
        "case_key": case_key,
        "description": case["description"],
        "turns": turn_results,
        "draft_created": draft_created,
        "draft_text_sample": draft_text[:500] if draft_text else "",
        "overall_result": overall,
        "failed_turn_count": len(failed_turns),
        "blocked_turn_count": len(blocked_turns),
        "total_turns": len(turn_results),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", required=True,
                        help="Case keys to run, e.g. 00 01 02")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    cases_to_run = [(k, ALL_CASES[k]) for k in args.cases if k in ALL_CASES]
    if not cases_to_run:
        print(f"No valid cases found in: {args.cases}")
        sys.exit(1)

    print(f"Running cases: {[c[0] for c in cases_to_run]}")
    print(f"Target URL: {URL}")
    print(f"Output: {args.output}")

    all_results = []
    start_time = datetime.datetime.utcnow().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()

        # Navigate to URL
        print(f"\nNavigating to {URL}...")
        try:
            page.goto(URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            print("Page loaded OK")
        except Exception as e:
            print(f"Failed to load page: {e}")
            sys.exit(1)

        # Open copilot
        open_copilot_panel(page)
        page.wait_for_timeout(2000)

        # Take initial screenshot
        page.screenshot(path=str(SCREENSHOT_DIR / "00_initial_page.png"))

        # Run each case
        for case_key, case_data in cases_to_run:
            result = run_case(page, case_key, case_data, SCREENSHOT_DIR)
            all_results.append(result)

            # Brief pause between cases
            page.wait_for_timeout(2000)

        browser.close()

    end_time = datetime.datetime.utcnow().isoformat()

    output = {
        "run_start": start_time,
        "run_end": end_time,
        "url": URL,
        "cases_ran": [c[0] for c in cases_to_run],
        "results": all_results,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"DONE. Results written to {args.output}")
    total = len(all_results)
    passed = sum(1 for r in all_results if r["overall_result"] == "PASS")
    failed = sum(1 for r in all_results if r["overall_result"] == "FAIL")
    blocked = sum(1 for r in all_results if r["overall_result"] == "BLOCKED")
    print(f"  Total: {total} | PASS: {passed} | FAIL: {failed} | BLOCKED: {blocked}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
