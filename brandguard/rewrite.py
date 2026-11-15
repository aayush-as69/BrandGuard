"""Three-strength rewrites, each checked before anyone sees it.

A rewrite is the content with a chosen set of suggested fixes applied. Nothing new is invented: every change is
a fix BrandGuard already proposed for an open finding, so every change still has a source.

  minimal   only the fixes needed to be correct and compliant: high-severity, high-confidence, rule-based
  balanced  adds medium-severity fixes (terminology, partial dates)
  full      adds low-severity polish (capitals, exclamation marks)

Low-confidence findings and AI-written suggestions are never part of Minimal, and low-confidence findings are
never applied automatically at all: they need a person.

VALIDATION. Every candidate is reviewed again, from scratch, with the rule checks only (no AI call), and must pass:
  numbers   a number, price or date changes only where an approved fact says so (or an unapproved ranking is removed)
  facts     the rewrite raises no fact finding the original did not already have
  clean     the rewrite raises no new finding of any kind
  support   every approved statement that was supported stays supported
  length    the text did not shrink or grow by more than 25%
  nonempty  something is left
A candidate that fails any check is hidden from the person (`status: "hidden"`), with the reasons kept for admins
and tests. A person can still fix a finding by hand; what they are never offered is an unsafe one-click option.
"""
import re
from collections import Counter
from typing import Optional

from . import engine
from . import workflow as wf
from .db import now
from .errors import Forbidden

STRENGTHS = ("minimal", "balanced", "full")
LABELS = {
    "minimal": ("Minimal", "Only what must be fixed to be correct: wrong facts and unapproved claims."),
    "balanced": ("Balanced", "Adds wording fixes: banned terms, slang and partial dates."),
    "full": ("Full", "Adds polish: capital letters and exclamation marks."),
}
MAX_CHANGE = 0.25
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _eligible(f: dict, strength: str) -> bool:
    if f["decision"] != "open" or f["target"] != "body" or f["span_start"] < 0 or not f["suggested_fix"]:
        return False
    if f["confidence"] == "low":
        return False
    if strength == "minimal":
        return f["severity"] == "high" and f["confidence"] == "high" and not f["ai_generated"]
    if strength == "balanced":
        return f["severity"] in ("high", "medium")
    return True


def _nums(text: str) -> Counter:
    return Counter(n.replace(",", "") for n in _NUM.findall(text or ""))


