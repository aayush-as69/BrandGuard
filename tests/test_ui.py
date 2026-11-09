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
    return dict(re.findall(r"--(\w+):(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))\b", HTML))


def test_every_text_and_background_pair_meets_4_5_to_1():
    p = palette()
    pairs = [  # (text colour, background it is drawn on), taken from the CSS classes
        (p["ink"], p["bg"]), (p["ink"], p["card"]),
        (p["mute"], p["bg"]), (p["mute"], p["card"]), (p["mute"], "#eff4ff"), (p["mute"], "#f8fafc"),
        (p["blue"], p["card"]), (p["blue"], "#eef2ff"), (p["blue"], "#f4f7ff"), ("#ffffff", p["blue"]),
        (p["green"], p["card"]), (p["green"], "#f0fdf4"), ("#ffffff", p["green"]),
        (p["amber"], p["card"]), (p["amber"], "#fff7ed"),
        (p["red"], p["card"]), (p["red"], "#fef2f2"), ("#ffffff", p["red"]),
        (p["purple"], "#f5f3ff"),
        ("#475569", "#f1f5f9"),
        (p["ink"], "#fecaca"), (p["ink"], "#fde68a"), (p["ink"], "#e2e8f0"),
    ]
    failures = [(fg, bg, round(contrast_ratio(fg, bg), 2)) for fg, bg in pairs if contrast_ratio(fg, bg) < 4.5]
    assert not failures, failures
    for bg in ("#eff4ff", "#f8fafc", "#eef2ff", "#f4f7ff", "#f0fdf4", "#fff7ed", "#fef2f2", "#f5f3ff", "#f1f5f9"):
        assert bg in HTML  # the pairs above really are the ones used in the CSS


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
