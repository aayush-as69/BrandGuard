# Deploying BrandGuard

BrandGuard is one Flask process plus a SQLite file. That is deliberate: it is easy to run, back up and reason about.
For a team of tens of people it is enough. For many concurrent writers or several servers, move to Postgres (see "Limits").

## Modes

| | Development (default) | Staging | Production |
|---|---|---|---|
| `BRANDGUARD_ENV` | unset | `staging` | `production` |
| Sign-in | demo identities, no passwords | real accounts | real accounts (enforced) |
| `BRANDGUARD_SECRET` | auto-generated beside the DB | required in practice | **required, the app refuses to start without it** |
| Secure cookies | no | behind HTTPS | yes |
| Demo identities | yes | no | no (`BRANDGUARD_AUTH=demo` must be chosen explicitly and needs `BRANDGUARD_PASSCODE`) |

Staging should use `BRANDGUARD_AUTH=accounts`, its own database and its own API key, so a test never touches real content.

## First deployment

1. Copy `.env.example`, fill it in, keep it out of git.
2. Build and run: `docker build -t brandguard . && docker run -p 8000:8000 -v bg-data:/data --env-file .env brandguard`
   (or deploy `render.yaml` as a Render blueprint).
3. Start once with `BRANDGUARD_ADMIN_EMAIL` and `BRANDGUARD_ADMIN_PASSWORD`. That creates the first admin. Remove both afterwards.
4. Sign in, open **Users**, add the team and agency accounts. Passwords are hashed (scrypt); deactivating an account or
   resetting its password signs that person out at once. Sessions end after 8 hours.
5. Put it behind HTTPS (the platform's TLS, or a reverse proxy). Set `BRANDGUARD_ALLOWED_ORIGINS` if the public URL differs from the Host the app sees.
6. Load the brand's guidelines, facts and glossary in the **Knowledge base** tab.

## Health and logs

`GET /healthz` returns `{"status":"ok","schema_version":N}` after a real database query, or 503. It needs no sign-in and reveals no data.
With `BRANDGUARD_LOG_JSON=1` each request logs one JSON line (time, method, path, status, user id, milliseconds). Content, passwords and
query strings are never logged.

## Database migrations

The schema version lives in SQLite's `PRAGMA user_version`. On every start the app applies any newer migration, each in its own
transaction, safe when several workers start together. Migrations are listed in `brandguard/db.py` (`MIGRATIONS`). To add one,
append `(next_number, "description", function)`; never edit an old one. **Back up before upgrading.**

## Backup and restore

SQLite in WAL mode can be copied safely with its own backup command while the app runs:

```
sqlite3 /data/brandguard.db ".backup '/backups/brandguard-$(date +%F).db'"
```

Keep the `.secret` file only if you did not set `BRANDGUARD_SECRET` (losing it just signs everyone out). To restore: stop the app,
replace `/data/brandguard.db` (delete any `-wal` and `-shm` files beside it), start the app, and check `/healthz`.
Test a restore before you need one. The backup contains content, comments and the audit trail, so protect it like the live data.

## Production checklist

- [ ] `BRANDGUARD_ENV=production`, long random `BRANDGUARD_SECRET`, HTTPS in front
- [ ] First admin created, bootstrap variables removed, demo users absent (`/api/users` is not public)
- [ ] Database on a persistent, encrypted disk; daily `.backup` copied off the machine; one restore tested
- [ ] `BRANDGUARD_AI_LOG=metadata` and a retention you have agreed with the brand owner (see PRIVACY.md)
- [ ] `ANTHROPIC_API_KEY` set only if the brand approves sending text to the provider; users can still opt out per review
- [ ] `/healthz` wired to the platform's health check; logs collected
- [ ] `pip-audit` (CI runs it) is clean; dependabot enabled
- [ ] Brand owners understand image checks use metadata, not pixels (SECURITY.md)

## Limits (honest list)

- Review runs inside the request. With AI on, a review can wait up to `BRANDGUARD_AI_TIMEOUT` seconds (default 20); rule findings never depend on it.
- Rate limits are per process (in memory). Run behind a proxy that also limits, or one worker per instance, if that matters.
- One SQLite file means one machine. Postgres is the upgrade path; the SQL is plain and the migration list is the contract.
- No SSO or multi-factor sign-in yet. Use a strong password policy and an identity-aware proxy if you need either.
