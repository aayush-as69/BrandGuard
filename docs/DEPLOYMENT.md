<div align="right"><img src="../assets/brandguard-mark.svg" width="34" alt="BrandGuard"></div>

> Configure a safe deployment, keep the service observable, and rehearse recovery before relying on real brand content.

[Documentation index](README.md) · [Deployment](DEPLOYMENT.md) · [Testing](TESTING.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md)

---

# Deployment guide

BrandGuard is one Flask process plus a SQLite file. That is deliberate: it is easy to run, back up and reason about.
For a team of tens of people it is enough. For many concurrent writers or several servers, move to Postgres (see "Limits").

## Modes

| | Development (default) | Staging | Production |
|---|---|---|---|
| `BRANDGUARD_ENV` | unset | `staging` | `production` |
| Sign-in | local demo identities | real accounts | real accounts (enforced) |
| `BRANDGUARD_SECRET` | auto-generated beside the DB | required in practice | **required, the app refuses to start without it** |
| Secure cookies | no | behind HTTPS | yes |
| Demo workspace | available locally | off by default | off by default; enable only on an isolated demo deployment with `BRANDGUARD_SEED_DEMO=1` and `BRANDGUARD_DEMO_PASSWORD` |

Staging should use `BRANDGUARD_AUTH=accounts`, its own database and its own API key, so a test never touches real content.

## First deployment

1. Copy `.env.example`, fill it in, keep it out of git.
2. Build and run: `docker build -t brandguard . && docker run -p 8000:8000 -v bg-data:/data --env-file .env brandguard`
   (or deploy `render.yaml` as a free-tier Render demo blueprint: no disk, so the database resets on restart; for real use add a persistent disk on a paid instance).
3. Start once with `BRANDGUARD_ADMIN_EMAIL` and `BRANDGUARD_ADMIN_PASSWORD`. That creates the first admin. Remove both afterwards.
4. Sign in, open **Users**, add the team and agency accounts. Passwords are hashed (scrypt); deactivating an account or
   resetting its password signs that person out at once. Sessions end after 8 hours.
