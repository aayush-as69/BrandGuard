"""Small BM25 retriever so the LLM judge only ever sees the few guideline rules
relevant to the content. (pgvector embeddings are the planned production upgrade;
BM25 needs no external service and is easy to explain.)"""
from __future__ import annotations

import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def top_rules(query: str, rules: dict[str, dict], k: int = 4) -> list[str]:
    """Return up to k rule codes, best match first. Rules with no overlap are excluded."""
    docs = {code: tokenize(r["title"] + " " + r["text"]) for code, r in rules.items()}
    if not docs:
        return []
    n = len(docs)
    avg = sum(len(d) for d in docs.values()) / n or 1.0
    df: Counter = Counter()
    for toks in docs.values():
        df.update(set(toks))
    q = tokenize(query)
    scored = []
    for code, toks in docs.items():
        tf = Counter(toks)
        score = 0.0
        for term in set(q):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf[term] * 2.2) / (tf[term] + 1.2 * (0.25 + 0.75 * len(toks) / avg))
        if score > 0:
            scored.append((score, code))
    scored.sort(reverse=True)
    return [code for _, code in scored[:k]]
