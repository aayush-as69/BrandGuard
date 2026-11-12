"""The main review journey through the real UI (demo mode), plus layout checks at the four required widths."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect
ROOT = Path(__file__).resolve().parent.parent.parent
WIDTHS = {"desktop": 1440, "laptop": 1280, "tablet": 768, "mobile": 390}


@pytest.fixture(scope="module")
def demo_server(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, BRANDGUARD_DB=str(tmp_path_factory.mktemp("ui") / "u.db"), PORT=str(port), BRANDGUARD_LLM="off")
    for k in ("BRANDGUARD_ENV", "BRANDGUARD_AUTH"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()


def open_page(p, url, width=1440):
    try:
        browser = p.chromium.launch()
    except Exception as exc:
        pytest.skip(f"Chromium unavailable: {exc}")
    pg = browser.new_page(viewport={"width": width, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "401" not in m.text and "403" not in m.text else None)
    pg.on("dialog", lambda d: (pg.errors.append("native dialog: " + d.message), d.dismiss()))   # the UI must never use alert/confirm/prompt
    pg.goto(url)
    return browser, pg


def overflow(pg):
    return pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def test_landing_to_approval_to_audit_record(demo_server):
    with sync_api.sync_playwright() as p:
        browser, pg = open_page(p, demo_server)
        pg.wait_for_selector("h1:has-text('Check content before it goes live')")
        pg.click("[data-c=demoLogin]")                                         # Try demo
        pg.wait_for_selector("#page-title:has-text('Review content with confidence')")
        assert "No reviews yet" in pg.inner_text("#detail")                   # a deliberate empty state with a call to action
        pg.click("#who")                                                       # the demo user is the manager; seed the knowledge base as admin
        pg.evaluate("async()=>{await api('/api/login',{json:{user_id:4,passcode:''}});await api('/api/kb/seed',{json:{}});"
                    "ME=await api('/api/login',{json:{user_id:2,passcode:''}});await afterLogin()}")
        pg.click("[data-c=showNew] >> nth=0")
        pg.click("[data-c=loadDemo]")
        expect(pg.locator("#nb")).not_to_have_value("")
        pg.click("#rv-go")
        pg.wait_for_selector("mark")
        assert pg.locator(".finding.sel .evidence blockquote").count() == 1   # the first finding is open, with its source quote visible
        assert pg.locator(".finding.sel .diff ins").count() == 1
        assert pg.locator("button:has-text('Approve review')").count() == 0 or pg.locator("button:has-text('Approve review')").is_disabled()
        for _ in range(30):                                                    # decide every finding: accept the fix, or dismiss with a reason
            row = pg.locator(".finding:not(.done) .f-btn").first
            if not row.count():
                break
            row.click()
            accept = pg.locator(".finding.sel button:has-text('Accept fix')")
            if accept.count() and accept.is_enabled():
                accept.click()
            else:
                pg.click(".finding.sel button:has-text('Dismiss')")
                pg.fill(".finding.sel input[placeholder^='Reason']", "Checked with the brand team")
                pg.click(".finding.sel button:has-text('Dismiss with reason')")
            pg.wait_for_selector("#toast:not(.hidden)")
            pg.wait_for_timeout(250)
        pg.wait_for_selector("text=Every finding has a decision")
        pg.click("button:has-text('Submit for approval')")
        pg.wait_for_selector(".chip:has-text('In review')")
        # a dismissed claim means a reviewer, not the author, must approve: switch role and approve
        pg.select_option("#who", "reviewer")
        pg.locator(".item", has_text="Signature Blend").click()                       # switching role returns to the list
        pg.wait_for_selector("button:has-text('Approve review')")
        pg.click("button:has-text('Approve review')")
        pg.wait_for_selector("dialog[open]:has-text('Approve this version?')")
        assert pg.evaluate("document.activeElement.closest('dialog') !== null")      # focus moved into the dialog
        pg.keyboard.press("Escape")                                                   # Escape cancels and returns focus
        pg.wait_for_selector("dialog", state="detached")
        pg.click("button:has-text('Approve review')")
        pg.click("dialog[open] button[type=submit]")
        pg.wait_for_selector(".chip.approved")
        with pg.context.expect_page() as new:
            pg.click("a:has-text('Approval record')")
        assert "Approval record" in new.value.content() or "approved" in new.value.content().lower()
        assert not pg.errors, pg.errors
        browser.close()


@pytest.mark.parametrize("name", list(WIDTHS))
def test_no_horizontal_scroll_on_main_screens(demo_server, name):
    with sync_api.sync_playwright() as p:
        browser, pg = open_page(p, demo_server, WIDTHS[name])
        assert overflow(pg) <= 1, f"landing overflows at {name}"
        pg.click("[data-c=demoLogin]")
        pg.wait_for_selector(".page-head")
        pg.click("[data-c=showNew] >> nth=0")
        pg.click("[data-c=loadDemo]")
        expect(pg.locator("#nb")).not_to_have_value("")
        assert overflow(pg) <= 1, f"new review overflows at {name}"
        pg.click("#rv-go")
        pg.wait_for_selector("mark")
        assert overflow(pg) <= 1, f"workspace overflows at {name}"
        if name == "mobile":                                                   # content comes first, then findings, then the decision
            y = lambda sel: pg.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top")
            assert y("#doc-h") < y("#fl-h") < y("#dec-h")
        for tab in ("kb", "insights"):
            pg.click(f"#nav [data-tab={tab}]")
            pg.wait_for_selector("#page-title")
            assert overflow(pg) <= 1, f"{tab} overflows at {name}"
        assert not pg.errors, pg.errors
        browser.close()
