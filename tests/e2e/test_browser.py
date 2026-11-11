"""Real-browser checks (Chromium via Playwright). Skipped when Playwright or a browser is not installed."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, BRANDGUARD_DB=str(tmp_path_factory.mktemp("e2e") / "e.db"), PORT=str(port),
               BRANDGUARD_LLM="off")
    env.pop("BRANDGUARD_ENV", None)
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()


@pytest.fixture()
def page(server):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # no browser binary
            pytest.skip(f"Chromium unavailable: {exc}")
        pg = browser.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "401" not in m.text else None)
        pg.goto(server)
        yield pg
        browser.close()


def test_tour_review_and_keyboard_flow(page):
    page.click("header [data-c=tourStart]")
    page.click("#tour-nx")  # step 0 is the introduction
    for _ in range(2):  # step 1 loads the knowledge base as admin, step 2 drafts the demo email as the agency writer
        page.click("#tour-do")
        page.wait_for_timeout(1000)
        page.click("#tour-nx")
    page.click("button:has-text('Close')")
    page.click("text=Review now")
    page.wait_for_selector("mark", timeout=10000)  # findings are highlighted in the text
    assert page.locator("mark").count() >= 3
    page.locator("mark").first.focus()
    page.keyboard.press("Enter")  # keyboard operable, no inline handlers needed
    assert not page.errors, page.errors


def test_phone_width_has_no_horizontal_scroll(page):
    page.set_viewport_size({"width": 375, "height": 740})
    page.reload()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
