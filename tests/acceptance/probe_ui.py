# -*- coding: utf-8 -*-
"""UI structure probe - finds the actual selectors used by OptiShift."""
from playwright.sync_api import sync_playwright
import json, pathlib

URL = "https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/"
OUT = pathlib.Path("tests/acceptance/results/ui_structure.json")
SS  = pathlib.Path("tests/acceptance/screenshots")
SS.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(ignore_https_errors=True,
                              viewport={"width":1440,"height":900},
                              locale="zh-CN")
    page = ctx.new_page()
    page.goto(URL, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.screenshot(path=str(SS/"probe_01_initial.png"), full_page=True)

    result = {}
    result["title"] = page.title()
    result["url"] = page.url

    # All buttons
    buttons = []
    for btn in page.query_selector_all("button")[:40]:
        try:
            buttons.append({
                "text": btn.inner_text().strip()[:60],
                "class": (btn.get_attribute("class") or "")[:80],
                "aria":  (btn.get_attribute("aria-label") or "")[:60],
                "id":    (btn.get_attribute("id") or "")[:40],
                "visible": btn.is_visible(),
            })
        except Exception:
            pass
    result["buttons"] = buttons

    # All textareas + inputs
    textareas = []
    for ta in page.query_selector_all("textarea"):
        try:
            textareas.append({
                "placeholder": (ta.get_attribute("placeholder") or "")[:80],
                "class": (ta.get_attribute("class") or "")[:80],
                "id":    (ta.get_attribute("id") or "")[:40],
                "name":  (ta.get_attribute("name") or "")[:40],
                "visible": ta.is_visible(),
            })
        except Exception:
            pass
    result["textareas"] = textareas

    inputs = []
    for inp in page.query_selector_all("input")[:20]:
        try:
            inputs.append({
                "placeholder": (inp.get_attribute("placeholder") or "")[:80],
                "type":  (inp.get_attribute("type") or "")[:20],
                "class": (inp.get_attribute("class") or "")[:80],
                "id":    (inp.get_attribute("id") or "")[:40],
                "visible": inp.is_visible(),
            })
        except Exception:
            pass
    result["inputs"] = inputs

    # Body HTML first 8000 chars
    result["body_html"] = page.evaluate("document.body.innerHTML")[:8000]

    # Try clicking any AI/chat button and re-probe
    clicked = False
    for btn in page.query_selector_all("button")[:40]:
        try:
            txt = btn.inner_text().strip()
            if any(k in txt for k in ["AI", "问", "智能", "助手", "Chat"]):
                btn.click()
                page.wait_for_timeout(2000)
                clicked = True
                break
        except Exception:
            pass

    if clicked:
        page.screenshot(path=str(SS/"probe_02_after_click.png"), full_page=True)
        result["body_html_after_click"] = page.evaluate("document.body.innerHTML")[:8000]
        textareas_after = []
        for ta in page.query_selector_all("textarea"):
            try:
                textareas_after.append({
                    "placeholder": (ta.get_attribute("placeholder") or "")[:80],
                    "class": (ta.get_attribute("class") or "")[:80],
                    "visible": ta.is_visible(),
                })
            except Exception:
                pass
        result["textareas_after_click"] = textareas_after

    browser.close()

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print("Done -", OUT)
