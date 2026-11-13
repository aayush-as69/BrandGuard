"""Accuracy benchmark for the deterministic checks.

A benchmark CASE is a short piece of text plus the findings a brand manager says it SHOULD produce.
A RUN reviews every case with the current knowledge base and scores the result:

  true positive   an expected finding that BrandGuard raised
  false positive  a finding BrandGuard raised that nobody expected (noise for authors)
  false negative  an expected finding BrandGuard missed (a mistake that would go live)

  precision = TP / (TP + FP)   "when it flags something, how often is it right?"
  recall    = TP / (TP + FN)   "of the real problems, how many does it catch?"

Only the rule-based checks run: no AI call is made, so no text leaves the server.
Every run stores a snapshot of what the checks depend on (glossary, check settings, facts, rule versions),
so two runs can be compared and the change that moved the numbers can be seen.
"""
import json
import sqlite3
from typing import Optional

from . import engine
from . import versions as rv
from .errors import NotFound
from .workflow import now

MAX_CASES = 200
MAX_BODY = 20000
MAX_EXPECTED = 50
MAX_RUNS = 50


def _text(value, what: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError(f"{what} is required")
        return ""
    value = value.strip()
    if required and not value:
        raise ValueError(f"{what} cannot be empty")
    if len(value) > limit:
        raise ValueError(f"{what} is too long (at most {limit} characters)")
    return value


def clean_case(raw, rule_codes: set, fact_codes: set) -> dict:
    """Validate one labelled case. Raises ValueError with a message a person can act on."""
    if not isinstance(raw, dict):
        raise ValueError("Each case must be an object")
    title = _text(raw.get("title"), "Case title", 200)
    body = _text(raw.get("body"), "Case text", MAX_BODY)
    images = raw.get("images", [])
    if not isinstance(images, list) or len(images) > 20 or not all(isinstance(i, dict) for i in images):
        raise ValueError("images must be a list of up to 20 objects")
    expected = raw.get("expected", [])
    if not isinstance(expected, list) or len(expected) > MAX_EXPECTED:
        raise ValueError(f"expected must be a list of up to {MAX_EXPECTED} findings (an empty list means the text should be clean)")
    out = []
    for e in expected:
        if not isinstance(e, dict):
            raise ValueError("Each expected finding must be an object with a source_id")
        sid = _text(e.get("source_id"), "Expected source_id", 40)
        if sid not in rule_codes and sid not in fact_codes:
            raise ValueError(f"Expected finding refers to {sid}, which is not a rule or fact in the knowledge base")
        text = _text(e.get("text", ""), "Expected text", 300, required=False)
        out.append({"source_id": sid, "text": text})
    return {"title": title, "body": body, "images": images, "expected": out}


def add_cases(conn, user_id: int, cases) -> int:
    if not isinstance(cases, list) or not cases:
        raise ValueError("Provide a list of cases")
    have = conn.execute("SELECT COUNT(*) FROM benchmark_cases").fetchone()[0]
    if have + len(cases) > MAX_CASES:
        raise ValueError(f"A benchmark can hold at most {MAX_CASES} cases ({have} already saved)")
    rules = {r["code"] for r in conn.execute("SELECT code FROM rules")}
    facts = {r["code"] for r in conn.execute("SELECT code FROM facts")}
    cleaned = []
    for i, raw in enumerate(cases, 1):
        try:
            cleaned.append(clean_case(raw, rules, facts))
        except ValueError as exc:
            raise ValueError(f"Case {i}: {exc}") from None
    for c in cleaned:
        conn.execute("INSERT INTO benchmark_cases(title, body, images, expected, created_by, created_at) VALUES (?,?,?,?,?,?)",
                     (c["title"], c["body"], json.dumps(c["images"]), json.dumps(c["expected"]), user_id, now()))
    conn.commit()
    return len(cleaned)


def delete_case(conn, case_id: int) -> None:
    if not conn.execute("DELETE FROM benchmark_cases WHERE id=?", (case_id,)).rowcount:
        raise NotFound("No such case")
    conn.commit()


def list_cases(conn) -> list[dict]:
    return [{"id": r["id"], "title": r["title"], "body": r["body"], "images": json.loads(r["images"]),
             "expected": json.loads(r["expected"])} for r in conn.execute("SELECT * FROM benchmark_cases ORDER BY id")]


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def score_case(predicted: list, expected: list[dict]) -> dict:
    """Match raised findings to expected ones, one to one. An expected finding with no text matches any
    finding from that source; with text, the flagged text must contain it (ignoring case), because the
    checks often flag a little more than the key word, for example "a cheap" for "cheap"."""
    pool = [(f.source_id, (f.span_text or "").strip().lower(), f) for f in predicted]
    used: set[int] = set()
    missed, matched = [], []
    tp = 0
    for e in expected:
        want = e.get("text", "").strip().lower()
        hit = next((i for i, (sid, txt, _) in enumerate(pool) if i not in used and sid == e["source_id"] and (not want or want in txt)), None)
        if hit is None:
            missed.append({"source_id": e["source_id"], "text": e.get("text", "")})
        else:
            used.add(hit)
            matched.append(e["source_id"])
            tp += 1
    extra = [{"source_id": sid, "text": f.span_text, "issue": f.issue} for i, (sid, _, f) in enumerate(pool) if i not in used]
    return {"tp": tp, "fp": len(extra), "fn": len(missed), "missed": missed, "extra": extra, "matched": matched}


def snapshot(conn) -> dict:
    """Everything the deterministic checks depend on, so two runs can be compared."""
    codes = [r["code"] for r in conn.execute("SELECT code FROM rules ORDER BY code")]
    for code in codes:
        rv.sync(conn, code)
    conn.commit()
    pub = {r["rule_code"]: r["version"] for r in conn.execute("SELECT rule_code, version FROM rule_versions WHERE status='published'")}
    kb = engine.load_kb(conn)
    return {"rules": {c: pub.get(c) for c in codes},
            "glossary": sorted(f"{g['term']} -> {g['preferred']} ({g['kind']}, {g['rule_code']})" for g in kb.glossary),
            "facts": sorted(f"{f['code']}: {json.dumps(f['data'], sort_keys=True)}" for f in kb.facts),
            "checks": kb.checks}


def run(conn, user_id: int, label: str = "") -> dict:
    label = _text(label, "Label", 120, required=False)
    cases = list_cases(conn)
    if not cases:
        raise ValueError("There are no benchmark cases yet. Add cases or load the demo set first.")
    kb = engine.load_kb(conn)
    snap = snapshot(conn)
    per_case, per_rule = [], {}
    tp = fp = fn = 0
    for c in cases:
        result = engine.review(kb, c["body"], c["images"], judge=None)
        s = score_case(result.findings, c["expected"])
        per_case.append({"case_id": c["id"], "title": c["title"], **{k: v for k, v in s.items() if k != "matched"}})
        tp, fp, fn = tp + s["tp"], fp + s["fp"], fn + s["fn"]
        for e in c["expected"]:
            per_rule.setdefault(e["source_id"], {"tp": 0, "fp": 0, "fn": 0})
        # per-rule counts: matched and missed come from the case; extras are attributed to their source
        for m in s["missed"]:
            per_rule.setdefault(m["source_id"], {"tp": 0, "fp": 0, "fn": 0})["fn"] += 1
        for x in s["extra"]:
            per_rule.setdefault(x["source_id"], {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
        for sid in s["matched"]:
            per_rule[sid]["tp"] += 1
    rules = {k: {**v, "precision": _ratio(v["tp"], v["tp"] + v["fp"]), "recall": _ratio(v["tp"], v["tp"] + v["fn"])} for k, v in sorted(per_rule.items())}
    summary = {"cases": len(cases), "tp": tp, "fp": fp, "fn": fn,
               "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}
    cur = conn.execute("INSERT INTO benchmark_runs(label, created_by, created_at, summary, per_rule, per_case, snapshot) VALUES (?,?,?,?,?,?,?)",
                       (label, user_id, now(), json.dumps(summary), json.dumps(rules), json.dumps(per_case), json.dumps(snap)))
    conn.execute("DELETE FROM benchmark_runs WHERE id NOT IN (SELECT id FROM benchmark_runs ORDER BY id DESC LIMIT ?)", (MAX_RUNS,))
    conn.commit()
    return get_run(conn, cur.lastrowid)


def _run_row(r) -> dict:
    return {"id": r["id"], "label": r["label"], "created_at": r["created_at"], "author": r["author"], "summary": json.loads(r["summary"])}


_RUN_SQL = "SELECT b.*, u.name AS author FROM benchmark_runs b LEFT JOIN users u ON u.id=b.created_by"


def list_runs(conn) -> list[dict]:
    return [_run_row(r) for r in conn.execute(_RUN_SQL + " ORDER BY b.id DESC")]


def get_run(conn, run_id: int) -> dict:
    r = conn.execute(_RUN_SQL + " WHERE b.id=?", (run_id,)).fetchone()
    if not r:
        raise NotFound("No such benchmark run")
    return {**_run_row(r), "per_rule": json.loads(r["per_rule"]), "per_case": json.loads(r["per_case"]), "snapshot": json.loads(r["snapshot"])}


def _list_diff(a: list, b: list) -> dict:
    return {"added": [x for x in b if x not in a], "removed": [x for x in a if x not in b]}


def what_changed(before: dict, after: dict) -> dict:
    """Plain-language differences between the two knowledge-base snapshots."""
    rules = [{"code": c, "from": before["rules"].get(c), "to": v} for c, v in after["rules"].items() if before["rules"].get(c) != v]
    checks = [{"check": k, "from": before["checks"].get(k), "to": after["checks"].get(k)}
              for k in sorted(set(before["checks"]) | set(after["checks"])) if before["checks"].get(k) != after["checks"].get(k)]
    return {"glossary": _list_diff(before["glossary"], after["glossary"]), "facts": _list_diff(before["facts"], after["facts"]),
            "checks": checks, "rule_versions": rules}


def compare(conn, before_id: int, after_id: int) -> dict:
    a, b = get_run(conn, before_id), get_run(conn, after_id)
    rules = {}
    for code in sorted(set(a["per_rule"]) | set(b["per_rule"])):
        rules[code] = {"before": a["per_rule"].get(code), "after": b["per_rule"].get(code)}
    cases_before = {c["case_id"]: c for c in a["per_case"]}
    changed = []
    for c in b["per_case"]:
        old = cases_before.get(c["case_id"])
        if old and (old["fp"], old["fn"]) != (c["fp"], c["fn"]):
            changed.append({"case_id": c["case_id"], "title": c["title"], "before": {"fp": old["fp"], "fn": old["fn"]}, "after": {"fp": c["fp"], "fn": c["fn"]}})
    sa, sb = a["summary"], b["summary"]
    delta = {k: (None if sa[k] is None or sb[k] is None else round(sb[k] - sa[k], 4)) for k in ("precision", "recall")}
    return {"before": _run_row_from(a), "after": _run_row_from(b), "summary": {"before": sa, "after": sb, "delta": delta},
            "rules": rules, "cases_changed": changed, "changes": what_changed(a["snapshot"], b["snapshot"])}


def _run_row_from(run: dict) -> dict:
    return {k: run[k] for k in ("id", "label", "created_at", "author", "summary")}
