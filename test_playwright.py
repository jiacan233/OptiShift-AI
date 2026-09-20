# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright
import time
import sys
import codecs

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)

URL = 'https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, timeout=30000)
    page.wait_for_load_state('networkidle')
    ai_btn = page.get_by_role('button', name='问问 AI')
    if ai_btn.is_visible(): ai_btn.click()
    page.wait_for_selector('role=dialog', timeout=5000)
    
    input_box = page.locator('input[placeholder*=\"排班\"], textarea[placeholder*=\"排班\"], [role=\"textbox\"]').first
    input_box.fill('E02这周为啥没排班？')
    input_box.press('Enter')
    
    time.sleep(15)
    # capture response
    responses = page.locator('.message-agent, [class*=\"agent\"], [class*=\"response\"]').all_inner_texts()
    print('Responses:', responses)
    browser.close()
