"""A measured quality benchmark for the review engine.

`seed/benchmark.json` holds synthetic drafts where a person has labelled every real mistake. Running the benchmark
reviews each draft with the current knowledge base and compares what the engine flagged with the labels:

  * true positive  - a flagged finding that matches a labelled mistake (same rule or fact, same text)
  * false positive - a flagged finding with no matching label (a false alarm)
  * false negative - a labelled mistake the engine did not flag (a miss)

Precision = TP / (TP + FP): how many alarms were right.  Recall = TP / (TP + FN): how many mistakes were found.
Both are reported for every rule and fact. The AI judge is measured separately and only when asked, because it
costs an API call per draft. Nothing here touches real content: the drafts are synthetic.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from . import engine
from .db import now

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_FILE = ROOT / "seed" / "benchmark.json"
LOW_PRECISION = 0.8        # a rule below this (with enough alarms) is flagged for review
MIN_ALARMS = 3             # fewer alarms than this is too little evidence to judge a rule's precision
MAX_NOTES = 60
AI_DRAFTS = 12             # the AI judge is tried on this many drafts: every one with an AI-only mistake, then clean ones


def load_cases(path: Path = BENCHMARK_FILE) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data["cases"]
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Benchmark case ids must be unique")
    return cases


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _same(expected_text: str, found_text: str) -> bool:
    a, b = _norm(expected_text), _norm(found_text)
    return bool(a) and bool(b) and (a in b or b in a)


def _match(expected: list[dict], found: list) -> tuple[list[tuple[dict, object]], list[dict], list]:
    """Pair each labelled mistake with at most one finding. Returns (pairs, missed labels, unmatched findings)."""
    free = list(found)
    pairs, missed = [], []
    for e in expected:
        hit = next((f for f in free if f.source_id == e["source_id"] and _same(e["text"], f.span_text)), None)
        if hit is None:
            missed.append(e)
        else:
            free.remove(hit)
            pairs.append((e, hit))
    return pairs, missed, free


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 3) if den else None


def _ai_subset(cases: list[dict]) -> set[str]:
    chosen = [c["id"] for c in cases if any(e.get("ai") for e in c["expected"])]
    chosen += [c["id"] for c in cases if not c["expected"]]
    return set(chosen[:AI_DRAFTS])


def run(conn: sqlite3.Connection, judge: Optional[Callable] = None, cases: Optional[list[dict]] = None) -> dict:
    """Review every labelled draft and score the result. `judge` adds the AI judge (rule results stay separate);
    it is tried on a subset of the drafts (AI_DRAFTS), because every draft costs one API call."""
    cases = load_cases() if cases is None else cases
    ai_ids = _ai_subset(cases) if judge else set()
    kb = engine.load_kb(conn)
    per: dict[str, dict] = {}
    ai = {"tp": 0, "fp": 0, "fn": 0, "drafts": 0}
    notes: list[dict] = []

    def row(code: str) -> dict:
        return per.setdefault(code, {"code": code, "tp": 0, "fp": 0, "fn": 0})

    for case in cases:
        result = engine.review(kb, case["body"], [dict(i) for i in case.get("images", [])],
                               judge=judge if case["id"] in ai_ids else None)
        rule_found = [f for f in result.findings if not f.ai_generated]
        ai_found = [f for f in result.findings if f.ai_generated]
        rule_labels = [e for e in case["expected"] if not e.get("ai")]
        ai_labels = [e for e in case["expected"] if e.get("ai")]

        pairs, missed, spare = _match(rule_labels, rule_found)
        for e, _ in pairs:
            row(e["source_id"])["tp"] += 1
        for e in missed:
            row(e["source_id"])["fn"] += 1
            notes.append({"case": case["id"], "title": case["title"], "kind": "missed", "code": e["source_id"], "text": e["text"]})
        for f in spare:
            row(f.source_id)["fp"] += 1
            notes.append({"case": case["id"], "title": case["title"], "kind": "false_alarm", "code": f.source_id, "text": f.span_text})

        if judge and case["id"] in ai_ids:
            ai["drafts"] += 1
            # the AI is judged on every finding it adds, against all labels the rules did not already settle
            leftover = ai_labels + missed
            a_pairs, a_missed, a_spare = _match(leftover, ai_found)
            ai["tp"] += len(a_pairs)
            ai["fn"] += len([e for e in a_missed if e.get("ai")])
            ai["fp"] += len(a_spare)

    rules = []
    titles = {c: r["title"] for c, r in kb.rules.items()}
    titles.update({f["code"]: f["statement"] for f in kb.facts})
    for code in sorted(per):
        r = per[code]
        rules.append({**r, "title": titles.get(code, code), "precision": _ratio(r["tp"], r["tp"] + r["fp"]),
                      "recall": _ratio(r["tp"], r["tp"] + r["fn"]),
                      "review": r["tp"] + r["fp"] >= MIN_ALARMS and r["tp"] / (r["tp"] + r["fp"]) < LOW_PRECISION})
    tp, fp, fn = (sum(r[k] for r in rules) for k in ("tp", "fp", "fn"))
    out = {
        "drafts": len(cases), "labels": sum(len(c["expected"]) for c in cases),
        "overall": {"tp": tp, "fp": fp, "fn": fn, "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)},
        "rules": rules, "notes": notes[:MAX_NOTES], "notes_total": len(notes), "ai": None,
    }
    if judge:
        out["ai"] = {**ai, "precision": _ratio(ai["tp"], ai["tp"] + ai["fp"]), "recall": _ratio(ai["tp"], ai["tp"] + ai["fn"])}
    return out


def save(conn: sqlite3.Connection, user_id: Optional[int], result: dict, label: str = "") -> int:
    cur = conn.execute("INSERT INTO benchmark_runs(created_at, user_id, label, with_ai, result) VALUES (?,?,?,?,?)",
                       (now(), user_id, label[:200], 1 if result.get("ai") else 0, json.dumps(result)))
    conn.commit()
    return cur.lastrowid


PENDING = '{"pending": true}'
PENDING_MINUTES = 10


def start_pending(conn: sqlite3.Connection, user_id: Optional[int], label: str) -> int:
    """A run with the AI judge takes a while, so it is recorded first and filled in when it finishes."""
    cur = conn.execute("INSERT INTO benchmark_runs(created_at, user_id, label, with_ai, result) VALUES (?,?,?,1,?)",
                       (now(), user_id, label[:200], PENDING))
    conn.commit()
    return cur.lastrowid


def finish_pending(conn: sqlite3.Connection, run_id: int, result: Optional[dict], failed: str = "") -> None:
    value = json.dumps(result) if result else json.dumps({"failed": failed[:300] or "the run did not finish"})
    conn.execute("UPDATE benchmark_runs SET result=? WHERE id=?", (value, run_id))
    conn.commit()


def pending(conn: sqlite3.Connection) -> Optional[dict]:
    """The AI run in progress, if any (a run that never reported back stops counting after a few minutes)."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=PENDING_MINUTES)).isoformat(timespec="seconds")
    row = conn.execute("SELECT id, created_at FROM benchmark_runs WHERE result=? AND created_at>=? ORDER BY id DESC LIMIT 1",
                       (PENDING, cutoff)).fetchone()
    return dict(row) if row else None


