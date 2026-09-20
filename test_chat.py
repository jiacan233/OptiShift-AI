# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright
import time
import sys
import codecs

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)

URL = 'https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/'

CASES = [
    {
        "id": "Case 00",
        "turns": [
            "E02这周为啥没排班？",
            "我想把E02排进去，你有什么建议吗？"
        ]
    }
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, timeout=30000)
    page.wait_for_load_state('networkidle')
    
    # Check for CloudBase interstitial
    submit_btn = page.locator('#submitBtn')
    if submit_btn.is_visible():
        print("Handling interstitial page...")
        page.wait_for_function('document.getElementById("submitBtn").disabled === false')
        submit_btn.click()
        page.wait_for_load_state('networkidle')

    time.sleep(2)
    ai_btn = page.get_by_role('button', name='问问 AI')
    if ai_btn.is_visible(): 
        ai_btn.click()
        time.sleep(2)

    input_box = page.locator('textarea')
    
    for t in CASES[0]["turns"]:
        print(f"User: {t}")
        input_box.fill(t)
        input_box.press('Enter')
        time.sleep(15) # Wait for agent reply
        # capture last response
        responses = page.locator('div.message-agent, p, div').all_inner_texts()
        # The agent responses might not have 'message-agent' class. 
        # Let's just print the last few elements or look at the HTML structure for responses.
        # Let's save html to see chat structure
        with open('chat_source.html', 'w', encoding='utf-8') as f:
            f.write(page.content())
    
    browser.close()
