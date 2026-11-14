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
MAX_FINDINGS = 300      # a review shows at most this many; the rest means "fix these and run it again"
MAX_CLAIM_TEXT = 300
_ALWAYS_OK_CAPS = {"INR", "GST", "MRP", "FSSAI", "MSME", "GSTIN", "SKU", "CEO", "FAQ", "USD", "EMI"}
_NEGATION = re.compile(r"\b(?:not|never|no|without|isn['’]t|aren['’]t|wasn['’]t|doesn['’]t|don['’]t)\s+(?:\w+\s+){0,2}$", re.I)
_RELATIVE = re.compile(r"\b(?:after|before|since|until|till|following|post|by)\s+(?:the\s+|our\s+)?$", re.I)
NEAR = 60               # a date counts as the launch date only if it sits this close to the word "launch"
_ABBREV = {"no", "rs", "mr", "mrs", "ms", "dr", "st", "vs", "approx", "inc", "ltd"}


def sentences(body: str) -> list[tuple[int, str]]:
    """(offset, text) for every sentence, so findings can point at exact spans.
    A full stop after an abbreviation ("No. 1", "Rs. 399") does not end a sentence."""
    out: list[tuple[int, str]] = []
    for line in re.finditer(r"[^\n]+", body):
        text, base, begin = line.group(), line.start(), 0
        for m in re.finditer(r"[.!?]+(?=\s|$)", text):
            word = re.search(r"([A-Za-z]+)$", text[max(0, m.start() - 12):m.start()])
            if m.group() == "." and word and word.group(1).lower() in _ABBREV:
                continue
            seg = text[begin:m.end()]
            if seg.strip():
                out.append((base + begin, seg))
            begin = m.end()
        if text[begin:].strip():
            out.append((base + begin, text[begin:]))
    return out


