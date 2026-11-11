"""Keyboard-only use and accessible names, checked on the screens as rendered (not just the markup)."""
import pytest

from test_full_flow import ADMIN, PW, page, server, sign_in  # noqa: F401  (fixtures)

NAME_JS = """el => {
  const t = s => (s || '').trim();
  if (t(el.getAttribute('aria-label')) || t(el.getAttribute('aria-labelledby'))) return true;
  if (el.id && document.querySelector('label[for="' + el.id + '"]')) return true;
  if (el.closest('label')) return true;
  if (['BUTTON', 'SUMMARY', 'A'].includes(el.tagName) || el.getAttribute('role') === 'button') return t(el.textContent).length > 0;
  return t(el.getAttribute('placeholder')).length > 0 && el.tagName !== 'SELECT';
}"""


def unnamed(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('button,input,select,textarea,summary,[role=button]')]
        .filter(e => !e.closest('.hidden') && e.offsetParent !== null)
        .filter(e => !(%s)(e)).map(e => e.outerHTML.slice(0, 100))""" % NAME_JS)


def test_every_visible_control_has_a_name_on_each_screen(page):
    sign_in(page, ADMIN)
    for tab in ("content", "kb", "insights", "users"):
        page.click(f"#nav [data-tab={tab}]")
        page.wait_for_timeout(500)
        assert unnamed(page) == [], tab
    page.click("#nav [data-tab=content]")
    page.click("text=New")
    assert unnamed(page) == []


def test_keyboard_only_sign_in_and_navigation(page):
    page.focus("#hdr-signin")
    page.keyboard.press("Enter")                       # the header link opens the sign-in page
    page.wait_for_selector("#email")
    page.focus("#email")
    page.keyboard.type(ADMIN)
    page.keyboard.press("Tab")
    page.keyboard.type(PW)
    page.keyboard.press("Enter")                       # submit the form from the keyboard
    page.wait_for_selector("#acct:not(.hidden)")
    page.focus("#nav [data-tab=kb]")
    page.keyboard.press("Enter")
    assert page.locator("#nav [data-tab=kb].on").count() == 1
    seen = set()
    for _ in range(25):                                # Tab never gets stuck: focus keeps moving through real controls
        page.keyboard.press("Tab")
        seen.add(page.evaluate("document.activeElement.outerHTML.slice(0, 80)"))
    assert len(seen) > 5


def test_list_items_and_highlights_work_with_enter_and_space(page):
    sign_in(page, ADMIN)
    page.click("#nav [data-tab=kb]")
    page.click("text=Load Brewline demo knowledge base")
    page.wait_for_selector("text=G-01", timeout=10000)
    page.click("#nav [data-tab=content]")
    page.click("text=New")
    page.fill("#nt", "Kbd")
    page.fill("#nb", "Hi Dude, buy now!!")
    page.click("text=Review now")
    page.wait_for_selector(".item")
    item = page.locator(".item").first
    item.focus()
    assert item.get_attribute("role") == "button" and item.get_attribute("tabindex") == "0"
    page.keyboard.press("Space")
    page.wait_for_selector("mark")
    page.locator("mark").first.focus()
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement !== document.body")
