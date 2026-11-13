"""Benchmark journey through the real UI: run, read precision and recall, apply an improvement, rerun, compare."""
from test_ui_flow import demo_server, expect, open_page, overflow, sync_api  # noqa: F401  (fixtures and helpers)


def test_run_improve_rerun_compare(demo_server):
    with sync_api.sync_playwright() as p:
        browser, pg = open_page(p, demo_server)
        pg.click("[data-c=demoLogin]")
        pg.wait_for_selector(".page-head")
        assert pg.locator("#nav [data-tab=benchmark]").is_hidden()                  # the manager has no Benchmark tab
        pg.evaluate("async()=>{await api('/api/login',{json:{user_id:4,passcode:''}});await api('/api/kb/seed',{json:{}});"
                    "ME=await api('/api/login',{json:{user_id:4,passcode:''}});await afterLogin()}")
        pg.click("#nav [data-tab=benchmark]")
        pg.wait_for_selector("h2:has-text('No benchmark cases yet')")                # a deliberate empty state
        pg.click("button:has-text('Load demo cases')")
        pg.wait_for_selector("#bm-run")
        pg.click("#bm-run")
        pg.wait_for_selector("#acc-h")
        first = pg.inner_text(".bm-metrics")
        assert "precision" in first.lower() and "recall" in first.lower() and "%" in first
        assert "Before and after" not in pg.inner_text("main")                       # nothing to compare with yet
        # the demo set misses two unlisted slang words; add one to the glossary from the suggestion
        pg.click("button[aria-label='Add lit to the glossary']")
        pg.wait_for_selector("dialog[open]:has-text('changes the live checks')")
        pg.fill("#dlg-preferred", "wonderful")
        pg.click("dialog[open] button[type=submit]")
        pg.wait_for_selector("dialog", state="detached")
        pg.click("#bm-run")
        pg.wait_for_selector("#cmp-h")
        table = pg.inner_text(".bm-table")
        assert "Before change" in table and "After change" in table and "Better" in table
        assert "Glossary term added: lit -> wonderful" in pg.inner_text("main")      # the comparison names the change that moved the numbers
        assert pg.locator("button[aria-label='Add lit to the glossary']").count() == 0   # the miss is gone
        assert pg.locator("button[aria-label='Add dope to the glossary']").count() == 1
        assert overflow(pg) <= 1
        assert not pg.errors, pg.errors
        browser.close()
