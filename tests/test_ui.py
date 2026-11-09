"""The UI must pass the accessibility rule it enforces on others (G-06: 4.5:1), and escape server values."""
import re
from pathlib import Path

from brandguard.engine import contrast_ratio

STATIC = Path(__file__).resolve().parent.parent / "static"
JS_FILES = sorted((STATIC / "js").glob("*.js"))
JS = "\n".join(f.read_text(encoding="utf-8") for f in JS_FILES)
# markup, styles and script together: most UI tests check the page as a whole
HTML = "\n".join((STATIC / n).read_text(encoding="utf-8") for n in ("index.html", "style.css")) + "\n" + JS


def palette():
    return dict(re.findall(r"--([\w-]+):(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))(?![0-9a-fA-F])", HTML))


# Colours that appear only as literals in the CSS (chips, marks, diffs, quotes), keyed by what they sit behind.
CHIP_BG = {"#17304a": "#8fd8ff", "#232d49": "#b4bfd8", "#3b2f14": "amber", "#3d1d29": "red", "#123626": "green", "#2a2450": "violet"}
SURFACE_BG = ("#0f2230", "#0a1122", "#1b2746")


def test_every_text_and_background_pair_meets_4_5_to_1():
    p = palette()
    surfaces = [p["bg"], p["card"], p["sunk"], p["raised"]]
    pairs = [(p["ink"], s) for s in surfaces] + [(p["mute"], s) for s in surfaces]
    pairs += [(p[c], s) for c in ("accent", "green", "amber", "red", "violet") for s in (p["card"], p["sunk"])]
    pairs += [(p["accent-ink"], p["accent"]), ("#06260f", p["green"]), ("#2a0709", p["red"]), (p["bg"], p["ink"])]  # buttons, toasts
    pairs += [(fg if fg.startswith("#") else p[fg], bg) for bg, fg in CHIP_BG.items()]
    pairs += [(p["ink"], bg) for bg in ("#6b2437", "#5e4915", "#33406a")]          # highlighted text in a review
    pairs += [("#ffd0d0", "#552030"), ("#c2f5da", "#14442f"), (p["accent"], "#0f2230"), (p["ink"], "#0f2230"), ("#cfe7ff", "#1b2746"),
              (p["ink"], "#0a1122"), ("#7f8ba8", p["sunk"])]                       # diff, quote, code, placeholder
    failures = [(fg, bg, round(contrast_ratio(fg, bg), 2)) for fg, bg in pairs if contrast_ratio(fg, bg) < 4.5]
    assert not failures, failures
    for literal in list(CHIP_BG) + list(SURFACE_BG) + ["#6b2437", "#5e4915", "#33406a", "#552030", "#14442f", "#7f8ba8"]:
        assert literal in HTML, literal  # the pairs above really are the ones used in the CSS

def test_server_values_are_escaped_before_reaching_html():
    for raw in ("${f.severity}", "${c.status}", "${x.status}", "${m.role}", "${f.confidence}",
                "${f.decision}", "${h.decision}", "${g.access_level}", "${f.access_level}", "${t.status}"):
        for m in re.finditer(re.escape(raw), HTML):
            before = HTML[max(0, m.start() - 6):m.start()]
            assert before.endswith(("cls(", "esc(")) or "label(" in before, f"unescaped {raw} near: {HTML[m.start()-40:m.end()+10]!r}"
    assert "created_at.slice" not in HTML  # timestamps are shown in the viewer's local time


def test_form_controls_have_accessible_names():
    inputs = re.findall(r"<(?:input|select|textarea)\b[^>]*>", HTML)
    unnamed = [i for i in inputs if "aria-label" not in i and "id=" not in i]
    assert not unnamed, unnamed
    assert 'role="status"' in HTML and "aria-live" in HTML


def test_tour_exists_and_only_calls_real_endpoints(app):
    tour = JS[JS.index("const TOUR=["):JS.index("let TI=0")]
    assert tour.count("{h:") >= 6
    rules = {r.rule for r in app.url_map.iter_rules()}
    for path in re.findall(r"api\('(/api/[a-z/-]+)'", tour):
        assert path in rules, path


def test_page_script_has_no_syntax_errors():
    """The other UI tests read the page as text; this one makes sure the script actually parses."""
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node is not installed")
    assert JS_FILES, "no script files found"
    for f in JS_FILES:
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{f.name}: {r.stderr[:600]}"


def test_page_assets_are_linked_and_served(app):
    c = app.test_client()
    page = c.get("/").get_data(as_text=True)
    for url, kind in (("/static/style.css", "text/css"), ("/static/js/core.js", "javascript")):
        assert f'"{url}"' in page, url
        r = c.get(url)
        assert r.status_code == 200 and kind in r.content_type, (url, r.content_type)
    assert "<style" not in page and "<script>" not in page   # no inline code left in the markup


def test_no_inline_script_and_strict_csp(app):
    import re
    assert not re.search(r"\son[a-z]+\s*=\s*[\"']", HTML), "inline event handler found"
    assert "javascript:" not in HTML
    csp = app.test_client().get("/").headers["Content-Security-Policy"]
    script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert "object-src 'none'" in csp and "frame-ancestors 'none'" in csp



def test_every_script_file_is_linked_once_and_in_dependency_order(app):
    page = app.test_client().get("/").get_data(as_text=True)
    linked = re.findall(r'src="/static/js/([a-z]+\.js)"', page)
    assert sorted(linked) == sorted(f.name for f in JS_FILES) and len(set(linked)) == len(linked)
    assert linked[0] == "core.js" and linked[-1] == "main.js"  # helpers first, dispatch and start-up last
