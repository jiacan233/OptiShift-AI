import os
import sys
import json
import time
from playwright.sync_api import sync_playwright, TimeoutError

URL = "https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/"

CASES = [
    {
        "id": "Case 00",
        "turns": [
            "E02这周为啥没排班？",
            "我想把E02排进去，你有什么建议吗？",
            "如果尽量少改其他人，你建议把他放哪？",
            "那就重新排，把E02排进本周。",
            "周二。",
            "晚班。",
            "先别生成，再加一个条件：E17周三请假。你先分析一下这两个条件一起会怎样。",
            "把你现在理解的两个排班条件复述给我。",
            "可以，就按这两个条件重新排班，生成草稿。"
        ]
    },
    {
        "id": "Case 01",
        "turns": [
            "E02这周为什么一个班都没有？",
            "我想让E02这周上班，你帮我看看放哪里比较合适，先不要改。",
            "如果目标是尽量少改现在的排班，你最推荐哪个班次？为什么？",
            "还有别的方案吗？给我两个候选。",
            "第二个方案具体会影响哪些人？",
            "如果采用第二个方案，再加一个条件：E20周五请假，会怎么样？先分析，不生成。",
            "把你最终准备执行的两个要求列出来，我确认一下。",
            "好，按这两个条件重新排班。"
        ]
    },
    {
        "id": "Case 02",
        "turns": [
            "我想重新排一下本周，把E02安排进去。",
            "就周二。",
            "晚班。",
            "先别生成。你现在理解我要改什么？",
            "再加一个要求，E20周五请假。",
            "这两个条件放一起会影响哪些班次？",
            "尽量少动其他人的班，告诉我你准备怎么改。",
            "现在按E02周二晚班上班+E20周五请假重新排班。"
        ]
    },
    {
        "id": "Case 03",
        "turns": [
            "看一下这周哪些班次比较适合再放一个人进去？",
            "如果是E02呢？",
            "给我两个不同的调整方案，先不要生成。",
            "第二个方案为什么这么调？",
            "第二个方案如果再加E11周四晚班优先，会怎么样？",
            "先做反事实分析，看两个要求一起能不能满足所有硬约束。",
            "把你准备使用的两个变更条件和目标周复述给我。",
            "可以，按第二个方案加上E11周四晚班优先，重新排班。"
        ]
    },
    {
        "id": "Case 04",
        "turns": [
            "如果E17周三请假，会有什么影响？",
            "给我两个解决建议。",
            "第二条为什么？",
            "先别改，我只是分析。",
            "换个问题：周日早班为什么安排现在这些人？",
            "那E02这周为什么没排班？",
            "好，现在回到调整：E17周三请假，同时把E02放到周二晚班。先分析这两个要求。",
            "没问题的话，就按这两个条件重新排。"
        ]
    },
    {
        "id": "Case 05",
        "turns": [
            "周二晚班现在是什么情况？",
            "我感觉这班人不少，那如果把E02塞进去会怎么样？",
            "那如果是周四早班呢？",
            "先别动。我还希望E11周四晚上优先上。",
            "你对比一下：E02周二晚班+E11周四晚班优先，跟现在不改有什么区别？",
            "预计主要会换掉谁？",
            "如果所有硬约束都能满足，就尽量少动其他人。",
            "需要重新排班：把E02排进周二晚班，同时E11周四晚班优先。"
        ]
    },
    {
        "id": "Case 06",
        "turns": [
            "E02这周现在是什么排班情况？",
            "如果让E02周二晚班上，会有什么影响？",
            "我还希望他周五晚班也优先安排。",
            "先别生成，检查一下这样会不会让E02一周班次太多。",
            "连续工作天数呢？",
            "晚班接第二天早班的规则有没有风险？",
            "把你现在理解的两个条件逐条列出来。",
            "按这两个条件重新排班，尽量少改其他人。"
        ]
    },
    {
        "id": "Case 07",
        "turns": [
            "E17为什么周一不能排？",
            "如果一定让E17周一早班上，会违反什么规则？",
            "有没有完全合规的替代方案？",
            "先不要生成。",
            "另外我还想正常把E02安排到周二晚班。",
            "先一起分析这两个要求：E17周一早班强制上班；E02周二晚班正常上班。不要生成。",
            "我明确授权：只允许突破R08，仅限E17、周一、早班。E02周二晚班必须正常满足所有规则。除此之外不授权任何规则违规。",
            "按刚才两个条件强制生成草稿。"
        ]
    },
    {
        "id": "Case 08",
        "turns": [
            "E02周一现在有班吗？",
            "如果让E02周一早班和晚班都上会怎样？",
            "这会违反哪条规则？",
            "先不要修改。",
            "另外加一个正常条件：E17周三请假。",
            "如果要求E02周一早晚都上，同时E17周三请假，系统能生成吗？",
            "即使我说强制，也不要绕过不可突破规则。你告诉我会怎么处理。",
            "尝试按这两个要求生成；H01不可突破就必须明确拒绝，不能产生非法Draft。"
        ]
    },
    {
        "id": "Case 09",
        "turns": [
            "这周有什么可以优化的地方？",
            "如果想把E02加入排班，你建议怎么调？",
            "先分析：E02周二晚班上班，E17周三请假。",
            "好，就按这两个条件重新排班。",
            "这版具体改了哪些人？",
            "确认。",
            "现在这版到底是正式排班还是待确认草稿？",
            "我现在再要求E20周五请假并重新排一次，可以吗？"
        ]
    },
    {
        "id": "Case 10",
        "turns": [
            "我现在工作台看的是哪一周？",
            "下周有没有正式排班？",
            "回到本周，E02为什么没有排班？",
            "如果是下周，我想让E02周二晚班优先。",
            "再加一个条件，下周E20周三请假。",
            "先分析下周这两个条件一起是否可行。",
            "把你目标周、员工、日期、班次、两个条件完整复述一次。",
            "好，为下周按这两个条件生成排班草稿。"
        ]
    }
]

