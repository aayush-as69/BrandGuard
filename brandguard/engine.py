"""Review engine: deterministic rule checks first, then an optional grounded LLM judge.

Every finding is validated against the knowledge base before it is returned:
the cited rule or fact must exist, the quote must really appear in it, and the
flagged span must really appear in the content. Anything that fails is dropped
and reported in `rejected`, never shown to a user as if it were real.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import Finding

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]
_MONTHS = {m.lower(): i for i, m in enumerate(MONTH_NAMES, 1)}
_MONTH_RE = "|".join(MONTH_NAMES)


# --------------------------------------------------------------------------- KB
@dataclass
class KB:
    rules: dict[str, dict] = field(default_factory=dict)      # code -> {title, text}
    facts: list[dict] = field(default_factory=list)           # code, kind, statement, data
    glossary: list[dict] = field(default_factory=list)
    checks: dict = field(default_factory=dict)                # check name -> params


def load_kb(conn: sqlite3.Connection) -> KB:
    kb = KB()
    for r in conn.execute("SELECT code, title, text FROM rules"):
        kb.rules[r["code"]] = {"title": r["title"], "text": r["text"]}
    for f in conn.execute("SELECT code, kind, statement, data FROM facts"):
        kb.facts.append(
            {"code": f["code"], "kind": f["kind"], "statement": f["statement"], "data": json.loads(f["data"])}
        )
    kb.glossary = [dict(g) for g in conn.execute("SELECT term, preferred, kind, rule_code, note FROM glossary")]
    row = conn.execute("SELECT value FROM settings WHERE key='rule_checks'").fetchone()
    kb.checks = json.loads(row["value"]) if row else {}
    return kb


# --------------------------------------------------------------------- helpers
def sentences(body: str) -> list[tuple[int, str]]:
    """(offset, text) for every sentence, so findings can point at exact spans."""
    out: list[tuple[int, str]] = []
    for line in re.finditer(r"[^\n]+", body):
        for s in re.finditer(r".+?(?:[.!?]+(?=\s|$)|$)", line.group()):
            if s.group().strip():
                out.append((line.start() + s.start(), s.group()))
    return out


def match_case(original: str, replacement: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def fmt_date(d: dt.date) -> str:
    return f"{d.day} {MONTH_NAMES[d.month - 1]} {d.year}"


def find_dates(text: str) -> list[tuple[int, int, dt.date]]:
    found = []
    patterns = [
        (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})\b", re.I), "dmy"),
        (re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), "mdy"),
        (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    ]
    for rx, kind in patterns:
        for m in rx.finditer(text):
            try:
                if kind == "dmy":
                    d = dt.date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
                elif kind == "mdy":
                    d = dt.date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
                else:
                    d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            found.append((m.start(), m.end(), d))
    return found


def _lum(hex_color: str) -> Optional[float]:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return None

    def chan(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: str, bg: str) -> Optional[float]:
    """WCAG 2.x contrast ratio, or None if either colour is not valid hex."""
    a, b = _lum(fg), _lum(bg)
    if a is None or b is None:
        return None
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def darken_to_pass(fg: str, bg: str, target: float) -> Optional[str]:
    """Darken (or lighten, on dark backgrounds) the text colour until it passes."""
    h = fg.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if _lum(fg) is None or _lum(bg) is None:
        return None
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    toward = 0 if (_lum(bg) or 0) > 0.5 else 255
    for step in range(0, 101):
        t = step / 100
        cand = "#%02X%02X%02X" % tuple(round(c + (toward - c) * t) for c in (r, g, b))
        ratio = contrast_ratio(cand, bg)
        if ratio and ratio >= target:
            return cand
    return None


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


# ------------------------------------------------------------------ verification
def verify(f: Finding, kb: KB, body: str, images: list[dict]) -> Optional[str]:
    """Return None if the finding is trustworthy, otherwise the reason it is rejected."""
    if f.source_type == "guideline":
        rule = kb.rules.get(f.source_id)
        if not rule:
            return f"cited rule {f.source_id} does not exist"
        source_text = rule["text"]
    else:
        fact = next((x for x in kb.facts if x["code"] == f.source_id), None)
        if not fact:
            return f"cited fact {f.source_id} does not exist"
        source_text = fact["statement"]
    if _norm(f.source_quote) not in _norm(source_text):
        return f"quote is not found in {f.source_id}"
    if f.target == "body":
        if f.span_start < 0 or body[f.span_start:f.span_end] != f.span_text or not f.span_text:
            return "flagged span does not match the content"
    else:
        name = f.target.split(":", 1)[1] if ":" in f.target else ""
        if not any(img.get("name") == name for img in images):
            return f"image {name!r} is not in the content"
    return None


# ------------------------------------------------------------------- the checks
@dataclass
class ReviewResult:
    findings: list[Finding] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    llm_status: str = "not used"


def review(
    kb: KB,
    body: str,
    images: list[dict],
    judge: Optional[Callable[[str, KB, list[Finding]], tuple[list[Finding], str]]] = None,
) -> ReviewResult:
    res = ReviewResult()
    raw: list[Finding] = []
    sents = sentences(body)

    def cited(check: str) -> Optional[str]:
        """Rule code a check cites; None (plus a warning) if the KB does not have it."""
        cfg = kb.checks.get(check)
        if not cfg:
            return None
        code = cfg.get("rule_code")
        if code not in kb.rules:
            res.warnings.append(f"Check '{check}' skipped: rule {code} is not in the knowledge base.")
            return None
        return code

    def guideline_finding(code: str, **kw) -> Finding:
        return Finding(source_type="guideline", source_id=code, source_quote=kb.rules[code]["text"], **kw)

    # 1. Glossary: banned terms and slang -------------------------------------
    for g in kb.glossary:
        code = g["rule_code"]
        if code not in kb.rules:
            res.warnings.append(f"Glossary term '{g['term']}' skipped: rule {code} is missing.")
            continue
        for m in re.finditer(rf"(?<![\w-]){re.escape(g['term'])}(?![\w-])", body, re.I):
            tone = g["kind"] == "slang"
            raw.append(guideline_finding(
                code,
                category="tone" if tone else "terminology",
                issue=(f"'{m.group()}' is {'off-tone slang' if tone else 'a banned term'}; "
                       f"use '{g['preferred']}'." + (f" {g['note']}" if g.get("note") else "")),
                span_text=m.group(), span_start=m.start(), span_end=m.end(),
                severity="medium", confidence="high",
                suggested_fix=match_case(m.group(), g["preferred"]),
            ))

    # 2. Punctuation and emphasis -----------------------------------------------
    code = cited("exclamation")
    if code:
        limit = int(kb.checks["exclamation"].get("max", 1))
        runs = list(re.finditer(r"!+", body))
        if runs and (len(runs) > limit or len(runs[0].group()) > 1):
            for i, m in enumerate(runs):
                if i < limit and len(m.group()) == 1:
                    continue
                keep = i < limit
                raw.append(guideline_finding(
                    code, category="tone",
                    issue=f"Too many exclamation marks (the limit is {limit} per email).",
                    span_text=m.group(), span_start=m.start(), span_end=m.end(),
                    severity="low", confidence="high",
                    suggested_fix="!" if keep else ".",
                ))
    code = cited("all_caps")
    if code:
        allow = set(kb.checks["all_caps"].get("allow", []))
        for m in re.finditer(r"\b[A-Z]{3,}\b", body):
            if m.group() in allow:
                continue
            raw.append(guideline_finding(
                code, category="tone",
                issue=f"'{m.group()}' is written in capitals for emphasis.",
                span_text=m.group(), span_start=m.start(), span_end=m.end(),
                severity="low", confidence="high", suggested_fix=m.group().capitalize(),
            ))

    # 3. Claims and facts ---------------------------------------------------------
    claims_code = cited("claims")
    facts_code = cited("facts")
    price_facts = [f for f in kb.facts if f["kind"] == "price"]
    date_facts = [f for f in kb.facts if f["kind"] == "date"]
    claim_facts = [f for f in kb.facts if f["kind"] == "claim"]
    super_facts = [f for f in kb.facts if f["kind"] == "superlative"]

    def fact_finding(fact: dict, **kw) -> Finding:
        return Finding(source_type="fact", source_id=fact["code"], source_quote=fact["statement"], **kw)

    def add_claim(text: str, status: str, source_id: str = "") -> None:
        res.claims.append({"text": text.strip(), "status": status, "source_id": source_id})

    if facts_code:
        for off, sent in sents:
            low = sent.lower()
            # prices
            for m in re.finditer(r"((?:₹|Rs\.?|INR)\s?)(\d(?:[\d,]*\d)?(?:\.\d+)?)", sent):
                amount = float(m.group(2).replace(",", ""))
                cands = [f for f in price_facts if any(t in low for t in f["data"].get("match", []))]
                if not cands and len(price_facts) == 1:
                    cands = price_facts
                if not cands:
                    add_claim(sent, "no_approved_source")
                    continue
                fact = cands[0]
                approved = float(fact["data"]["amount"])
                if amount == approved:
                    add_claim(sent, "supported", fact["code"])
                else:
                    shown = f"{approved:,.0f}" if approved.is_integer() else f"{approved:,.2f}"
                    add_claim(sent, "contradicted", fact["code"])
                    raw.append(fact_finding(
                        fact, category="fact",
                        issue=f"Price is {m.group(0)} but the approved price is {m.group(1)}{shown}.",
                        span_text=m.group(0), span_start=off + m.start(), span_end=off + m.end(),
                        severity="high", confidence="high", suggested_fix=f"{m.group(1)}{shown}",
                    ))
            # dates
            for start, end, d in find_dates(sent):
                for fact in date_facts:
                    if not any(t in low for t in fact["data"].get("match", [])):
                        continue
                    approved = dt.date.fromisoformat(fact["data"]["date"])
                    if d == approved:
                        add_claim(sent, "supported", fact["code"])
                    else:
                        add_claim(sent, "contradicted", fact["code"])
                        raw.append(fact_finding(
                            fact, category="fact",
                            issue=f"Date is {fmt_date(d)} but the approved date is {fmt_date(approved)}.",
                            span_text=sent[start:end], span_start=off + start, span_end=off + end,
                            severity="high", confidence="high", suggested_fix=fmt_date(approved),
                        ))
            # descriptive facts (sourcing, roast, ...)
            for fact in claim_facts:
                data = fact["data"]
                hit = False
                # Spans of the approved wording, so "medium-dark roast" never trips "dark roast".
                approved_spans = [
                    (m.start(), m.end())
                    for k in data.get("keywords", [])
                    for m in re.finditer(re.escape(k), sent, re.I)
                ]
                for bad in data.get("contradicts", []):
                    for m in re.finditer(rf"(?<![\w-]){re.escape(bad)}", sent, re.I):
                        if any(s <= m.start() and m.end() <= e for s, e in approved_spans):
                            continue
                        hit = True
                        add_claim(sent, "contradicted", fact["code"])
                        raw.append(fact_finding(
                            fact, category="fact",
                            issue=f"'{m.group()}' contradicts the approved fact: {fact['statement']}",
                            span_text=m.group(), span_start=off + m.start(), span_end=off + m.end(),
                            severity="high", confidence="high",
                            suggested_fix=data.get("fix"),
                        ))
                if not hit and any(k in low for k in data.get("keywords", [])):
                    add_claim(sent, "supported", fact["code"])

    if claims_code:
        rank = re.compile(
            r"(?:india['’]s\s+)?(?:#\s?1|no\.?\s?1|number\s+(?:one|1))(?:\s+([a-z][a-z-]+))?", re.I)
        generic = re.compile(
            r"\b(?:the\s+)?(?:best|finest|greatest|unmatched|unbeatable|world['’]s\s+[a-z]+est)\b|\b100\s?%", re.I)
        for off, sent in sents:
            low = sent.lower()
            if any(p.lower() in low for f in super_facts for p in f["data"].get("phrases", [])):
                add_claim(sent, "supported", next(f["code"] for f in super_facts))
                continue
            taken: list[tuple[int, int]] = []
            for m in rank.finditer(sent):
                taken.append((m.start(), m.end()))
                noun = m.group(1)
                add_claim(sent, "no_approved_source")
                raw.append(guideline_finding(
                    claims_code, category="claim",
                    issue=f"'{m.group().strip()}' is a ranking claim with no approved source.",
                    span_text=m.group(), span_start=off + m.start(), span_end=off + m.end(),
                    severity="high", confidence="high",
                    suggested_fix=f"our {noun}" if noun else None,
                    fix_note="Remove or reword unless an approved source is added to the fact sheet.",
                ))
            for m in generic.finditer(sent):
                if any(s <= m.start() < e for s, e in taken):
                    continue
                add_claim(sent, "no_approved_source")
                raw.append(guideline_finding(
                    claims_code, category="claim",
                    issue=f"'{m.group().strip()}' is a superlative claim with no approved source.",
                    span_text=m.group(), span_start=off + m.start(), span_end=off + m.end(),
                    severity="medium", confidence="medium",
                    fix_note="Reword without the superlative, or add an approved source to the fact sheet.",
                ))

    # 4. Images and accessibility ---------------------------------------------------
    code = cited("alt_text")
    if code:
        lo = int(kb.checks["alt_text"].get("min_len", 5))
        hi = int(kb.checks["alt_text"].get("max_len", 125))
        for img in images:
            name, alt = img.get("name", "image"), (img.get("alt") or "").strip()
            if len(alt) < lo:
                raw.append(guideline_finding(
                    code, category="accessibility",
                    issue=f"Image '{name}' has no usable alt text." if not alt
                    else f"Alt text for '{name}' is too short ({len(alt)} characters, minimum {lo}).",
                    span_text=name, target=f"image.alt:{name}",
                    severity="high", confidence="high",
                    fix_note="Describe what the image shows in one short sentence.",
                ))
            elif len(alt) > hi:
                raw.append(guideline_finding(
                    code, category="accessibility",
                    issue=f"Alt text for '{name}' is too long ({len(alt)} characters, maximum {hi}).",
                    span_text=name, target=f"image.alt:{name}",
                    severity="low", confidence="high", fix_note="Shorten the description.",
                ))
    code = cited("contrast")
    if code:
        need = float(kb.checks["contrast"].get("min_ratio", 4.5))
        for img in images:
            fg, bg = img.get("text_color"), img.get("bg_color")
            if not fg or not bg:
                continue
            ratio = contrast_ratio(fg, bg)
            if ratio is None:
                res.warnings.append(f"Contrast for '{img.get('name')}' not checked: invalid colour value.")
                continue
            if ratio < need:
                name = img.get("name", "image")
                raw.append(guideline_finding(
                    code, category="accessibility",
                    issue=f"Text on '{name}' has contrast {ratio:.1f}:1 ({fg} on {bg}); the minimum is {need}:1.",
                    span_text=name, target=f"image.text_color:{name}",
                    severity="medium", confidence="high",
                    suggested_fix=darken_to_pass(fg, bg, need),
                    fix_note="Suggested colour is the closest shade that passes.",
                ))

    # 5. Verify everything, then optionally ask the grounded LLM judge --------------
    for f in raw:
        reason = verify(f, kb, body, images)
        (res.rejected.append(f"{f.issue} ({reason})") if reason else res.findings.append(f))

    if judge:
        extra, status = judge(body, kb, list(res.findings))
        res.llm_status = status
        for f in extra:
            reason = verify(f, kb, body, images)
            if reason:
                res.rejected.append(f"[AI] {f.issue} ({reason})")
            elif any(f.span_start < o.span_end and o.span_start < f.span_end
                     for o in res.findings if o.target == "body" and f.target == "body"):
                continue  # a rule-based finding already covers this span
            else:
                res.findings.append(f)

    res.findings.sort(key=lambda f: (f.span_start if f.span_start >= 0 else 10**9, f.issue))
    return res
