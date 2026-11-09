# Data retention and AI privacy

## What is stored
Content text and image metadata, findings, comments, decisions and an audit trail, in the database you control. Accounts store a name,
email, role and a password hash. Nothing is sent anywhere unless the AI judge is switched on.

## The AI judge
- **Off by default** unless `ANTHROPIC_API_KEY` is set. `BRANDGUARD_LLM=off` forces it off.
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

## Known gaps, stated plainly
- Masking covers those five patterns only. Names, product codenames and unreleased plans written in plain words are still sent: tick
  "Use AI" off for anything that must not leave the server.
- **No application-level encryption of the database, on purpose.** Findings, comments and the audit trail each hold excerpts of
  content, so encrypting one column would give a false sense of safety. Use an encrypted disk or volume (or SQLCipher), and encrypted backups
  (`scripts/backup.py` with `BRANDGUARD_BACKUP_KEY`).
- Deleting a user deactivates them; their content and audit entries stay, because the audit trail must remain whole.
