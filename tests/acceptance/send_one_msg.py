# -*- coding: utf-8 -*-
"""
Send one real message to OptiShift and capture the agent reply DOM structure.
Saves HTML of the chat panel after response for selector analysis.
"""
from playwright.sync_api import sync_playwright
import pathlib, time

URL = "https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/"
SS  = pathlib.Path("tests/acceptance/screenshots")
SS.mkdir(parents=True, exist_ok=True)

MSG = "E02这周为啥没排班？"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(ignore_https_errors=True,
                              viewport={"width":1440,"height":900}, locale="zh-CN")
    page = ctx.new_page()
    page.goto(URL, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=20000)

    # bypass redirect
    sb = page.query_selector("#submitBtn")
    if sb and sb.is_visible():
        sb.click()
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(2)

    # open AI panel
    ai = page.query_selector('[aria-label="打开 AI 助手"]')
    if ai:
        ai.click()
        time.sleep(3)
    
    page.screenshot(path=str(SS/"send1_before.png"))

    # find textarea
    ta = None
    for sel in ["textarea.resize-none", "textarea[class*='resize-none']", "textarea"]:
        for el in page.query_selector_all(sel):
            if el.is_visible():
                ta = el
                break
        if ta:
            break

    if not ta:
        print("ERROR: no textarea found")
        # dump HTML
        pathlib.Path("tests/acceptance/results/send1_html.txt").write_text(
            page.evaluate("document.body.innerHTML"), encoding="utf-8")
        browser.close()
        exit(1)

    print(f"Found textarea: {ta.get_attribute('class')[:80]}")

    # send message
    ta.click()
    ta.fill(MSG)
    time.sleep(0.3)
    ta.press("Enter")
    print(f"Sent: {MSG}")
    page.screenshot(path=str(SS/"send2_sent.png"))

    # wait up to 60s for response - poll for new content
    print("Waiting for reply...")
    for i in range(60):
        time.sleep(1)
        # check if any new text appeared that looks like a reply
        body = page.evaluate("document.body.innerText")
        if len(body) > 200 and ("E02" in body or "排班" in body):
            # wait a bit more for streaming to finish
            time.sleep(5)
            break
        if i % 10 == 0:
            print(f"  waiting... {i}s")

    page.screenshot(path=str(SS/"send3_reply.png"))

    # dump full HTML for selector analysis
    html = page.evaluate("document.body.innerHTML")
    pathlib.Path("tests/acceptance/results/send1_html.txt").write_text(html, encoding="utf-8")
    print(f"HTML saved: {len(html)} chars")

    # try to extract reply
    visible_text = page.evaluate("document.body.innerText")
    print("=== VISIBLE TEXT (last 1000 chars) ===")
    print(visible_text[-1000:])

    # look for message elements
    print("=== DIVS WITH SUBSTANTIAL TEXT ===")
    items = page.evaluate("""
        () => Array.from(document.querySelectorAll('div,p,section,article'))
            .filter(el => el.offsetParent !== null 
                       && el.children.length < 3 
                       && el.innerText 
                       && el.innerText.trim().length > 50
                       && el.innerText.trim().length < 2000)
            .map(el => ({
                tag: el.tagName,
                cls: (el.className||'').substring(0,80),
                role: el.getAttribute('data-role')||'',
                text: el.innerText.trim().substring(0,200)
            }))
            .slice(-8)
    """)
    for it in items:
        print(f"  [{it['tag']}] cls={it['cls']} role={it['role']}")
        print(f"    text={it['text'][:120]}")

    browser.close()
print("Done")