def last_failure(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT result FROM benchmark_runs ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        res = json.loads(row["result"])
        return res.get("failed", "") if isinstance(res, dict) else ""
    return ""


def _finished() -> str:
    return "result NOT LIKE '{\"pending\"%' AND result NOT LIKE '{\"failed\"%'"


def get(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM benchmark_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "created_at": row["created_at"], "label": row["label"], "result": json.loads(row["result"])}


def history(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    out = []
    for r in conn.execute(f"SELECT * FROM benchmark_runs WHERE {_finished()} ORDER BY id DESC LIMIT ?", (limit,)):
        res = json.loads(r["result"])
        out.append({"id": r["id"], "created_at": r["created_at"], "label": r["label"], "with_ai": bool(r["with_ai"]),
                    "precision": res["overall"]["precision"], "recall": res["overall"]["recall"]})
    return out


def latest(conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(f"SELECT id FROM benchmark_runs WHERE {_finished()} ORDER BY id DESC LIMIT 1").fetchone()
    return get(conn, row["id"]) if row else None


def compare(before: dict, after: dict) -> dict:
    """Per-rule and overall change between two stored results (after minus before)."""
    def delta(a, b):
        return None if a is None or b is None else round(b - a, 3)
    old = {r["code"]: r for r in before["rules"]}
    new = {r["code"]: r for r in after["rules"]}
    rules = []
    for code in sorted(set(old) | set(new)):
        o, n = old.get(code, {}), new.get(code, {})
        rules.append({"code": code, "precision_before": o.get("precision"), "precision_after": n.get("precision"),
                      "recall_before": o.get("recall"), "recall_after": n.get("recall"),
                      "precision_change": delta(o.get("precision"), n.get("precision")),
                      "recall_change": delta(o.get("recall"), n.get("recall"))})
    b, a = before["overall"], after["overall"]
    return {"precision_before": b["precision"], "precision_after": a["precision"],
            "recall_before": b["recall"], "recall_after": a["recall"],
            "precision_change": delta(b["precision"], a["precision"]),
            "recall_change": delta(b["recall"], a["recall"]),
            "changed_rules": [r for r in rules if r["precision_change"] or r["recall_change"]]}
