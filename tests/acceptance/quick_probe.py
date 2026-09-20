# -*- coding: utf-8 -*-
"""Quick probe: bypass redirect, open AI panel, dump HTML + screenshot."""
from playwright.sync_api import sync_playwright
import json, pathlib, time

URL = "https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/"
SS  = pathlib.Path("tests/acceptance/screenshots")
SS.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(ignore_https_errors=True,
                              viewport={"width":1440,"height":900}, locale="zh-CN")
    page = ctx.new_page()

    # Step 1: load page
    page.goto(URL, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=20000)
    page.screenshot(path=str(SS/"p1_loaded.png"))
    print("Step1 title:", page.title())
    print("Step1 buttons:", [b.inner_text().strip() for b in page.query_selector_all("button")])

    # Step 2: bypass redirect (click confirm if present)
    submit = page.query_selector("#submitBtn")
    if submit and submit.is_visible():
        submit.click()
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(2)
        page.screenshot(path=str(SS/"p2_after_redirect.png"))
        print("Step2 (after redirect) title:", page.title())

    # Step 3: open AI panel
    ai_btn = page.query_selector('[aria-label="打开 AI 助手"]')
    print("AI btn found:", ai_btn is not None)
    if ai_btn:
        ai_btn.click()
        time.sleep(3)
        page.screenshot(path=str(SS/"p3_panel_open.png"))

    # Step 4: dump full body HTML
    html = page.evaluate("document.body.innerHTML")
    pathlib.Path("tests/acceptance/results/panel_html_v2.txt").write_text(html, encoding="utf-8")
    print(f"HTML length: {len(html)}")

    # Step 5: list all visible textareas and inputs
    print("=== TEXTAREAS ===")
    for ta in page.query_selector_all("textarea"):
        print(" PH:", ta.get_attribute("placeholder"), "| class:", (ta.get_attribute("class") or "")[:80], "| visible:", ta.is_visible())
    print("=== INPUTS ===")
    for inp in page.query_selector_all("input"):
        print(" PH:", inp.get_attribute("placeholder"), "| type:", inp.get_attribute("type"), "| visible:", inp.is_visible())
    print("=== CONTENTEDITABLE ===")
    for ce in page.query_selector_all("[contenteditable]"):
        print(" CE:", ce.get_attribute("contenteditable"), "| class:", (ce.get_attribute("class") or "")[:80], "| visible:", ce.is_visible())
    print("=== BUTTONS (first 20) ===")
    for b in page.query_selector_all("button")[:20]:
        txt = b.inner_text().strip()[:40]
        aria = b.get_attribute("aria-label") or ""
        print(f"  [{txt}] aria=[{aria}] visible={b.is_visible()}")

    browser.close()
print("Done")
