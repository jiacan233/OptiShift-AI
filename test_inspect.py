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
    
    # Check for CloudBase interstitial
    submit_btn = page.locator('#submitBtn')
    if submit_btn.is_visible():
        print("Handling interstitial page...")
        # wait until button is enabled (countdown ends)
        page.wait_for_function('document.getElementById("submitBtn").disabled === false')
        submit_btn.click()
        page.wait_for_load_state('networkidle')

    time.sleep(2)
    ai_btn = page.get_by_role('button', name='问问 AI')
    if ai_btn.is_visible(): 
        ai_btn.click()
        time.sleep(2)
        
    page.screenshot(path='app_ui_screenshot.png')
    
    html = page.content()
    with open('app_page_source.html', 'w', encoding='utf-8') as f:
        f.write(html)
        
    browser.close()
