# BrandGuard

**Catch brand mistakes before they go live.** An explainable, source-grounded brand-governance platform.
Every finding cites an approved guideline or fact, suggestions never override people, and a reviewer approves before anything is published.

CodeTitan Hackathon · Team STARTEND · Aayush Singh (solo) · Round 2: The Build

All demo data is synthetic (fictional brand: Brewline Coffee). No confidential material is included.

## What works in Round 2

| Plan feature (Must) | Where it lives |
|---|---|
| Knowledge base import: guidelines (PDF/DOCX/TXT/MD), approved facts, glossary, asset list, access levels | `brandguard/kb.py`, `POST /api/kb/import` |
| Text review, rules first | `brandguard/engine.py` |
| Cited findings: span, rule or fact, source quote, severity, confidence | `brandguard/models.py` (`Finding`), `engine.verify` |
| Claim check: supported / contradicted / no approved source | `engine.review` (prices, dates, rankings, superlatives, descriptive facts) |
| Suggested fixes shown as a diff; accept, edit or dismiss | `workflow.decide`, `static/index.html` |
| Review workflow: roles, comments, approval, versions, audit log | `brandguard/workflow.py` |
| Image and accessibility check (Should) | alt text length and WCAG contrast in `engine.py` |
| Grounded AI judge for tone and messaging | `brandguard/llm.py` (optional, needs an API key) |

## Run it

```bash
pip install flask pydantic python-docx pypdf requests pytest   # no other dependencies
python run.py                                                  # http://127.0.0.1:5000
python -m pytest -q                                            # 28 tests
```

Demo walkthrough: sign in as **Ira (admin)** → Knowledge base → *Load Brewline demo knowledge base*.
Sign in as **Neha (agency creator)** → New → *Load demo email* → *Review now*.
Fix findings, *Submit for approval*, then sign in as **Arjun (manager)** or **Meera (reviewer)** to approve.

Optional AI judge: `export ANTHROPIC_API_KEY=...` (model via `BRANDGUARD_MODEL`, default `claude-sonnet-5-5`; `BRANDGUARD_LLM=off` disables it).

## Architecture and main decisions

```
Content → Parse → Rules + retrieval → LLM judge → Verify → Findings store → Review UI → Approval
```

- **One finding model.** `Finding` (pydantic) cannot exist without a source id, a source quote, severity and confidence. Malformed records are rejected by validation.
- **Rules first, AI second.** Glossary matches, exclamation and capitals limits, price/date/fact matching, alt text and WCAG contrast are deterministic and fully explainable. The LLM only judges tone and messaging.
- **Grounded AI.** The model sees only the content plus the top guideline rules retrieved by BM25. It must return a rule code, a verbatim quote of the rule and a verbatim span of the content. `engine.verify` checks all three; anything that fails is discarded and counted in the review header. AI findings are labelled, capped at *medium* confidence and never auto-applied. Everything sent to the API is stored in `llm_log`.
- **Data-driven checks.** Which rule each check cites, and its limits, live in the `settings` table (imported from `seed/settings.json`), not in code. If a configured rule is missing from the knowledge base, the check is skipped with a visible warning instead of failing silently.
- **Human control is enforced in the server, not just the UI** (`workflow.py`): dismissals need a reason; dismissing fact, claim or low-confidence findings needs a manager or reviewer; approval needs every finding decided, a manager or reviewer who is not the author, and a reviewer specifically if a claim was dismissed; approved content is locked; every action is audited.
- **Access.** External agency users see only their own content and cannot browse the knowledge base. Facts are `confidential`: internal creators browse guidelines only; managers, reviewers and admins browse everything.

## Deviations from the Round 1 plan (disclosure)

- **Flask instead of FastAPI.** FastAPI was not installable in the build environment (package installs were disabled). Pydantic still validates every finding, so the "malformed output is rejected" property is unchanged. The service layer is framework-independent, so a port is mechanical.
- **SQLite and BM25 instead of PostgreSQL + pgvector** for now (listed as dev default in the plan). Retrieval is keyword-based; embeddings are the planned upgrade.
- **Sign-in is a user switcher** (session cookie, no passwords) so judges can try every role quickly. This is a demo mechanism, not authentication.

## Testing

`python -m pytest -q` runs 28 tests, including: all seeded traps detected with citations; clean content produces no findings; fabricated AI quotes, rules and spans are rejected; an AI outage does not break the review; the full creator → manager → reviewer approval flow; role and access restrictions; dismissals carried across versions. Writing these tests found and fixed two real bugs (a price span that swallowed a comma, and "medium-dark roast" being flagged as contradicting itself).

**Not yet tested:** the live LLM call against the real API (tests use a fake backend), PDF import with real-world scanned PDFs, concurrent users, and user testing with real teams.

## Known limitations

- Single organisation: workspaces are not yet isolated per organisation.
- Rule-based fixes are minimal word swaps; stronger, intent-preserving rewrites are a Round 3 improvement.
- Claim extraction covers prices (₹/Rs/INR), dates, rankings, common superlatives and keyword facts, not every possible claim.
- Images are described by name, alt text and colours entered by the user; vision-based reading of uploaded images is not built yet.
- Not a substitute for legal advice.

## Round 3 improvements (to be confirmed)

1. Guideline insights: repeated mistakes and often-disputed rules.
2. Intent-preserving rewrites with a diff view.
3. Privacy mode with leakage tests (redact secrets before AI calls).

## AI disclosure

This plan and the code were prepared with AI assistance (Claude, via Claude Code) and reviewed by the author. The product itself can call an LLM API and labels every AI-generated finding.
