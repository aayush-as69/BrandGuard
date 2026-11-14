"""Rewrite options for a finding, each one checked before it is shown.

A finding already carries one minimal fix. This module offers up to three options at different strengths:

  minimal   change only the flagged words
  balanced  fix everything flagged in the sentence
  full      fix everything flagged in the paragraph

Options come from the rules (always available, no AI key needed) and, when the author asks for it, from the AI
provider (on masked text only). It makes no difference where an option comes from: nothing is shown unless it passes
the same two checks, and nothing is applied until the author clicks.

  Check 1 - no new violation: the rules re-run on the rewritten text. A rewrite must not add a finding that was not
            already there, and it must clear the finding it was offered for.
  Check 2 - facts stay identical: prices, dates, quantities and percentages cannot appear unless they were in the
            original or are the approved value; an approved value or product name in the original cannot disappear.

Check 3 is the diff: every option carries a word-level diff so the author sees exactly what changes.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from typing import Callable, Optional

from . import engine

STRENGTHS = ("minimal", "balanced", "full")
LABELS = {"minimal": "Change only the flagged words", "balanced": "Fix this sentence", "full": "Fix this paragraph"}
MAX_SCOPE = 3000          # characters in the passage handed to a rewriter
_UNIT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?(g|kg|mg|ml|l|oz)\b", re.I)
_PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")


# ---------------------------------------------------------------------------- scopes
def sentence_scope(body: str, start: int, end: int) -> tuple[int, int]:
    for off, text in engine.sentences(body):
        if off <= start < off + len(text):
            lead = len(text) - len(text.lstrip())
            return off + lead, off + len(text.rstrip())
    return start, end


def paragraph_scope(body: str, start: int, end: int) -> tuple[int, int]:
    s = body.rfind("\n\n", 0, start)
    s = 0 if s < 0 else s + 2
    e = body.find("\n\n", end)
    e = len(body) if e < 0 else e
    text = body[s:e]
    lead = len(text) - len(text.lstrip())
    return s + lead, s + len(text.rstrip())


def scopes(body: str, f: dict) -> dict[str, tuple[int, int]]:
    s, e = f["span_start"], f["span_end"]
    return {"minimal": (s, e), "balanced": sentence_scope(body, s, e), "full": paragraph_scope(body, s, e)}


# ---------------------------------------------------------------------------- tidying
def tidy(text: str, begin_fresh: bool) -> str:
    """Clean up the seams left by a deletion. `begin_fresh`: the text starts a sentence, so it starts with a capital."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"^\s*,\s*", "", text)
    text = re.sub(r"([.!?]\s+),\s*", r"\1", text)
    if begin_fresh and text[:1].islower():
        text = text[0].upper() + text[1:]
    return text


# ---------------------------------------------------------------------------- protected facts
def _protected(text: str) -> dict:
    money = {float(m.group(2).replace(",", "")) for m in engine._PRICE.finditer(text)}
    full = engine.find_dates(text)
    dates = {d for _, _, d in full}
    partial = {(mo, dy) for _, _, mo, dy in engine.find_partial_dates(text, [(a, b) for a, b, _ in full])}
    units = {f"{float(m.group(1)):g}{m.group(2).lower()}" for m in _UNIT.finditer(text)}
    percents = {f"{float(m.group(1)):g}%" for m in _PERCENT.finditer(text)}
    return {"money": money, "dates": dates, "partial": partial, "units": units, "percents": percents}


def _approved(kb: engine.KB) -> dict:
    import datetime as dt
    money, dates, partial, terms = set(), set(), set(), set()
    for f in kb.facts:
        data = f["data"]
        if f["kind"] == "price" and "amount" in data:
            money.add(float(data["amount"]))
        if f["kind"] == "date" and "date" in data:
            d = dt.date.fromisoformat(data["date"])
            dates.add(d)
            partial.add((d.month, d.day))
        if f["kind"] != "date":
            terms.update(t.lower() for t in data.get("match", []) + data.get("keywords", []))
    units = {f"{float(m.group(1)):g}{m.group(2).lower()}" for t in terms for m in _UNIT.finditer(t)}
    return {"money": money, "dates": dates, "partial": partial, "units": units, "terms": terms}


