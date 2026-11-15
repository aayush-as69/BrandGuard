"""Rewrite options through the real UI: tabs, views, safety badges, apply with a confirmation."""
from test_ui_flow import demo_server, expect, open_page, overflow, sync_api  # noqa: F401  (fixtures and helpers)


def test_choose_a_strength_inspect_and_apply(demo_server):
    with sync_api.sync_playwright() as p:
        browser, pg = open_page(p, demo_server)
        pg.click("[data-c=demoLogin]")
        pg.wait_for_selector(".page-head")
        pg.evaluate("async()=>{await api('/api/login',{json:{user_id:4,passcode:''}});await api('/api/kb/seed',{json:{}});"
                    "ME=await api('/api/login',{json:{user_id:1,passcode:''}});await afterLogin()}")
        pg.click("[data-c=showNew] >> nth=0")
        pg.click("[data-c=loadDemo]")
        pg.click("#rv-go")
        card = pg.locator("section[aria-labelledby=rw-h]")
        expect(card).to_be_visible()
        tabs = card.locator("[role=tab]")
        assert tabs.count() == 3
        assert [t.split()[0] for t in tabs.all_inner_texts()] == ["Minimal", "Balanced", "Full"]
        assert card.locator("[role=tab][aria-selected=true]").inner_text().startswith("Minimal")
        assert "₹449" in card.locator(".rw-text").inner_text()                        # Proposed is the default view
        card.get_by_role("button", name="Original").click()
        assert "₹399" in pg.locator("section[aria-labelledby=rw-h] .rw-text").inner_text()
        card.get_by_role("button", name="Changes").click()
        assert pg.locator("section[aria-labelledby=rw-h] .rw-text ins").count() > 0 and pg.locator("section[aria-labelledby=rw-h] .rw-text del").count() > 0
        checks = card.locator(".rw-checks li")
        assert checks.count() == 6 and all("✓" in t for t in checks.all_inner_texts())    # every badge is green on a safe option
        card.get_by_role("tab", name="Full").click()
        assert pg.locator("section[aria-labelledby=rw-h] [role=tab][aria-selected=true]").inner_text().startswith("Full")
        card.get_by_role("button", name="Proposed").click()
        assert "!!!" not in pg.locator("#rwp .rw-text").inner_text()                   # Full also removes the exclamation marks
        assert overflow(pg) <= 1
        card.get_by_role("button", name="Apply full rewrite").click()                  # a confirmation first, never a one-click change
        pg.wait_for_selector("dialog[open]:has-text('Apply the full rewrite?')")
        pg.click("dialog[open] button[type=submit]")
        pg.wait_for_selector("dialog", state="detached")
        pg.wait_for_selector("text=version 2")
        assert "₹449" in pg.locator("#body").inner_text() and "₹399" not in pg.locator("#body").inner_text()
        assert not pg.errors, pg.errors
        browser.close()
