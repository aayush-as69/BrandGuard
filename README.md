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
| Suggested fixes shown as a diff; accept, edit or dismiss | `workflow.decide`, `static/js/content.js` |
| Review workflow: roles, comments, approval, versions, audit log | `brandguard/workflow.py` |
| Image and accessibility check (Should) | alt text length and WCAG contrast in `engine.py` |
| Grounded AI judge for tone and messaging | `brandguard/llm.py` (optional, needs an API key; `scripts/check_live_ai.py` tests it end to end) |
| Guideline insights (repeated mistakes, often-disputed rules) | `brandguard/insights.py`, Insights tab (managers, reviewers, admins) |
| Printable approval record: text, findings with sources, decisions, approver, audit trail | `brandguard/record.py`, `GET /api/content/<id>/record` |
| Guided 2-minute tour through every role | "Tour" button in the page header |
| Edit or delete single rules, facts, glossary terms and assets (admin) | `PATCH/DELETE /api/kb/<section>/<id>` |
| Hinglish slang in the demo glossary (yaar, bhai, bindaas, jhakaas, ekdum mast, paisa vasool) | `seed/glossary.json` |

## Run it

```bash
pip install -r requirements-dev.txt      # runtime + pytest
python run.py                            # http://127.0.0.1:5000  (open demo mode, no passcode)
python -m pytest -q                      # ~190 tests (browser tests skip if Chromium is missing)
```

### Configuration (environment variables)

Everything is listed, with comments, in [`.env.example`](.env.example). The ones that matter most:

| Variable | Purpose |
|---|---|
| `BRANDGUARD_ENV=production` | Real deployment: needs `BRANDGUARD_SECRET`, uses real accounts, marks cookies `Secure` (serve over HTTPS). |
| `BRANDGUARD_AUTH` | `accounts` (default in production: email + password, admin manages users) or `demo` (demo identities; in production it also needs `BRANDGUARD_PASSCODE`). |
| `BRANDGUARD_ADMIN_EMAIL` / `_PASSWORD` | First start only: creates the first admin in accounts mode. |
| `BRANDGUARD_DB` | SQLite file path (default `brandguard.db`). Migrations run automatically at start. |
| `ANTHROPIC_API_KEY` or (`BRANDGUARD_LLM_BASE_URL` + `BRANDGUARD_LLM_API_KEY` + `BRANDGUARD_MODEL`), `BRANDGUARD_MODEL`, `BRANDGUARD_LLM=off`, `BRANDGUARD_AI_TIMEOUT` | Optional AI judge. |
| `BRANDGUARD_AI_LOG`, `BRANDGUARD_AI_RETENTION_DAYS` | AI request log: metadata only by default, deleted after 30 days. |
| `BRANDGUARD_AI_REDACT`, `BRANDGUARD_AI_ASYNC` | Mask emails/links/amounts/phones before the AI sees text (default on); run the AI check in the background (default on with a real provider). |
| `BRANDGUARD_SSO_EMAIL_HEADER`, `BRANDGUARD_SSO_SECRET` | Sign-in through an identity-aware proxy (see docs/DEPLOYMENT.md). |
| `BRANDGUARD_LOG_JSON=1` | One JSON log line per request (never any content). `GET /healthz` is the health check. |

Deployment, monitoring, backup/restore, migrations and the production checklist: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Test guide, smoke test, manual phone/keyboard checklists and the restore drill: [docs/TESTING.md](docs/TESTING.md).
Data retention and what is sent to the AI: [docs/PRIVACY.md](docs/PRIVACY.md). Security model: [docs/SECURITY.md](docs/SECURITY.md).
A `Dockerfile`, `render.yaml`, GitHub Actions CI (tests, browser tests, `pip-audit`) and dependabot config are included.

Demo walkthrough: sign in as **Ira (admin)** → Knowledge base → *Load Brewline demo knowledge base*.
Sign in as **Neha (agency creator)** → New → *Load demo email* → *Review now*.
Fix findings, *Submit for approval*, then sign in as **Arjun (manager)** or **Meera (reviewer)** to approve.

Optional AI judge: `export ANTHROPIC_API_KEY=...`, or for any OpenAI-compatible provider set `BRANDGUARD_LLM_BASE_URL` (https), `BRANDGUARD_LLM_API_KEY` and `BRANDGUARD_MODEL` (model via `BRANDGUARD_MODEL`, default `claude-sonnet-5-5`; `BRANDGUARD_LLM=off` disables it).
The content is sent to the AI service only when it is first reviewed, when its author edits it, or when someone presses *Re-run review*. Accepting a fix does not re-send it; earlier AI suggestions are carried over and re-located in the new text.

## Code layout

```
brandguard/   engine.py (the checks)  workflow.py (roles, versions, approval)  kb.py (import, edit)  llm.py (AI judge)
              insights.py  record.py  retrieve.py  models.py  db.py  errors.py  app.py (HTTP API)
static/       index.html (markup)  style.css  js/ (core, auth, users, tour, insights, content, kb, main) - plain HTML/CSS/JS, no build step
seed/         synthetic Brewline Coffee guidelines, facts, glossary, assets, settings, demo email
scripts/      check_live_ai.py - end-to-end test of the real AI judge (needs a key and network)
docs/         deployment, privacy and security notes
tests/        ~190 tests: engine, workflow, accounts, access control, migrations, AI privacy, multi-process, UI, browser (e2e/)
```

## Architecture and main decisions

```
Content → Parse → Rules + retrieval → LLM judge → Verify → Findings store → Review UI → Approval
```

