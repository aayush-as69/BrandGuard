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


# Colour pairs that appear as literals beside the tokens (status chips, highlights, diffs, buttons).
CHIP_PAIRS = [("success", "#10291f"), ("warning", "#2e2411"), ("danger", "#361a1f"), ("info", "#112539"),
              ("danger", "#2a1519"), ("muted", "#2a1519"), ("text", "#4a2027"), ("text", "#41330f"), ("text", "#163450"),
              ("#ffd6d9", "#361a1f"), ("#c7f5de", "#10291f"), ("text", "#252d3b"), ("muted", "#252d3b"),
              ("primary-ink", "primary"), ("primary-ink", "primary-hover"), ("#06210f", "success"), ("#06210f", "#6bd6a1"), ("#2a0b0e", "danger"),
              ("#2c2720", "#f3f0e8"), ("#6e1f26", "#f3c9c9")]


def test_every_text_and_background_pair_meets_4_5_to_1():
    p = palette()
    surfaces = [p[k] for k in ("bg", "surface", "elevated", "sunk")]
    pairs = [(p[c], s) for c in ("text", "muted", "link", "success", "warning", "danger", "info") for s in surfaces]
    pairs += [(p["bg"], p["text"])]                                                # toast
    res = lambda v: p.get(v, v)
    pairs += [(res(fg), res(bg)) for fg, bg in CHIP_PAIRS]
    failures = [(fg, bg, round(contrast_ratio(fg, bg), 2)) for fg, bg in pairs if contrast_ratio(fg, bg) < 4.5]
    assert not failures, failures
    for literal in {v for pair in CHIP_PAIRS for v in pair if v.startswith("#")}:
        assert literal in HTML, literal  # the pairs above really are the ones used in the CSS
    for name in ("--bg", "--surface", "--elevated", "--sunk", "--border", "--primary", "--success", "--warning", "--danger", "--info", "--muted", "--text"):
        assert name + ":" in HTML, name  # the semantic tokens exist


def test_severity_never_relies_on_colour_alone():
    assert "SEV={high:['\u25b2','High']" in JS.replace("▲", "\u25b2") and "const sev=" in JS
    assert "</style>" not in HTML and "alert(" not in JS and "confirm(" not in JS and "prompt(" not in JS


def test_form_controls_have_accessible_names():
    inputs = re.findall(r"<(?:input|select|textarea)\b[^>]*>", HTML)
    # Dialog fields are built from one template whose id is paired with a <label for>; a checkbox is named by its wrapping label.
    unnamed = [i for i in inputs if "aria-label" not in i and "id=" not in i and "${common}" not in i and 'type="checkbox"' not in i]
    assert not unnamed, unnamed
    assert 'for="${id}"' in HTML and 'role="status"' in HTML and "aria-live" in HTML


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


def test_no_inline_styles_and_style_src_is_strict(app):
    assert 'style="' not in HTML and "setAttribute('style'" not in HTML  # layout lives in CSS classes
    csp = app.test_client().get("/").headers["Content-Security-Policy"]
    style_src = [d for d in csp.split(";") if d.strip().startswith("style-src")][0]
    assert "'unsafe-inline'" not in style_src
    rec = (STATIC / "record.css").read_text(encoding="utf-8")
    assert "@media print" in rec  # the approval record stays printable on paper


def test_every_data_c_action_is_registered():
    """A button whose data-c has no entry in ACTIONS silently does nothing (it happened with 'Try demo')."""
    import re
    root = STATIC
    js = "\n".join(p.read_text(encoding="utf-8") for p in sorted((root / "js").glob("*.js")))
    used = set(re.findall(r'data-c=["\\\']?([A-Za-z]+)', js + (root / "index.html").read_text(encoding="utf-8")))
    block = re.search(r"const ACTIONS=\{([^}]*)\}", js).group(1)
    registered = {n.strip() for n in block.split(",")}
    assert used - registered == set(), f"data-c actions with no handler: {sorted(used - registered)}"
