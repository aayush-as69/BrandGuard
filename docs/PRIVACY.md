<div align="right"><img src="../assets/brandguard-mark.svg" width="34" alt="BrandGuard"></div>

> Understand what BrandGuard stores, what an optional AI provider receives, and how logs, retention, and deletion work.

[Documentation index](README.md) · [Deployment](DEPLOYMENT.md) · [Testing](TESTING.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md)

---

# Privacy and data retention

## What is stored
Content text and image metadata, findings, comments, decisions and an audit trail, in the database you control. Accounts store a name,
email, role and a password hash. Nothing is sent anywhere unless the AI judge is switched on.

## The AI judge
- **Off by default** unless an AI provider is configured (`ANTHROPIC_API_KEY`, or `BRANDGUARD_LLM_BASE_URL` with `BRANDGUARD_LLM_API_KEY` and `BRANDGUARD_MODEL`). `BRANDGUARD_LLM=off` forces it off.
- **What is sent** when it is on: the content text of that review, plus the few guideline rules that match it. Nothing else:
  no names, emails, other content or restricted facts. **Email addresses, links, money amounts, phone numbers and @handles are masked first** (`[[EMAIL_1]]`)
  and put back in the findings you see. `BRANDGUARD_AI_REDACT=off` turns the masking off. Rule-based checks run locally first; their findings never depend on AI.
- **Per-review choice:** every author sees a notice and a checkbox ("Use AI to judge tone"). Unticked means nothing leaves the server.
  Re-runs reuse earlier AI findings rather than sending the text again when the text is unchanged.
- **Disclosure:** the notice text comes from `/api/config` and states the provider, what is sent and how long records are kept.
- **Provider terms:** your API agreement with Anthropic governs how they handle requests. Check it against your client contracts.

## The AI request log
By default the log keeps **metadata only**: when, which model, a SHA-256 of the text, its length, which rule codes were sent, the outcome.
It cannot be turned back into the text. `BRANDGUARD_AI_LOG=full` also keeps the full prompt, for debugging; only admins can read
the payload. Rows older than `BRANDGUARD_AI_RETENTION_DAYS` (default 30; `0` keeps nothing) are deleted on every AI call and at start.

## Organisation-defined rules for the AI
- `BRANDGUARD_AI_MASK_PATTERNS` = JSON like `{"CODENAME": "Project \\w+"}`: anything matching is masked like the built-in patterns.
- `BRANDGUARD_AI_BLOCK_PATTERNS` = JSON like `{"EMBARGO": "(?i)embargoed"}`: content matching is never sent; the review says so and uses rules only.
- A broken pattern setting blocks sending (it never means "send anyway"). `BRANDGUARD_LLM=off` is the organisation-wide opt-out.

## Retention and deletion

| Data | Kept | Removed by |
|---|---|---|
| AI request log | 30 days by default (`BRANDGUARD_AI_RETENTION_DAYS`); metadata only unless `BRANDGUARD_AI_LOG=full` | automatic purge on every AI call and at start |
| Failed sign-in counters | 5 minutes | automatic |
| Content, versions, findings, comments, audit trail | until someone asks for deletion or the brand owner's retention period ends | `python scripts/delete_content.py DB ID "reason" "operator"` |
| Accounts | while active; deactivated accounts keep their name on past audit entries | deactivate in Users; remove by request with SQL after review |
| Backups | as long as you keep them; they hold the same data | your backup storage's lifecycle rule (suggest 30-90 days) |

Deleting content removes it from the live database and the AI log and leaves one audit line (who, when, why, never the content). **Older backups
still contain it until they expire**, so tell requesters that and set the backup lifecycle to match your policy. Agree the retention period
with the brand owner before go-live and write it here.

## Known gaps, stated plainly
- Masking covers those five patterns only. Names, product codenames and unreleased plans written in plain words are still sent: tick
  "Use AI" off for anything that must not leave the server.
- **No application-level encryption of the database, on purpose.** Findings, comments and the audit trail each hold excerpts of
  content, so encrypting one column would give a false sense of safety. Use an encrypted disk or volume (or SQLCipher), and encrypted backups
  (`scripts/backup.py` with `BRANDGUARD_BACKUP_KEY`).
- Deleting a user deactivates them; their content and audit entries stay, because the audit trail must remain whole.
