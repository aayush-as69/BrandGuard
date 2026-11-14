"""Small, explainable BM25 retriever for source-grounded AI review.

The retriever deliberately stays dependency-free. It adds two useful ranking signals:
light stemming so close word forms can match, and a heading/title boost so a rule's
name carries more weight than the body alone. Access filtering still happens before
this layer, so retrieval can never broaden a user's clearance.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

TOKEN_RE = re.compile(r"[a-z0-9']+")
_SUFFIXES = (
    ("ingly", ""),
    ("edly", ""),
    ("ments", ""),
    ("ment", ""),
    ("ation", ""),
    ("ations", ""),
    ("ing", ""),
    ("ers", ""),
    ("ies", "y"),
    ("ed", ""),
    ("es", ""),
    ("s", ""),
)


def stem(token: str) -> str:
    """Small, conservative stemmer; avoid turning short words into nonsense."""
    if len(token) <= 4:
        return token
    for suffix, replacement in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)] + replacement
    return token


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in TOKEN_RE.findall(text.lower())]


@lru_cache(maxsize=8)
def _index(rules_key: tuple) -> tuple[dict, dict, Counter, float]:
    """Tokenise each rule once per distinct rule set.

    The cached value keeps body tokens and title tokens separate so the title can
    receive a modest relevance boost without changing the explainability of the score.
    """
    docs: dict[str, list[str]] = {}
    titles: dict[str, list[str]] = {}
    df: Counter = Counter()

    for code, title, text in rules_key:
        body_tokens = tokenize(text)
        title_tokens = tokenize(title)
        docs[code] = body_tokens
        titles[code] = title_tokens
        df.update(set(body_tokens + title_tokens))

    avg = (sum(len(d) for d in docs.values()) / len(docs)) if docs else 1.0
    return docs, titles, df, avg or 1.0


def _bm25(tf: int, doc_len: int, avg_len: float, n: int, df: int, k1: float = 1.5, b: float = 0.75) -> float:
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    return idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_len))


def top_rules(query: str, rules: dict[str, dict], k: int = 4) -> list[str]:
    """Return up to k rule codes, best match first. Rules with no overlap are excluded."""
    if not rules or k <= 0:
        return []

    docs, titles, df, avg = _index(tuple((code, r["title"], r["text"]) for code, r in rules.items()))
    n = len(docs)
    q = set(tokenize(query))
    scored = []

    for code, toks in docs.items():
        if not q:
            continue
        body_tf = Counter(toks)
        title_tf = Counter(titles[code])
        doc_len = len(toks) or 1
        score = 0.0

        for term in q:
            if term not in body_tf and term not in title_tf:
                continue

            # Body evidence is the main signal; matching the rule title is a
            # deliberately smaller but useful boost.
            if body_tf[term]:
                score += _bm25(body_tf[term], doc_len, avg, n, df[term])
            if title_tf[term]:
                score += 0.35 * _bm25(title_tf[term], max(len(titles[code]), 1), max(avg, 1.0), n, df[term])

        if score > 0:
            scored.append((score, code))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [code for _, code in scored[:k]]
