"""The guideline learning loop: turn real review decisions and the quality benchmark into suggested changes.

Three kinds of suggestion, each backed by evidence that is shown next to it:

  narrow   a rule or term that people dismiss most of the time ("narrow its wording")
  example  a mistake that keeps repeating ("add a clearer example")
  review   a rule whose precision on the labelled benchmark is low ("flag it for review")

Where the change is mechanical the brand team can apply it with one click: retire a glossary term, approve an
acronym, or add an example to a guideline. Each applied change is stored with what it replaced (so it can be
undone) and the benchmark is run before and after, so the effect is a number. Changes that need a person's
judgement (rewording a rule) are shown as advice, not applied.

Nothing here names a person: it works from counts and the flagged wording, never from who decided.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from typing import Optional

from . import benchmark, engine, llm
from .db import now
from .errors import NotFound

DISPUTED_MIN_DECISIONS = 2
DISPUTED_RATE = 0.5
REPEAT_MIN_FINDINGS = 3
REPEAT_MIN_PIECES = 2
MAX_NOTE = 300


def _term_re(term: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])", re.I)


def _decisions(conn: sqlite3.Connection) -> list[dict]:
    """Real decisions only: a dismissal carried into a later version is not a new decision."""
    return [dict(r) for r in conn.execute(
        "SELECT source_id, source_type, span_text, issue, category, decision, decision_text, suggested_fix, content_id "
        "FROM findings WHERE decision IN ('accepted','edited','dismissed') AND ai_generated=0 "
        "AND decision_reason NOT LIKE '(carried over)%'")]


def _caps_rule(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key='rule_checks'").fetchone()
    return (json.loads(row["value"]).get("all_caps") or {}).get("rule_code") if row else None


def _narrow(conn: sqlite3.Connection, kb: engine.KB) -> list[dict]:
    caps_code = _caps_rule(conn)
    glossary = conn.execute("SELECT id, term, preferred, rule_code FROM glossary").fetchall()
    groups: dict[tuple, Counter] = {}
    for d in _decisions(conn):
        key = None
        for g in glossary:
            if g["rule_code"] == d["source_id"] and _term_re(g["term"]).search(d["span_text"]):
                key = ("term", g["id"], g["term"], g["rule_code"])
                break
        if key is None and d["source_id"] == caps_code and re.fullmatch(r"[A-Z]{3,}", d["span_text"] or ""):
            key = ("caps", d["span_text"], d["span_text"], d["source_id"])
        if key is None:
            key = ("rule", d["source_id"], d["source_id"], d["source_id"])
        groups.setdefault(key, Counter())["fixed" if d["decision"] != "dismissed" else "dismissed"] += 1
    out = []
    for (kind, ident, label, code), c in groups.items():
        total = c["fixed"] + c["dismissed"]
        if total < DISPUTED_MIN_DECISIONS or c["dismissed"] / total < DISPUTED_RATE:
            continue
        evidence = {"dismissed": c["dismissed"], "fixed": c["fixed"], "dismissal_rate": round(c["dismissed"] / total, 2)}
        base = {"type": "narrow", "code": code, "evidence": evidence}
        pct = f"{c['dismissed']} of {total} decisions"
        if kind == "term":
            out.append({**base, "id": f"narrow:term:{ident}", "title": f"Retire the glossary term '{label}'",
                        "why": f"People dismissed it in {pct}. A term that is mostly overridden is probably not a real rule.",
                        "apply": {"kind": "retire_term", "term_id": ident}})
        elif kind == "caps":
            out.append({**base, "id": f"narrow:caps:{ident}", "title": f"Allow '{label}' in capitals",
                        "why": f"People dismissed it in {pct}. It is probably an acronym, not emphasis.",
                        "apply": {"kind": "allow_caps", "tokens": [label]}})
        elif ident in kb.rules or any(f["code"] == ident for f in kb.facts):
            out.append({**base, "id": f"narrow:rule:{ident}", "title": f"Narrow the wording of {ident}",
                        "why": f"People dismissed findings from {ident} in {pct}. Say more exactly when it applies, "
                               "or when an exception is fine. Rewording needs a person, so this one is advice only.",
                        "apply": None})
    return out


def _example(conn: sqlite3.Connection, kb: engine.KB) -> list[dict]:
    out = []
    repeats = conn.execute(
        "SELECT source_id, COUNT(*) n, COUNT(DISTINCT content_id) pieces FROM findings "
        "WHERE version=1 AND source_type='guideline' AND ai_generated=0 GROUP BY source_id").fetchall()
    for r in repeats:
        code = r["source_id"]
        if code not in kb.rules or r["n"] < REPEAT_MIN_FINDINGS or r["pieces"] < REPEAT_MIN_PIECES:
            continue
        pairs: Counter = Counter()
        shown: dict[tuple, str] = {}
        for f in conn.execute(
                "SELECT span_text, suggested_fix, decision, decision_text FROM findings "
                "WHERE source_id=? AND source_type='guideline' AND ai_generated=0 AND category NOT IN ('accessibility','visual')", (code,)):
            fix = f["decision_text"] if f["decision"] in ("accepted", "edited") else f["suggested_fix"]
            span = (f["span_text"] or "").strip()
            if not fix or not span or len(span) > 60 or len(fix) > 60 or span.lower() == fix.lower():
                continue
            if llm.redact(span + " " + fix)[1]:  # an email, amount or phone number: never copy it into a guideline
                continue
            pairs[(span.lower(), fix.strip())] += 1
            shown.setdefault((span.lower(), fix.strip()), span)
        text = kb.rules[code]["text"].lower()
        for (span, fix), n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0])):
            note = f'Example: write "{fix}" instead of "{shown[(span, fix)]}".'
            if note.lower() in text:
                continue
            out.append({"id": f"example:{code}", "type": "example", "code": code,
                        "title": f"Add a clearer example to {code}",
                        "why": f"{code} flagged {r['n']} first-draft mistakes across {r['pieces']} pieces. "
                               f"The most common fix was '{shown[(span, fix)]}' → '{fix}' ({n} time{'s' if n != 1 else ''}).",
                        "evidence": {"flagged": r["n"], "pieces": r["pieces"], "pair": [shown[(span, fix)], fix], "times": n},
                        "apply": {"kind": "rule_note", "code": code, "note": note}})
            break
    return out


def _review(conn: sqlite3.Connection, kb: engine.KB, run: Optional[dict]) -> list[dict]:
    if not run:
        return []
    caps_code = _caps_rule(conn)
    out = []
    for r in run["result"]["rules"]:
        if not r["review"]:
            continue
        alarms = [n for n in run["result"]["notes"] if n["code"] == r["code"] and n["kind"] == "false_alarm"]
        suggestion = {"id": f"review:{r['code']}", "type": "review", "code": r["code"],
                      "title": f"Review {r['code']}: its false alarms are too frequent",
                      "why": f"On the labelled benchmark {r['code']} was right {round(r['precision'] * 100)}% of the time "
                             f"({r['fp']} false alarm{'s' if r['fp'] != 1 else ''} out of {r['tp'] + r['fp']}). "
                             "Look at the examples below and tighten the rule or its data.",
                      "evidence": {"precision": r["precision"], "recall": r["recall"], "false_alarms": r["fp"],
                                   "examples": [{"case": n["case"], "text": n["text"]} for n in alarms[:4]]},
                      "apply": None}
        tokens = sorted({n["text"] for n in alarms if re.fullmatch(r"[A-Z]{3,}", n["text"] or "")})
        if tokens and r["code"] == caps_code:
            suggestion["apply"] = {"kind": "allow_caps", "tokens": tokens}
            suggestion["title"] = f"Approve {', '.join(tokens)} as acronyms in {r['code']}"
        out.append(suggestion)
    return out


def suggestions(conn: sqlite3.Connection, run: Optional[dict] = None) -> list[dict]:
    kb = engine.load_kb(conn)
    run = run if run is not None else benchmark.latest(conn)
    return _narrow(conn, kb) + _example(conn, kb) + _review(conn, kb, run)


# ------------------------------------------------------------------------- applying
def _settings(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key='rule_checks'").fetchone()
    return json.loads(row["value"]) if row else {}


def _save_settings(conn: sqlite3.Connection, checks: dict) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES ('rule_checks', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(checks),))


def _do(conn: sqlite3.Connection, action: dict) -> tuple[dict, dict, str]:
    """Make the change. Returns (before, after, one-line summary). Raises ValueError if it cannot be made."""
    kind = action["kind"]
    if kind == "retire_term":
        row = conn.execute("SELECT * FROM glossary WHERE id=?", (action["term_id"],)).fetchone()
        if not row:
            raise ValueError("That glossary term no longer exists")
        conn.execute("DELETE FROM glossary WHERE id=?", (row["id"],))
        return {"glossary": dict(row)}, {}, f"Retired glossary term '{row['term']}'"
    if kind == "allow_caps":
        checks = _settings(conn)
        cfg = checks.get("all_caps")
        if not cfg:
            raise ValueError("The capitals check is not set up")
        before = list(cfg.get("allow", []))
        add = [t for t in action["tokens"] if t not in before]
        if not add:
            raise ValueError("Those acronyms are already allowed")
        cfg["allow"] = before + add
        _save_settings(conn, checks)
        return {"allow": before}, {"allow": cfg["allow"], "added": add}, f"Allowed {', '.join(add)} in capitals"
    if kind == "rule_note":
        row = conn.execute("SELECT text FROM rules WHERE code=?", (action["code"],)).fetchone()
        if not row:
            raise ValueError("That rule no longer exists")
        note = (action.get("note") or "").strip()
        if not note or len(note) > MAX_NOTE:
            raise ValueError(f"The example must be 1 to {MAX_NOTE} characters")
        text = row["text"].rstrip() + " " + note
        if len(text) > 4000:
            raise ValueError("That rule is already too long to add to")
        conn.execute("UPDATE rules SET text=? WHERE code=?", (text, action["code"]))
        return {"text": row["text"]}, {"text": text, "note": note}, f"Added an example to {action['code']}"
    raise ValueError("Unknown change")


def apply(conn: sqlite3.Connection, user_id: int, suggestion_id: str, note: Optional[str] = None) -> dict:
    """Apply one suggestion, with the benchmark run before and after. Raises NotFound / ValueError."""
    found = next((s for s in suggestions(conn) if s["id"] == suggestion_id), None)
    if not found:
        raise NotFound("That suggestion no longer applies. Reload the page.")
    if not found["apply"]:
        raise ValueError("This suggestion needs a person's judgement, so it cannot be applied with one click")
    action = dict(found["apply"])
    if note is not None and action["kind"] == "rule_note":
        action["note"] = note
    before = benchmark.run(conn)
    run_before = benchmark.save(conn, user_id, before, f"Before: {found['title']}")
    try:
        b, a, summary = _do(conn, action)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    after = benchmark.run(conn)
    run_after = benchmark.save(conn, user_id, after, f"After: {found['title']}")
    cur = conn.execute(
        "INSERT INTO kb_changes(created_at, user_id, kind, target, summary, before, after, suggestion, run_before, run_after) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now(), user_id, action["kind"], found["code"], summary, json.dumps(b), json.dumps(a), found["id"], run_before, run_after))
    conn.commit()
    return {"change_id": cur.lastrowid, "summary": summary, "compare": benchmark.compare(before, after),
            "run_before": run_before, "run_after": run_after}


def revert(conn: sqlite3.Connection, user_id: int, change_id: int) -> dict:
    row = conn.execute("SELECT * FROM kb_changes WHERE id=?", (change_id,)).fetchone()
    if not row:
        raise NotFound("No such change")
    if row["reverted_at"]:
        raise ValueError("That change was already undone")
    before, after = json.loads(row["before"]), json.loads(row["after"])
    kind = row["kind"]
    if kind == "retire_term":
        g = before["glossary"]
        conn.execute("INSERT INTO glossary(term, preferred, kind, rule_code, note) VALUES (?,?,?,?,?)",
                     (g["term"], g["preferred"], g["kind"], g["rule_code"], g["note"]))
    elif kind == "allow_caps":
        checks = _settings(conn)
        cfg = checks.get("all_caps") or {}
        cfg["allow"] = [t for t in cfg.get("allow", []) if t not in after["added"]]
        checks["all_caps"] = cfg
        _save_settings(conn, checks)
    elif kind == "rule_note":
        current = conn.execute("SELECT text FROM rules WHERE code=?", (row["target"],)).fetchone()
        if not current or current["text"] != after["text"]:
            raise ValueError("The rule was edited after this change, so it cannot be undone automatically. Edit it by hand.")
        conn.execute("UPDATE rules SET text=? WHERE code=?", (before["text"], row["target"]))
    conn.execute("UPDATE kb_changes SET reverted_at=?, reverted_by=? WHERE id=?", (now(), user_id, change_id))
    conn.commit()
    result = benchmark.run(conn)
    run_id = benchmark.save(conn, user_id, result, f"After undo: {row['summary']}")
    return {"summary": row["summary"], "run_after": run_id, "compare": benchmark.compare(
        benchmark.get(conn, row["run_after"])["result"], result)}


def changes(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM kb_changes ORDER BY id DESC LIMIT ?", (limit,)):
        d = {k: r[k] for k in ("id", "created_at", "kind", "target", "summary", "suggestion", "reverted_at")}
        b, a = benchmark.get(conn, r["run_before"]), benchmark.get(conn, r["run_after"])
        d["compare"] = benchmark.compare(b["result"], a["result"]) if b and a else None
        out.append(d)
    return out
