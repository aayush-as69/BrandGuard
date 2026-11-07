"""Grounded LLM judge for tone and messaging.

Grounding rules:
  * The model only sees the content and the few retrieved guideline rules.
  * It must cite a rule code and quote the rule; the engine verifies both.
  * It must quote the flagged span verbatim; the engine verifies that too.
  * AI findings are labelled, capped at "medium" confidence, and never auto-applied.
  * Everything sent out is written to llm_log so it can be disclosed.

The judge is optional: with no ANTHROPIC_API_KEY the rule-based engine still
runs and the review says the AI judge was not used.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Callable, Optional

from . import retrieve
from .db import now
from .models import Finding

DEFAULT_MODEL = "claude-sonnet-5-5"
API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "You are a brand-governance reviewer. Judge the content ONLY against the numbered brand rules provided. "
    "Report only clear tone or messaging problems that the rules actually cover; do not invent rules, "
    "facts, prices or dates. Return a JSON array and nothing else. Each item: "
    '{"rule_code": "...", "quote": "exact words copied from that rule", "span": "exact words copied from the content", '
    '"issue": "one plain sentence", "severity": "high|medium|low", "confidence": "high|medium|low", '
    '"fix": "minimal rewrite of the span that keeps the author\'s meaning, or empty"}. '
    "If nothing is wrong, return []."
)


def default_call(system: str, user: str, model: str) -> str:
    """Call the Anthropic Messages API. Raises on any failure."""
    import requests

    key = os.environ["ANTHROPIC_API_KEY"]
    r = requests.post(
        API_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 1500, "system": system,
              "messages": [{"role": "user", "content": user}]},
        timeout=30,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))


def _parse(text: str) -> list[dict]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("model did not return a JSON array")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("model output is not a list")
    return [d for d in data if isinstance(d, dict)]


def make_judge(
    conn: sqlite3.Connection,
    content_id: Optional[int] = None,
    version: Optional[int] = None,
    call: Optional[Callable[[str, str, str], str]] = None,
    top_k: int = 4,
):
    """Build the judge callable for engine.review. Returns None if no AI backend is configured."""
    if call is None:
        if not os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("BRANDGUARD_LLM", "on") == "off":
            return None
        call = default_call
    model = os.environ.get("BRANDGUARD_MODEL", DEFAULT_MODEL)

    def judge(body: str, kb, existing: list[Finding]) -> tuple[list[Finding], str]:
        codes: list[str] = []
        for para in (p for p in body.split("\n") if p.strip()):
            for code in retrieve.top_rules(para, kb.rules, k=top_k):
                if code not in codes:
                    codes.append(code)
        if not codes:
            return [], "skipped: no relevant guideline rules retrieved"
        rules_text = "\n".join(f"{c}: {kb.rules[c]['text']}" for c in codes)
        user = f"BRAND RULES\n{rules_text}\n\nCONTENT\n{body}"
        conn.execute(
            "INSERT INTO llm_log(content_id, version, model, payload, created_at) VALUES (?,?,?,?,?)",
            (content_id, version, model, system_and_user(user), now()),
        )
        conn.commit()
        try:
            items = _parse(call(SYSTEM, user, model))
        except Exception as exc:  # network, auth, bad JSON: never break the review
            return [], f"failed: {type(exc).__name__}: {exc}"[:200]

        out: list[Finding] = []
        for it in items:
            span = str(it.get("span", ""))
            code = str(it.get("rule_code", ""))
            start = body.find(span) if span else -1
            sev = it.get("severity") if it.get("severity") in ("high", "medium", "low") else "medium"
            conf = it.get("confidence") if it.get("confidence") in ("medium", "low") else "medium"  # AI never "high"
            try:
                out.append(Finding(
                    category="tone",
                    issue=str(it.get("issue", "")),
                    span_text=span, span_start=start, span_end=start + len(span) if start >= 0 else -1,
                    source_type="guideline", source_id=code, source_quote=str(it.get("quote", "")),
                    severity=sev, confidence=conf,
                    suggested_fix=(str(it["fix"]).strip() or None) if it.get("fix") else None,
                    ai_generated=True,
                ))
            except Exception:
                continue  # malformed record: rejected by schema validation
        return out, f"used {model}; {len(codes)} rules retrieved, {len(items)} suggestions returned"

    return judge


def system_and_user(user: str) -> str:
    return f"[system]\n{SYSTEM}\n\n[user]\n{user}"
