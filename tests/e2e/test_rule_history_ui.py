"""Admin journey: draft a guideline change, preview it, publish it, then roll it back, all through the real UI."""
from test_ui_flow import demo_server, expect, open_page, overflow, sync_api  # noqa: F401  (fixtures and helpers)

CODE = "G-03"


def test_draft_preview_publish_and_roll_back(demo_server):
    with sync_api.sync_playwright() as p:
        browser, pg = open_page(p, demo_server)
        pg.click("[data-c=demoLogin]")
        pg.wait_for_selector(".page-head")
        pg.evaluate("async()=>{await api('/api/login',{json:{user_id:4,passcode:''}});await api('/api/kb/seed',{json:{}});"
                    "ME=await api('/api/login',{json:{user_id:4,passcode:''}});await afterLogin()}")        # signed in as the admin
        pg.click("#nav [data-tab=kb]")
        pg.wait_for_selector(".kb-tabs")
        pg.click(f"button[aria-label='Version history for {CODE}']")
        pg.wait_for_selector("#pub-h:has-text('Published version 1')")
        # an empty draft is refused inside the page, with the error tied to the field
        pg.fill("#rv-text", "")
        pg.click("button:has-text('Save draft')")
        assert "first" in pg.inner_text("#rv-err") and pg.get_attribute("#rv-text", "aria-invalid") == "true"
        pg.fill("#rv-text", "Describe our pricing as affordable or great value. Never call anything cheap.")
        pg.fill("#rv-note", "Clearer examples")
        pg.click("button:has-text('Save draft')")
        pg.wait_for_selector("#dr-h:has-text('Draft version 2')")
        pg.click("button:has-text('Preview changes')")
        pg.wait_for_selector("#rv-cmp ins")
        assert pg.locator("#rv-cmp del").count() >= 1 and pg.locator("#rv-cmp ins").count() >= 1
        # still version 1 live: nothing has changed for reviews yet
        assert "Published version 1" in pg.inner_text("#pub-h")
        pg.click("button:has-text('Publish version 2')")
        pg.wait_for_selector("dialog[open]:has-text('takes effect immediately')")
        pg.click("dialog[open] button[type=submit]")
        pg.wait_for_selector("#pub-h:has-text('Published version 2')")
        assert pg.locator("#hist-h:has-text('All versions (2)')").count() == 1
        pg.click("button[aria-label='Roll back to version 1']")
        pg.wait_for_selector("dialog[open]:has-text('current version stays in the history')")
        pg.click("dialog[open] button[type=submit]")
        pg.wait_for_selector("#pub-h:has-text('Published version 3')")
        assert pg.locator("#hist-h:has-text('All versions (3)')").count() == 1      # nothing was lost
        assert "Rolled back to version 1" in pg.inner_text("main")
        assert overflow(pg) <= 1
        pg.click("button:has-text('← Knowledge base')")
        pg.wait_for_selector(".kb-tabs")
        assert not pg.errors, pg.errors
        browser.close()