def facts_problem(kb: engine.KB, before: str, after: str) -> Optional[str]:
    """Why `after` changes a fact that `before` states, or None when every fact is preserved."""
    old, new, ok = _protected(before), _protected(after), _approved(kb)
    for key in ("money", "dates", "partial", "units"):
        invented = new[key] - old[key] - ok[key]
        if invented:
            return f"it introduces {', '.join(sorted(map(str, invented)))}, which is not in the original or the approved facts"
        lost = (old[key] & ok[key]) - new[key]
        if lost:
            return f"it drops the approved {', '.join(sorted(map(str, lost)))}"
    invented = new["percents"] - old["percents"]
    if invented:
        return f"it introduces {', '.join(sorted(invented))}"
    low_before, low_after = before.lower(), after.lower()
    for term in sorted(ok["terms"]):
        if term in low_before and term not in low_after:
            return f"it drops '{term}', which an approved fact depends on"
    return None


# ---------------------------------------------------------------------------- the checks
def _key(f) -> tuple:
    return (f.source_id, f.category, (f.span_text or "").lower(), f.target)


def _counts(kb: engine.KB, body: str, images: list[dict]) -> Counter:
    res = engine.review(kb, body, [dict(i) for i in images])
    return Counter(_key(f) for f in res.findings)


def check(kb: engine.KB, body: str, images: list[dict], scope: tuple[int, int], new_text: str, target: tuple) -> Optional[str]:
    """None if `new_text` may replace body[scope], otherwise the reason it may not."""
    s, e = scope
    old_text = body[s:e]
    if not new_text.strip():
        return "it is empty"
    if len(new_text) > MAX_SCOPE or new_text.count("\n\n") != old_text.count("\n\n"):
        return "it changes the structure of the passage"
    if new_text == old_text:
        return "it changes nothing"
    new_body = body[:s] + new_text + body[e:]
    before, after = _counts(kb, body, images), _counts(kb, new_body, images)
    added = [k for k in after if after[k] > before[k]]
    if added:
        return f"it would add a new finding ({added[0][0]}: {added[0][2]!r})"
    if not after[target] < before[target]:
        return "it does not fix the finding it was offered for"
    return facts_problem(kb, old_text, new_text)


# ---------------------------------------------------------------------------- building options
def _fixes_within(findings: list[dict], s: int, e: int, skip: set[str]) -> list[dict]:
    return [f for f in findings if f["target"] == "body" and f["span_start"] >= s and f["span_end"] <= e
            and f["decision"] == "open" and f["source_id"] not in skip]


def rules_text(body: str, findings: list[dict], scope: tuple[int, int], skip: set[str]) -> str:
    """The scope's text with every available fix applied. Findings without a fix are left alone, except a
    sentence-opening slang word followed by a comma ("Dude, ..."), which is dropped instead."""
    s, e = scope
    text = body[s:e]
    inside = sorted(_fixes_within(findings, s, e, skip), key=lambda f: f["span_start"], reverse=True)
    deleted_at_start = False
    for f in inside:
        a, b = f["span_start"] - s, f["span_end"] - s
        if f.get("suggested_fix"):
            text = text[:a] + f["suggested_fix"] + text[b:]
        elif a == 0 and f["category"] == "tone" and text[b:b + 1] == ",":
            text, deleted_at_start = text[b + 1:].lstrip(), True
    return tidy(text, begin_fresh=deleted_at_start)


def diff(before: str, after: str) -> list[dict]:
    """Word-level diff: [{"op": "equal|del|ins", "text": ...}]."""
    a, b = re.findall(r"\s+|[^\s]+", before), re.findall(r"\s+|[^\s]+", after)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
            continue
        if i2 > i1:
            out.append({"op": "del", "text": "".join(a[i1:i2])})
        if j2 > j1:
            out.append({"op": "ins", "text": "".join(b[j1:j2])})
    return out


