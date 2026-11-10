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
    if pg.locator("#email").count() == 0:
        pg.click("#hdr-signin")
    pg.wait_for_selector("#email")
    pg.fill("#email", email)
    pg.fill("#password", password)
    pg.click("#signin button[type=submit]")
    pg.wait_for_selector("#acct:not(.hidden)")


def sign_out(pg):
    pg.click("#signout")
    pg.wait_for_selector("#hdr-signin:not(.hidden)")


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


def test_sign_in_has_its_own_page(page):
    assert page.locator("#email").count() == 0                       # the front page has no form
    page.click("#hdr-signin")
    page.wait_for_selector("#email")
    assert page.url.endswith("/login") and "Sign in" in page.title()
    page.fill("#email", ADMIN); page.fill("#password", "wrong-password-here")
    page.click("#signin button[type=submit]")
    page.locator("#login-err:not(:empty)").wait_for()
    assert page.url.endswith("/login")                                # still on the sign-in page, with the reason shown
    page.fill("#password", PW)
    page.click("#signin button[type=submit]")
    page.wait_for_selector("#acct:not(.hidden)")
    assert "/login" not in page.url                                   # signed in: back at "/"
    page.goto(page.url.rstrip("/") + "/login")                        # opening /login directly while signed in goes to the app
    page.wait_for_selector("#acct:not(.hidden)")
    assert "/login" not in page.url


def test_try_demo_fills_the_sign_in_form_and_signs_in(tmp_path_factory, monkeypatch):
    """Landing 'Try demo' -> /login with the demo account filled in -> signed in as the manager."""
    import threading
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright
    from brandguard.app import create_app
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", ADMIN)
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", PW)
    monkeypatch.setenv("BRANDGUARD_SEED_DEMO", "1")
    monkeypatch.setenv("BRANDGUARD_DEMO_PASSWORD", "brandguard")
    app = create_app(str(tmp_path_factory.mktemp("d") / "d.db"))
    srv = make_server("127.0.0.1", 5081, app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto("http://127.0.0.1:5081/")
            pg.click("text=Try demo")
            pg.wait_for_selector("#email")
            assert pg.input_value("#email") == "arjun@brewline.demo" and pg.input_value("#password") == "brandguard"
            pg.click("#signin button[type=submit]")
            pg.wait_for_selector("#acct:not(.hidden)")
            assert "manager" in pg.inner_text("#acct-name")
            pg.select_option("#demo-role", "reviewer")                    # the role switch in the header
            pg.wait_for_function("document.querySelector('#acct-name').textContent.includes('reviewer')") if False else None
            pg.locator("#acct-name", has_text="reviewer").wait_for()
            pg.select_option("#demo-role", "agency")
            pg.locator("#acct-name", has_text="agency").wait_for()
            b.close()
    finally:
        srv.shutdown()