def match_case(original: str, replacement: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def fmt_date(d: dt.date) -> str:
    return f"{d.day} {MONTH_NAMES[d.month - 1]} {d.year}"


def find_partial_dates(text: str, taken: list[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Dates written without a year ("15 December", "December 15th"): (start, end, month, day)."""
    out = []
    for rx, md in ((re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\b(?!\.?,?\s+\d{{4}})", re.I), (2, 1)),
                   (re.compile(rf"\b({_MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!,?\s+\d{{4}})", re.I), (1, 2))):
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            try:
                month, day = _MONTHS[m.group(md[0]).lower()], int(m.group(md[1]))
                dt.date(2000, month, day)  # leap year, validates the day
            except (KeyError, ValueError):
                continue
            out.append((m.start(), m.end(), month, day))
    return out


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
def ai_pass(kb, body: str, images: list[dict], existing: list, judge) -> tuple[list[Finding], list[str], str]:
    """Run only the AI judge over a body that rule-based findings already cover. `existing` needs span_start,
    span_end and target. Returns (accepted findings, rejected notes, status). Same verification as a full review."""
    got, status = judge(body, kb, list(existing))
    accepted: list[Finding] = []
    rejected: list[str] = []
    for f in got:
        reason = verify(f, kb, body, images)
        if reason:
            rejected.append(f"[AI] {f.issue} ({reason})")
        elif any(f.span_start < o.span_end and o.span_start < f.span_end
                 for o in list(existing) + accepted if o.target == "body" and f.target == "body"):
            continue
        else:
            accepted.append(f)
    return accepted, rejected, status


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
    truncated: int = 0       # findings not shown because of MAX_FINDINGS


_PRICE = re.compile(r"(?<![A-Za-z])((?:₹|Rs\.?|INR)\s?)(\d(?:[\d,]*\d)?(?:\.\d+)?)")
_RANKING = re.compile(
    r"(?:(?<!\w)india['’]s\s+)?(?:#\s?1|(?<!\w)no\.?\s?1|(?<!\w)number\s+(?:one|1))(?!\d)"
    r"(?:\s+(?!(?:is|are|was|were|in|on|at|for|of|to|by|and|or|with|among|since|that|the|a|an|as|but|from)\b)"
    r"([a-z][a-z-]+))?", re.I)
_SUPERLATIVE = re.compile(
    r"\b(?:the\s+)?(?:best|finest|greatest|unmatched|unbeatable|world['’]s\s+[a-z]+est)\b|\b100\s?%", re.I)
_SENTENCE_START = re.compile(r"(?:^|\n|[.!?][\"')\]]*[ \t]+)$")


def _about(fact: dict, low: str, start: int, end: int) -> bool:
    """The date at low[start:end] is the one the fact describes: one of the fact's words sits close by and
    does not merely relate to it ("after the launch" is not the launch date)."""
    for term in fact["data"].get("match", []):
        for tm in re.finditer(re.escape(term), low):
            gap = max(tm.start() - end, start - tm.end(), 0)
            if gap <= NEAR and not _RELATIVE.search(low[:tm.start()]):
                return True
    return False


def _money(amount: float) -> str:
    return f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"


class _Review:
    """One review run. Each check_* method looks for one kind of problem and appends findings to `raw`;
    nothing is shown to anyone until `finish` has verified every finding against its source."""

    def __init__(self, kb: KB, body: str, images: list[dict]) -> None:
        self.kb, self.body, self.images = kb, body, images
        self.sents = sentences(body)
        self.res = ReviewResult()
        self.raw: list[Finding] = []
        self._seen_claims: set[tuple[str, str, str]] = set()
        self.facts = {kind: [f for f in kb.facts if f["kind"] == kind] for kind in ("price", "date", "claim", "superlative")}

    # -- helpers ---------------------------------------------------------------
    def cited(self, check: str) -> Optional[str]:
        """Rule code a check cites; None (plus a warning) if the KB does not have it."""
        cfg = self.kb.checks.get(check)
        if not cfg:
            return None
        code = cfg.get("rule_code")
        if code not in self.kb.rules:
            self.res.warnings.append(f"Check '{check}' skipped: rule {code} is not in the knowledge base.")
            return None
        return code

    def guideline_finding(self, code: str, **kw) -> Finding:
        return Finding(source_type="guideline", source_id=code, source_quote=self.kb.rules[code]["text"], **kw)

    @staticmethod
    def fact_finding(fact: dict, **kw) -> Finding:
        return Finding(source_type="fact", source_id=fact["code"], source_quote=fact["statement"], **kw)

    def add_claim(self, text: str, status: str, source_id: str = "") -> None:
        text = " ".join(text[:MAX_CLAIM_TEXT * 4].split())  # cut first: never normalise a huge sentence
        if len(text) > MAX_CLAIM_TEXT:
            text = text[:MAX_CLAIM_TEXT].rstrip() + "…"
        if (text, status, source_id) not in self._seen_claims:
            self._seen_claims.add((text, status, source_id))
            self.res.claims.append({"text": text, "status": status, "source_id": source_id})

    # -- 1. glossary: banned terms and slang -----------------------------------------
    def check_glossary(self) -> None:
        body = self.body
        for g in self.kb.glossary:
            code = g["rule_code"]
            if code not in self.kb.rules:
                self.res.warnings.append(f"Glossary term '{g['term']}' skipped: rule {code} is missing.")
                continue
            for m in re.finditer(rf"(?<![\w-]){re.escape(g['term'])}(?![\w-])", body, re.I):
                tone = g["kind"] == "slang"
                start, text = m.start(), m.group()
                fix = match_case(text, g["preferred"])
                # Keep "a"/"an" correct: "a cheap price" -> "an affordable price".
                lead = max(0, start - 12)
                art = re.search(r"\b(an?)(\s+)$", body[lead:start], re.I)
                if art and fix[:1].isalpha():
                    want = "an" if fix[0].lower() in "aeiou" else "a"
                    if art.group(1).lower() != want:
                        start = lead + art.start()
                        text = body[start:m.end()]
                        fix = f"{match_case(art.group(1), want)}{art.group(2)}{fix}"
                self.raw.append(self.guideline_finding(
                    code,
                    category="tone" if tone else "terminology",
                    issue=(f"'{m.group()}' is {'off-tone slang' if tone else 'a banned term'}; "
                           f"use '{g['preferred']}'." + (f" {g['note']}" if g.get("note") else "")),
                    span_text=text, span_start=start, span_end=m.end(),
                    severity="medium", confidence="high", suggested_fix=fix,
                ))

    # -- 2. punctuation and emphasis ---------------------------------------------------
    def check_exclamations(self) -> None:
        code = self.cited("exclamation")
        if not code:
            return
        limit = int(self.kb.checks["exclamation"].get("max", 1))
        runs = list(re.finditer(r"!+", self.body))
        if not runs or not (len(runs) > limit or len(runs[0].group()) > 1):
            return
        for i, m in enumerate(runs):
            if i < limit and len(m.group()) == 1:
                continue
            self.raw.append(self.guideline_finding(
                code, category="tone",
                issue=f"Too many exclamation marks (the limit is {limit} per email).",
                span_text=m.group(), span_start=m.start(), span_end=m.end(),
                severity="low", confidence="high",
                suggested_fix="!" if i < limit else ".",
            ))

    def check_capitals(self) -> None:
        code = self.cited("all_caps")
        if not code:
            return
        allow = set(self.kb.checks["all_caps"].get("allow", [])) | _ALWAYS_OK_CAPS
        for m in re.finditer(r"\b[A-Z]{3,}\b", self.body):
            if m.group() in allow:
                continue
            self.raw.append(self.guideline_finding(
                code, category="tone",
                issue=f"'{m.group()}' is written in capitals for emphasis.",
                span_text=m.group(), span_start=m.start(), span_end=m.end(),
                severity="low", confidence="high", suggested_fix=m.group().capitalize(),
            ))

    # -- 3. claims and approved facts ---------------------------------------------------
    def check_facts(self) -> None:
        """Prices, dates and descriptive facts are compared with the approved fact sheet."""
        if not self.cited("facts"):
            return
        for off, sent in self.sents:
            low = sent.lower()
            self._prices(off, sent, low)
            self._dates(off, sent, low)
            self._descriptive_facts(off, sent, low)

    def _prices(self, off: int, sent: str, low: str) -> None:
        price_facts = self.facts["price"]
        for m in _PRICE.finditer(sent):
            amount = float(m.group(2).replace(",", ""))
            cands = [f for f in price_facts if any(t in low for t in f["data"].get("match", []))]
            guessed = False
            if not cands and len(price_facts) == 1:
                cands, guessed = price_facts, True  # nothing says which price this is
            if not cands:
                self.add_claim(sent, "no_approved_source")
                continue
            fact = cands[0]
            approved = float(fact["data"]["amount"])
            shown = _money(approved)
            span = dict(span_text=m.group(0), span_start=off + m.start(), span_end=off + m.end())
            if amount == approved:
                self.add_claim(sent, "supported", fact["code"])
            elif guessed:
                # "Free delivery above ₹999" is not the product price: ask a person, do not assert.
                self.add_claim(sent, "no_approved_source")
                self.raw.append(self.fact_finding(
                    fact, category="fact", **span,
                    issue=(f"{m.group(0)} is not an approved price. If it is the product price, "
                           f"the approved price is {m.group(1)}{shown}."),
                    severity="medium", confidence="low",
                    fix_note="Check whether this amount refers to the product; no fix is applied automatically.",
                ))
            else:
                self.add_claim(sent, "contradicted", fact["code"])
                self.raw.append(self.fact_finding(
                    fact, category="fact", **span,
                    issue=f"Price is {m.group(0)} but the approved price is {m.group(1)}{shown}.",
                    severity="high", confidence="high", suggested_fix=f"{m.group(1)}{shown}",
                ))

    def _dates(self, off: int, sent: str, low: str) -> None:
        dates = find_dates(sent)
        partial = find_partial_dates(sent, [(a, b) for a, b, _ in dates])
        # (start, end, same_as_approved, confidence, shown_in_issue, fix_for) for every date found
        found = [(a, b, lambda ap, d=d: d == ap, "high", fmt_date(d), fmt_date) for a, b, d in dates]
        found += [(a, b, lambda ap, mo=mo, dy=dy: (mo, dy) == (ap.month, ap.day), "medium", sent[a:b],
                   lambda ap: f"{ap.day} {MONTH_NAMES[ap.month - 1]}") for a, b, mo, dy in partial]
        for start, end, same, confidence, shown, fix_for in found:
            for fact in self.facts["date"]:
                if not _about(fact, low, start, end):
                    continue
                approved = dt.date.fromisoformat(fact["data"]["date"])
                if same(approved):
                    self.add_claim(sent, "supported", fact["code"])
                    continue
                self.add_claim(sent, "contradicted", fact["code"])
                self.raw.append(self.fact_finding(
                    fact, category="fact",
                    issue=f"Date is {shown} but the approved date is {fmt_date(approved)}.",
                    span_text=sent[start:end], span_start=off + start, span_end=off + end,
                    severity="high", confidence=confidence, suggested_fix=fix_for(approved),
                ))

    def _descriptive_facts(self, off: int, sent: str, low: str) -> None:
        """Sourcing, roast and similar facts: wording that contradicts them, or wording that agrees."""
        for fact in self.facts["claim"]:
            data = fact["data"]
            hit = False
            # Spans of the approved wording, so "medium-dark roast" never trips "dark roast".
            approved_spans = [(m.start(), m.end()) for k in data.get("keywords", [])
                              for m in re.finditer(re.escape(k), sent, re.I)]
            for bad in data.get("contradicts", []):
                for m in re.finditer(rf"(?<![\w-]){re.escape(bad)}", sent, re.I):
                    if any(s <= m.start() and m.end() <= e for s, e in approved_spans):
                        continue
                    if _NEGATION.search(sent[:m.start()]):
                        continue  # "not a light roast" agrees with the fact
                    hit = True
                    self.add_claim(sent, "contradicted", fact["code"])
                    self.raw.append(self.fact_finding(
                        fact, category="fact",
                        issue=f"'{m.group()}' contradicts the approved fact: {fact['statement']}",
                        span_text=m.group(), span_start=off + m.start(), span_end=off + m.end(),
                        severity="high", confidence="high", suggested_fix=data.get("fix"),
                    ))
            if not hit and any(k in low for k in data.get("keywords", [])):
                self.add_claim(sent, "supported", fact["code"])

    def check_claims(self) -> None:
        """Rankings ("#1") and superlatives need an approved source."""
        code = self.cited("claims")
        if not code:
            return
        super_facts = self.facts["superlative"]
        for off, sent in self.sents:
            low = sent.lower()
            if any(p.lower() in low for f in super_facts for p in f["data"].get("phrases", [])):
                self.add_claim(sent, "supported", super_facts[0]["code"])
                continue
            taken: list[tuple[int, int]] = []
            for m in _RANKING.finditer(sent):
                taken.append((m.start(), m.end()))
                noun = m.group(1)
                self.add_claim(sent, "no_approved_source")
                self.raw.append(self.guideline_finding(
                    code, category="claim",
                    issue=f"'{m.group().strip()}' is a ranking claim with no approved source.",
                    span_text=m.group(), span_start=off + m.start(), span_end=off + m.end(),
                    severity="high", confidence="high",
                    suggested_fix=f"our {noun}" if noun else None,
                    fix_note="Remove or reword unless an approved source is added to the fact sheet.",
                ))
            for m in _SUPERLATIVE.finditer(sent):
                if any(s <= m.start() < e for s, e in taken):
                    continue
                self.add_claim(sent, "no_approved_source")
                self.raw.append(self.guideline_finding(
                    code, category="claim",
                    issue=f"'{m.group().strip()}' is a superlative claim with no approved source.",
                    span_text=m.group(), span_start=off + m.start(), span_end=off + m.end(),
                    severity="medium", confidence="medium",
                    fix_note="Reword without the superlative, or add an approved source to the fact sheet.",
                ))

    # -- 4. images and accessibility -----------------------------------------------------
    def check_alt_text(self) -> None:
        code = self.cited("alt_text")
        if not code:
            return
        lo = int(self.kb.checks["alt_text"].get("min_len", 5))
        hi = int(self.kb.checks["alt_text"].get("max_len", 125))
        for img in self.images:
            name, alt = img.get("name", "image"), (img.get("alt") or "").strip()
            where = dict(category="accessibility", span_text=name, target=f"image.alt:{name}")
            if len(alt) < lo:
                self.raw.append(self.guideline_finding(
                    code, **where,
                    issue=f"Image '{name}' has no usable alt text." if not alt
                    else f"Alt text for '{name}' is too short ({len(alt)} characters, minimum {lo}).",
                    severity="high", confidence="high",
                    fix_note="Describe what the image shows in one short sentence.",
                ))
            elif len(alt) > hi:
                self.raw.append(self.guideline_finding(
                    code, **where,
                    issue=f"Alt text for '{name}' is too long ({len(alt)} characters, maximum {hi}).",
                    severity="low", confidence="high", fix_note="Shorten the description.",
                ))

    def check_contrast(self) -> None:
        code = self.cited("contrast")
        if not code:
            return
        need = float(self.kb.checks["contrast"].get("min_ratio", 4.5))
        for img in self.images:
            fg, bg = img.get("text_color"), img.get("bg_color")
            name = img.get("name", "image")
            areas = ((img.get("measure") or {}).get("text") or {}).get("areas") or []
            where, measured = "", False
            if fg and areas:      # measured from the real pixels: the text colour against the background around each text area
                scored = [(contrast_ratio(fg, a["bg"]), a) for a in areas]
                scored = [(r, a) for r, a in scored if r is not None]
                if scored:
                    ratio, worst = min(scored, key=lambda t: t[0])
                    bg, measured = worst["bg"], True
                    where = f", measured at x={worst['x']}, y={worst['y']}"
            if not fg or not bg:
                continue
            if not measured:
                ratio = contrast_ratio(fg, bg)
            if ratio is None:
                self.res.warnings.append(f"Contrast for '{name}' not checked: invalid colour value.")
                continue
            if ratio < need:
                fix = darken_to_pass(fg, bg, need)
                self.raw.append(self.guideline_finding(
                    code, category="accessibility",
                    issue=f"Text on '{name}' has contrast {ratio:.1f}:1 ({fg} on {bg}{where}); the minimum is {need}:1.",
                    span_text=name, target=f"image.text_color:{name}",
                    severity="medium", confidence="high",
                    suggested_fix=fix,
                    fix_note="Suggested colour is the closest shade that passes." if fix
                    else "Choose a text colour that contrasts more with the background behind it.",
                ))

    def check_palette(self) -> None:
        """Share of an image's pixels in colours that are neither brand colours nor neutral (measured, not guessed)."""
        code = self.cited("palette")
        if not code:
            return
        cfg = self.kb.checks["palette"]
        brand = cfg.get("colours") or []
        tol, limit = float(cfg.get("tolerance", 14)), float(cfg.get("max_off_share", 0.12))
        from . import pixels
        for img in self.images:
            cols = (img.get("measure") or {}).get("colours")
            if not cols or not brand:
                continue
            off = [c for c in cols if not pixels.is_neutral(c["hex"]) and min(pixels.delta_e(c["hex"], b) for b in brand) > tol]
            share = sum(c["share"] for c in off)
            if share > limit:
                name = img.get("name", "image")
                biggest = ", ".join(f"{c['hex'].upper()} ({c['share'] * 100:.0f}%)" for c in sorted(off, key=lambda c: -c["share"])[:3])
                self.raw.append(self.guideline_finding(
                    code, category="visual", span_text=name, target=f"image.palette:{name}",
                    issue=f"{share * 100:.0f}% of '{name}' is outside the brand palette (largest: {biggest}); the limit is {limit * 100:.0f}%.",
                    severity="medium", confidence="high",
                    fix_note=f"Recolour those areas with {', '.join(b.upper() for b in brand)} or a neutral.",
                ))

    def check_logo(self) -> None:
        """For images the author marked as carrying the logo: is it there, big enough and clear of other content."""
        code = self.cited("logo")
        if not code:
            return
        cfg = self.kb.checks["logo"]
        min_pct, clear_ratio = float(cfg.get("min_width_pct", 15)), float(cfg.get("clear_ratio", 0.5))
        for img in self.images:
            if not img.get("logo"):
                continue
            name = img.get("name", "image")
            m = img.get("measure") or {}
            if m.get("logo") is None:
                self.res.warnings.append(f"Logo in '{name}' not checked: read the image file to measure it.")
                continue
            lg, base = m["logo"], dict(category="visual", span_text=name, target=f"image.logo:{name}", severity="medium", confidence="medium")
            if not lg.get("found"):
                self.raw.append(self.guideline_finding(
                    code, **base, issue=f"The logo was not found in '{name}', but the image is marked as carrying it.",
                    fix_note="Place the primary logo in Espresso or Crema, whole and unaltered."))
                continue
            pct = lg["w"] / m["width"] * 100
            need = clear_ratio * lg["h"]
            tight = {k: v for k, v in lg["clear"].items() if v < need}
            if pct < min_pct:
                self.raw.append(self.guideline_finding(
                    code, **base, issue=f"The logo in '{name}' is {pct:.0f}% of the image width ({lg['w']}px of {m['width']}px); the minimum is {min_pct:.0f}%.",
                    fix_note="Enlarge the logo."))
            elif tight:
                sides = ", ".join(f"{k} {v}px" for k, v in tight.items())
                self.raw.append(self.guideline_finding(
                    code, **base, issue=f"The logo in '{name}' has too little clear space ({sides}); it needs {need:.0f}px, half its height, on every side.",
                    fix_note="Move other content away from the logo."))

    # -- 5. finishing: tidy fixes, verify, add AI suggestions, order, cap ---------------------
    def capitalise_fixes(self) -> None:
        """A fix that lands at the start of a sentence starts with a capital letter."""
        for f in self.raw:
            fix = f.suggested_fix
            if (f.target == "body" and fix and f.span_start >= 0 and fix[0].isalpha() and fix[0].islower()
                    and _SENTENCE_START.search(self.body[max(0, f.span_start - 40):f.span_start])):
                f.suggested_fix = fix[0].upper() + fix[1:]

    def verify_rule_findings(self) -> None:
        for f in self.raw:
            reason = verify(f, self.kb, self.body, self.images)
            (self.res.rejected.append(f"{f.issue} ({reason})") if reason else self.res.findings.append(f))

    def add_ai_findings(self, judge, inherited: Optional[list[Finding]]) -> None:
        res = self.res
        extra: list[Finding] = list(inherited or [])
        if extra:
            res.llm_status = f"{len(extra)} earlier AI suggestion(s) carried over; content was not re-sent"
        if judge:
            got, status = judge(self.body, self.kb, list(res.findings))
            res.llm_status = status
            extra += got
        for f in extra:
            reason = verify(f, self.kb, self.body, self.images)
            if reason:
                res.rejected.append(f"[AI] {f.issue} ({reason})")
            elif any(f.span_start < o.span_end and o.span_start < f.span_end
                     for o in res.findings if o.target == "body" and f.target == "body"):
                continue  # a rule-based finding already covers this span
            else:
                res.findings.append(f)

    def finish(self) -> ReviewResult:
        res = self.res
        res.findings.sort(key=lambda f: (f.span_start if f.span_start >= 0 else 10**9, f.issue))
        if len(res.findings) > MAX_FINDINGS:
            res.truncated = len(res.findings) - MAX_FINDINGS
            res.findings = res.findings[:MAX_FINDINGS]
            res.warnings.append(
                f"{res.truncated} more findings are not shown (limit {MAX_FINDINGS}). "
                "Fix these, then run the review again to see the rest.")
        return res


def review(
    kb: KB,
    body: str,
    images: list[dict],
    judge: Optional[Callable[[str, KB, list[Finding]], tuple[list[Finding], str]]] = None,
    inherited: Optional[list[Finding]] = None,
) -> ReviewResult:
    """Run every check, verify each finding against its source, then optionally add AI suggestions.
    `inherited` are AI suggestions from the previous version, re-located in this text, so applying
    a fix does not send the content to the AI service again."""
    r = _Review(kb, body, images)
    for check in (r.check_glossary, r.check_exclamations, r.check_capitals, r.check_facts,
                  r.check_claims, r.check_alt_text, r.check_contrast, r.check_palette, r.check_logo):
        check()
    r.capitalise_fixes()
    r.verify_rule_findings()
    r.add_ai_findings(judge, inherited)
    return r.finish()