def options(kb: engine.KB, body: str, images: list[dict], finding: dict, findings: list[dict], skip: set[str],
            ai_texts: Optional[dict[str, str]] = None) -> dict:
    """Every option for `finding` that passes the checks. `findings` are the open findings of this version (as
    stored); `skip` are rule or fact codes the viewer may not see, which are never used. `ai_texts` maps a strength
    to wording from the AI provider; it goes through the same checks."""
    if finding["target"] != "body" or finding["span_start"] < 0 or finding["source_id"] in skip:
        return {"options": [], "hidden": 0}
    target = (finding["source_id"], finding["category"], (finding["span_text"] or "").lower(), finding["target"])
    sc = scopes(body, finding)
    shown: list[dict] = []
    seen: set[str] = set()
    hidden = 0
    for strength in STRENGTHS:
        s, e = sc[strength]
        candidates = []
        if strength == "minimal":
            if finding.get("suggested_fix"):
                candidates.append(("rules", finding["suggested_fix"]))
        else:
            candidates.append(("rules", rules_text(body, findings, sc[strength], skip)))
        if ai_texts and strength in ai_texts:
            candidates.append(("ai", ai_texts[strength]))
        for source, text in candidates:
            if text in seen:
                continue
            seen.add(text)
            problem = check(kb, body, images, (s, e), text, target)
            if problem == "it changes nothing":
                continue
            if problem:
                hidden += 1
                continue
            shown.append({"strength": strength, "label": LABELS[strength] + (" (AI wording)" if source == "ai" else ""),
                          "source": source, "start": s, "end": e, "before": body[s:e], "after": text,
                          "diff": diff(body[s:e], text)})
    # two strengths that produce the same final body are one option: keep the smaller scope
    final: list[dict] = []
    bodies: set[str] = set()
    for o in shown:
        new_body = body[:o["start"]] + o["after"] + body[o["end"]:]
        if new_body in bodies:
            continue
        bodies.add(new_body)
        final.append(o)
    return {"options": final, "hidden": hidden}


def validate(kb: engine.KB, body: str, images: list[dict], finding: dict, strength: str, text: str) -> tuple[int, int]:
    """For applying: the client names a strength and sends the wording; the checks run again on the server.
    Returns the (start, end) the text replaces, or raises ValueError."""
    if strength not in STRENGTHS or finding["target"] != "body" or finding["span_start"] < 0:
        raise ValueError("That rewrite does not apply to this finding")
    scope = scopes(body, finding)[strength]
    target = (finding["source_id"], finding["category"], (finding["span_text"] or "").lower(), finding["target"])
    problem = check(kb, body, images, scope, text, target)
    if problem:
        raise ValueError(f"That rewrite was not applied: {problem}.")
    return scope


# ---------------------------------------------------------------------------- AI wording
def ai_texts(rewriter: Callable[[str, list[str], list[str]], str], kb: engine.KB, body: str, finding: dict,
             findings: list[dict], skip: set[str]) -> dict[str, str]:
    """Ask the AI for the balanced and full scopes. `rewriter(passage, rule_texts, issues)` returns the new passage.
    Failures are not fatal: the rule-based options are still shown."""
    out: dict[str, str] = {}
    sc = scopes(body, finding)
    done: dict[tuple[int, int], str] = {}
    for strength in ("balanced", "full"):
        s, e = sc[strength]
        if (s, e) in done:
            continue
        inside = _fixes_within(findings, s, e, skip) or [finding]
        codes = list(dict.fromkeys(f["source_id"] for f in inside))
        rule_texts = [f"{c}: {kb.rules[c]['text']}" for c in codes if c in kb.rules]
        if not rule_texts or len(body[s:e]) > MAX_SCOPE:
            continue
        try:
            done[(s, e)] = rewriter(body[s:e], rule_texts, [f["issue"] for f in inside])
        except Exception:
            continue
        out[strength] = done[(s, e)]
    return out