def _splice(body: str, picks: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """Apply fixes left to right; a fix that overlaps an earlier one is skipped and reported."""
    applied, skipped, end = [], [], -1
    for f in sorted(picks, key=lambda x: (x["span_start"], x["id"])):
        if f["span_start"] < end:
            skipped.append(f)
            continue
        if body[f["span_start"]:f["span_end"]] != f["span_text"]:
            skipped.append(f)
            continue
        applied.append(f)
        end = f["span_end"]
    out, pos = [], 0
    for f in applied:
        out.append(body[pos:f["span_start"]])
        out.append(f["suggested_fix"])
        pos = f["span_end"]
    out.append(body[pos:])
    return "".join(out), applied, skipped


def _key(f) -> tuple[str, str]:
    return (f.source_id, (f.span_text or "").strip().lower())


def validate(kb, original: str, images: list[dict], rewritten: str, applied: list[dict]) -> list[dict]:
    """Run every check. Each result is {id, label, ok, detail}."""
    base = engine.review(kb, original, images, judge=None)
    after = engine.review(kb, rewritten, images, judge=None)
    base_keys = {_key(f) for f in base.findings}
    checks = []

    bad_nums = []
    for f in applied:
        if f["source_type"] == "fact":
            continue                                   # an approved fact may change a number; the "facts" check proves it matches
        added = _nums(f["suggested_fix"]) - _nums(f["span_text"])
        removed = _nums(f["span_text"]) - _nums(f["suggested_fix"])
        # Without an approved fact, a fix may never add a number. It may drop one only when it removes an unapproved claim ("#1").
        if added or (removed and f["category"] != "claim"):
            bad_nums.append(f"{f['span_text']!r} -> {f['suggested_fix']!r}")
    checks.append({"id": "numbers", "label": "Numbers, prices and dates change only where an approved fact says so",
                   "ok": not bad_nums, "detail": "; ".join(bad_nums)})

    new_fact = [f for f in after.findings if f.source_type == "fact" and _key(f) not in base_keys]
    checks.append({"id": "facts", "label": "Nothing in the rewrite contradicts an approved fact",
                   "ok": not new_fact, "detail": "; ".join(f"{f.source_id}: {f.span_text}" for f in new_fact)})

    new_any = [f for f in after.findings if _key(f) not in base_keys]
    checks.append({"id": "clean", "label": "The fixes introduce no new findings",
                   "ok": not new_any, "detail": "; ".join(f"{f.source_id}: {f.span_text}" for f in new_any)})

    def supported(res) -> Counter:
        return Counter(c["source_id"] for c in res.claims if c["status"] == "supported")
    before_s, after_s = supported(base), supported(after)
    lost = [k for k, n in before_s.items() if after_s.get(k, 0) < n]
    checks.append({"id": "support", "label": "Approved statements stay supported",
                   "ok": not lost, "detail": ", ".join(lost)})

    change = abs(len(rewritten) - len(original)) / max(1, len(original))
    checks.append({"id": "length", "label": f"Length changes by no more than {int(MAX_CHANGE * 100)}%",
                   "ok": change <= MAX_CHANGE, "detail": f"{round(change * 100)}% change"})

    checks.append({"id": "nonempty", "label": "The text is not left empty", "ok": bool(rewritten.strip()), "detail": ""})
    return checks


def _change(f: dict) -> dict:
    return {"finding_id": f["id"], "source_id": f["source_id"], "category": f["category"], "severity": f["severity"],
            "from": f["span_text"], "to": f["suggested_fix"], "issue": f["issue"], "ai_generated": bool(f["ai_generated"])}


def _diff_segments(a: str, b: str) -> list[dict]:
    """Word-level segments {op: same|removed|added, text} so the screen can show the change."""
    import difflib
    x, y = re.findall(r"\s+|\S+", a), re.findall(r"\s+|\S+", b)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append({"op": "same", "text": "".join(x[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "removed", "text": "".join(x[i1:i2])})
            if j2 > j1:
                out.append({"op": "added", "text": "".join(y[j1:j2])})
    return out


def build(conn, user: dict, content_id: int, include_hidden: bool = False) -> dict:
    """The three candidate rewrites for the current version, validated. Unsafe candidates are hidden."""
    c = wf.get_content(conn, user, content_id)
    v = wf.current(conn, c)
    visible = wf.visible_sources(conn, user)
    rows = [dict(r) for r in wf.open_findings(conn, c)]
    # A fix that rests on a source this person may not see would reveal it, so it is never offered.
    rows = [r for r in rows if not wf.is_restricted(r, visible)]
    kb = engine.load_kb(conn)
    options, seen = [], {}
    for s in STRENGTHS:
        picks = [f for f in rows if _eligible(f, s)]
        body, applied, skipped = _splice(v["body"], picks)
        name, blurb = LABELS[s]
        opt = {"strength": s, "label": name, "summary": blurb, "changes": [_change(f) for f in applied],
               "skipped": len(skipped), "body": body}
        ids = [f["id"] for f in applied]
        if not applied:
            opt.update(status="none", checks=[], same_as=None)
        else:
            checks = validate(kb, v["body"], v["images"], body, applied)
            ok = all(k["ok"] for k in checks)
            opt.update(checks=checks, status="ok" if ok else "hidden",
                       same_as=seen.get(tuple(ids)))
            if ok:
                opt["diff"] = _diff_segments(v["body"], body)
        if applied:
            seen.setdefault(tuple(ids), s)
        options.append(opt)
    if not include_hidden:
        for o in options:
            if o["status"] == "hidden":
                o.update(body="", changes=[], checks=[{"id": k["id"], "label": k["label"], "ok": k["ok"], "detail": ""} for k in o["checks"]])
    return {"content_id": content_id, "version": c["current_version"],
            "open_findings": len(rows), "options": options}


def apply(conn, user: dict, content_id: int, strength: str, judge_factory=None) -> dict:
    """Apply one validated rewrite as a new version. The candidate is rebuilt and revalidated on the server,
    so a request cannot apply an option that was hidden."""
    if strength not in STRENGTHS:
        raise ValueError("strength must be minimal, balanced or full")
    c = wf.get_content(conn, user, content_id)
    perms = wf.permissions(conn, user, c)
    if c["status"] == "approved":
        raise Forbidden("Approved content is locked")
    if not perms["can_decide"]:
        raise Forbidden("You cannot make decisions on this content right now")
    built = build(conn, user, content_id, include_hidden=True)
    opt = next(o for o in built["options"] if o["strength"] == strength)
    if opt["status"] == "none":
        raise ValueError("This option has no changes to apply")
    if opt["status"] != "ok":
        raise ValueError("This rewrite did not pass its safety checks, so it cannot be applied")
    v = wf.current(conn, c)
    ids = [ch["finding_id"] for ch in opt["changes"]]
    for fid in ids:
        text = next(ch["to"] for ch in opt["changes"] if ch["finding_id"] == fid)
        if not conn.execute("UPDATE findings SET decision='accepted', decision_text=?, decided_by=?, decided_at=? "
                            "WHERE id=? AND decision='open'", (text, user["id"], now(), fid)).rowcount:
            conn.rollback()
            raise ValueError("Someone else already decided one of these findings. Reload and try again.")
    wf.audit(conn, c["id"], user["id"], "rewrite_applied", f"{strength}: {len(ids)} fixes")
    ver = wf._new_version(conn, c, user["id"], opt["body"], [dict(i) for i in v["images"]],
                          f"{opt['label']} rewrite ({len(ids)} fixes)", judge_factory, ai="inherit")
    return {"new_version": ver, "applied": len(ids)}