- **One finding model.** `Finding` (pydantic) cannot exist without a source id, a source quote, severity and confidence. Malformed records are rejected by validation.
- **Rules first, AI second.** Glossary matches, exclamation and capitals limits, price/date/fact matching, alt text and WCAG contrast are deterministic and fully explainable. The LLM only judges tone and messaging.
- **Grounded AI.** The model sees only the content plus the top guideline rules retrieved by BM25. It must return a rule code, a verbatim quote of the rule and a verbatim span of the content. `engine.verify` checks all three; anything that fails is discarded and counted in the review header. AI findings are labelled, capped at *medium* confidence and never auto-applied. Everything sent to the API is stored in `llm_log`.
- **Data-driven checks.** Which rule each check cites, and its limits, live in the `settings` table (imported from `seed/settings.json`), not in code. If a configured rule is missing from the knowledge base, the check is skipped with a visible warning instead of failing silently.
- **Human control is enforced in the server, not just the UI** (`workflow.py`): dismissals need a reason; dismissing fact, claim or low-confidence findings needs a manager or reviewer; approval needs every finding decided, a manager or reviewer who is not the author, and a reviewer specifically if a claim was dismissed; approved content is locked; every action is audited.
- **Access.** External agency users see only their own content and cannot browse the knowledge base. Each fact has an access level. Agency users see public facts only, internal creators see public and internal ones, and managers, reviewers and admins see everything. For a fact someone may not see, a finding says that something conflicts and where, but hides the fact, the approved value and the suggested fix, and "Accept fix" is refused, because applying it would reveal the value. They can rewrite the text themselves, and a manager can apply the fix for them. In the demo the launch date is confidential (an embargo); price, sourcing and roast are public.

## Deviations from the Round 1 plan (disclosure)

- **Flask instead of FastAPI.** FastAPI was not installable in the build environment (package installs were disabled). Pydantic still validates every finding, so the "malformed output is rejected" property is unchanged. The service layer is framework-independent, so a port is mechanical.
- **SQLite and BM25 instead of PostgreSQL + pgvector** for now (listed as dev default in the plan). Retrieval is keyword-based; embeddings are the planned upgrade.
- **Sign-in is a user switcher plus an optional shared passcode** (admin can have its own), so judges can try every role quickly. This is a demo mechanism, not real authentication: there are no individual accounts, SSO or password resets. Wrong passcodes are rate limited (10 per 5 minutes per address) and production mode refuses to start without one.

## Testing

`python -m pytest -q` runs about 155 tests, including: a guideline's confidential text never reaching a viewer without clearance; comments rejected for another version's finding; cross-site writes refused; real accounts with revocation; four processes writing one database; a real Chromium run through the tour; all seeded traps detected with citations; clean content produces no findings; fabricated AI quotes, rules and spans are rejected; an AI outage does not break the review; applying fixes makes no further AI calls; the full creator → manager → reviewer approval flow; role and access restrictions; passcode login and rate limiting; stale concurrent writes refused; input limits and malformed requests return clear 400s; real server bugs return 500 (not a disguised 404); and the UI's own colours meet the 4.5:1 contrast rule it enforces on others.
Writing these tests found and fixed several real bugs (an HTML page whose script silently failed to parse, a price span that swallowed a comma, "medium-dark roast" flagged as contradicting itself, "#10" flagged as a "#1" claim, "ADRs 300" read as a price, "No. 1" and "Rs. 399" split across sentences, "a affordable" after a word swap, a 50,000-character post producing an ~800 MB response, a dismissal silently covering a later identical word, and highlights landing on the wrong text after an emoji).

**Not yet tested:** the live LLM call against the real API (tests use a fake backend), PDF import with real-world scanned PDFs, a live deployment, and user testing with real teams.

## Known limitations

- Single organisation: workspaces are not yet isolated per organisation.
- SQLite with one writer: fine for a team, not for heavy concurrent use (writes are guarded so conflicts are refused rather than corrupting versions). Rate limits are per process.
- The AI tone check runs in an in-process background thread (20 s deadline); rule findings never wait for it. Submit waits until it finishes. There is no external job queue.
- Two-step sign-in (TOTP) and proxy-based SSO exist but are optional; nothing forces them. The database is not encrypted by the app (use an encrypted disk; `scripts/backup.py` encrypts backups). Masking before the AI covers emails, links, amounts, phone numbers and handles, not names or plain-worded secrets.
- Timestamps are stored in UTC and shown in the viewer's local time.
- Sentence and claim detection are rule-based and English-only; unusual phrasing can be missed.
- Rule-based fixes are minimal word swaps; stronger, intent-preserving rewrites are a Round 3 improvement.
- At most 300 findings are shown per review; if there are more, the rest is flagged and the content cannot be submitted until the visible ones are fixed and the review is run again.
- Amounts that are not tied to a known product ("free delivery above ₹999") are raised as low-confidence questions for a reviewer, not as errors. Negated claims ("not a light roast") are ignored; dates are compared only when they sit near the fact's own words.
- A dismissal carries to a later version only for the same wording in the same sentence.
- Glossary matching is for Latin script, including Hinglish. Devanagari terms are not matched reliably yet.
- Claim extraction covers prices (₹/Rs/INR), dates, rankings, common superlatives and keyword facts, not every possible claim.
- Uploaded images are read for size and an estimated background/text colour (Pillow); alt text is typed by the author and no vision model recognises what the picture shows.
- Not a substitute for legal advice.

## Next steps

1. Run `scripts/check_live_ai.py` with a real `ANTHROPIC_API_KEY`: the live call is the one path the tests cannot cover.
2. A vision model to describe images and draft alt text; a setting that forces two-step sign-in.
3. Intent-preserving rewrites with a diff view; masking of names and codenames before AI calls.
4. Per-organisation workspaces and PostgreSQL.

## AI disclosure

This plan and the code were prepared with AI assistance (Claude, via Claude Code) and reviewed by the author. The product itself can call an LLM API and labels every AI-generated finding.