5. Put it behind HTTPS (the platform's TLS, or a reverse proxy). Set `BRANDGUARD_ALLOWED_ORIGINS` if the public URL differs from the Host the app sees.
6. Load the brand's guidelines, facts and glossary in the **Knowledge base** tab.

## Health and logs

`GET /healthz` returns `{"status":"ok","schema_version":N}` after a real database query, or 503. It needs no sign-in and reveals no data.
With `BRANDGUARD_LOG_JSON=1` each request logs one JSON line (time, method, path, status, user id, milliseconds). Content, passwords and
query strings are never logged.

## Monitoring and alerts

- Point the platform's health check (or an external monitor: UptimeRobot, Better Stack, Cloud Monitoring) at `GET /healthz` every minute and alert
  after two failures in a row. A 503 means the database could not be read; 200 reports the schema version.
- Alert on a rising share of 5xx and 429 responses in the JSON logs (`status` field) and on any `Unhandled error` log line.
- Run `python scripts/smoke_test.py ...` from the monitor or CI after each deploy (it signs in through the real proxy).
- Watch disk space on the data volume: SQLite stops accepting writes when it is full.

## Verifying HTTPS and origin behaviour through the proxy

Set `BRANDGUARD_TRUSTED_PROXIES` to the number of reverse proxies in front of the app (1 for Render, Fly, a single nginx). Without it the app sees the proxy's address for every visitor, so ten failed sign-ins by anyone would lock everyone out; with it set but no proxy in front, a client could forge `X-Forwarded-For`, so never set it when the app is reachable directly. Origin checks compare hosts, not schemes, so an https page talking to an app that sees http still works.

The app trusts the `Host` it receives to decide which `Origin` may write. After deploying, the smoke test must pass **through the public
URL**. If the proxy rewrites `Host`, writes fail with "Cross-site request refused": either forward the original Host or list the public
origin in `BRANDGUARD_ALLOWED_ORIGINS`. Confirm by hand once: `curl -i https://your-host/healthz` shows `Strict-Transport-Security`, and
`curl -i -X POST https://your-host/api/login -H 'Origin: https://evil.example' -d '{}'` returns 403.

## Database migrations

The schema version lives in SQLite's `PRAGMA user_version`. On every start the app applies any newer migration, each in its own
transaction, safe when several workers start together. Migrations are listed in `brandguard/db.py` (`MIGRATIONS`). To add one,
append `(next_number, "description", function)`; never edit an old one. **Back up before upgrading.**

**If a migration fails or the process is killed during one:** each migration runs in a single transaction, so the database is left exactly as it
was (tests kill a process mid-migration to prove it). Fix the cause and start again; the app retries on every start. Nothing needs undoing.

**Rolling back a release that already migrated:** migrations only ever add (columns, tables, indexes), so the previous release still runs on the
newer schema. If you must return to the exact old schema, stop the app and restore the backup you took before the upgrade (see below).
You lose changes made since that backup, so prefer rolling forward with a fix.

## Single sign-on

Put an identity-aware proxy (oauth2-proxy, Cloudflare Access, Google IAP, ...) in front and set `BRANDGUARD_SSO_EMAIL_HEADER`
(for example `X-Auth-Request-Email`) and `BRANDGUARD_SSO_SECRET` (16+ characters). Configure the proxy to **strip those headers from
client requests**, then add the email header and an `X-SSO-Secret` header carrying the shared secret. The browser calls
`POST /api/sso/login`; it succeeds only for an existing, active account (an admin adds people first) and skips the password and code,
because the proxy has already authenticated them. Never expose the app directly to the internet in this mode without the proxy.

## Backup and restore (recommended: the script)

`python scripts/backup.py backup /data/brandguard.db /backups/bg.db.enc` makes a consistent copy while the app runs; set
`BRANDGUARD_BACKUP_KEY` (a Fernet key, `pip install cryptography`) to encrypt it. `python scripts/backup.py restore ...` checks the
copy's integrity before replacing the database (stop the app first). The manual `sqlite3 .backup` route below also works.

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
- [ ] Database on a persistent, encrypted disk (the app does not encrypt it); daily encrypted `scripts/backup.py` copied off the machine; one restore tested
- [ ] `BRANDGUARD_AI_LOG=metadata` and a retention you have agreed with the brand owner (see PRIVACY.md)
- [ ] An AI provider key (`ANTHROPIC_API_KEY`, or `BRANDGUARD_LLM_*`) set only if the brand approves sending text to the provider; users can still opt out per review
- [ ] `/healthz` wired to the platform's health check; logs collected
- [ ] Health check alert configured; smoke test passes through the public URL; one restore drill done (docs/TESTING.md)
- [ ] `pip-audit` (CI runs it) is clean; dependabot enabled
- [ ] Brand owners understand image checks measure pixels but do not recognise picture contents, and that logo detection is shape matching (QUALITY.md); existing databases re-import the knowledge base for rules G-08 and G-09

## Limits (honest list)

- With a real AI provider the tone check runs in a background thread: the author sees rule findings at once, the page refreshes when the AI finishes, and submit is blocked meanwhile. The queue is in-process (2 threads per worker, 20 s deadline); a check cut short by a restart is marked "interrupted" at the next start. A separate job queue (Celery/RQ) is only needed at much larger scale. `BRANDGUARD_AI_ASYNC=0` makes it synchronous.
- The sign-in throttle is shared by all workers on one machine (it lives in the database) and fails closed if the store is unreadable. Across several machines, move it and the database to shared services together.
- One SQLite file means one machine. Postgres is the upgrade path; the SQL is plain and the migration list is the contract.
- Two-step sign-in (authenticator app) is optional per user; there is no setting that forces it yet. Authenticator secrets are encrypted in the database with `BRANDGUARD_DATA_KEY` (or, if unset, a key derived from `BRANDGUARD_SECRET`); keep that key apart from the backups, and if you change it people re-enrol.

## Demo seed data and one-click demo entry (demo sites only)

Set `BRANDGUARD_SEED_DEMO=1` to load the synthetic Brewline knowledge base into an empty workspace on start. Add
`BRANDGUARD_DEMO_PASSWORD` (10+ characters) to also create four accounts that share it (`neha@`, `arjun@`, `meera@`,
`rahul@brewline.demo`: agency writer, manager, reviewer, in-house writer) and one sample draft. It only fills what is
empty, so it is safe on every start; on the free Render tier it re-creates the demo after each restart. Do not use a shared
password on a site that holds real content.
