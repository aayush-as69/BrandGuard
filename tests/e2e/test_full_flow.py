"""One real-browser pass through the whole product in accounts mode: create people, write, revise, submit, approve, sign out."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
ADMIN, PW = "boss@example.com", "correct-horse-battery"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, BRANDGUARD_DB=str(tmp_path_factory.mktemp("flow") / "f.db"), PORT=str(port), BRANDGUARD_LLM="off",
               BRANDGUARD_AUTH="accounts", BRANDGUARD_ADMIN_EMAIL=ADMIN, BRANDGUARD_ADMIN_PASSWORD=PW)
    env.pop("BRANDGUARD_ENV", None)
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        pg = browser.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "401" not in m.text and "403" not in m.text else None)
        pg.on("dialog", lambda d: d.accept())
        pg.goto(server)
        yield pg
        browser.close()


def sign_in(pg, email, password=PW):
    pg.fill("#email", email)
    pg.fill("#password", password)
    pg.click("#signin button[type=submit]")
    pg.wait_for_selector("#acct:not(.hidden)")


def sign_out(pg):
    pg.click("#signout")
    pg.wait_for_selector("#signin:not(.hidden)")


def test_account_to_approval_and_logout(page):
    pg = page
    # admin: load the knowledge base, add a writer and a manager
    sign_in(pg, ADMIN)
    pg.click("#nav [data-tab=kb]")
    pg.click("text=Load Brewline demo knowledge base")
    pg.wait_for_selector("text=G-01", timeout=10000)
    pg.click("#nav [data-tab=users]")
    for name, email, role in (("Wendy Writer", "wendy@brewline.in", "creator"), ("Mo Manager", "mo@brewline.in", "manager")):
        pg.fill("#newuser [name=name]", name)
        pg.fill("#newuser [name=email]", email)
        pg.select_option("#newuser [name=role]", role)
        pg.fill("#newuser [name=password]", PW)
        pg.click("#newuser button[type=submit]")
        pg.wait_for_selector(f"text={email}")
    sign_out(pg)

    # writer: draft, see findings, revise, submit
    sign_in(pg, "wendy@brewline.in")
    assert not pg.locator("#nav [data-tab=users]").is_visible()  # a writer has no Users screen
    pg.click("text=New")
    pg.fill("#nt", "Launch email")
    pg.fill("#nb", "Hi Dude, our cheap Signature Blend is great!!")
    pg.click("text=Review now")
    pg.wait_for_selector("mark", timeout=10000)
    pg.click("summary:has-text('Edit the text myself')")
    pg.fill("#rb", "Hello, our affordable Signature Blend is great.")
    pg.click("text=Save as new version")
    pg.wait_for_selector("text=version 2", timeout=10000)
    pg.click("text=Submit for approval")
    pg.wait_for_selector(".chip:has-text('In review')", timeout=10000)
    sign_out(pg)

    # manager: approve
    sign_in(pg, "mo@brewline.in")
    pg.locator(".item", has_text="Launch email").click()
    pg.click("button:has-text('Approve')")
    pg.wait_for_selector(".chip:has-text('Approved')", timeout=10000)
    sign_out(pg)
    assert pg.locator("#nav").is_hidden()
    assert not pg.errors, pg.errors