def run_tests():
    report = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        print(f"Navigating to {URL}...")
        try:
            page.goto(URL, timeout=30000)
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Failed to load page: {e}")
            sys.exit(1)

        print("Page loaded successfully.")
        
        # Open Copilot Panel
        try:
            ai_btn = page.get_by_role("button", name="问问 AI")
            if ai_btn.is_visible():
                ai_btn.click()
            page.wait_for_selector('role=dialog[name="OptiShift Copilot 智能排班助手"]', timeout=5000)
            print("Copilot panel opened.")
        except Exception as e:
            print(f"Error opening panel: {e}")
            page.screenshot(path="error_panel.png")

        for c in CASES:
            print(f"--- Running {c['id']} ---")
            results = []
            try:
                # Start new conversation
                new_chat_btn = page.get_by_role("button", name="新对话")
                if new_chat_btn.is_visible():
                    new_chat_btn.click()
                    time.sleep(1)
                
                input_box = page.get_by_role("textbox", name="排班消息")
                for i, turn in enumerate(c["turns"]):
                    print(f"  Turn {i+1}: {turn}")
                    input_box.fill(turn)
                    input_box.press("Enter")
                    
                    # Wait for agent to start streaming (by waiting for a response)
                    # wait for stream to end by looking at the submit button or some loading state
                    # since I don't know the exact loading indicator, I will wait for network idle or a specific time
                    try:
                        # try to wait for response
                        with page.expect_response("**/messages/stream", timeout=15000) as response_info:
                            pass
                        # Wait for streaming to finish, maybe networkidle
                        page.wait_for_timeout(3000) 
                    except Exception as e:
                        print(f"  Turn {i+1} timeout or error: {e}")
                        results.append(f"Turn {i+1}: ERROR")
                        break
                    
                    results.append(f"Turn {i+1}: OK")
            except Exception as e:
                print(f"Case failed: {e}")
                results.append("FAILED")
            
            report.append({"id": c["id"], "results": results})
            # cancel draft if any
            try:
                cancel_btn = page.get_by_role("button", name="取消草稿")
                if cancel_btn.is_visible():
                    cancel_btn.click()
                    time.sleep(1)
            except:
                pass
            
        print("Tests complete.")
        browser.close()
        
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    run_tests()
