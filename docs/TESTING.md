<div align="right"><img src="../assets/brandguard-mark.svg" width="34" alt="BrandGuard"></div>

> Use automated checks and focused manual passes to verify review flows, accessibility, deployment health, and backup recovery.

[Documentation index](README.md) · [Deployment](DEPLOYMENT.md) · [Testing](TESTING.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md)

---

# Testing guide

`python -m pytest -q` runs everything automated (about 190 tests, including real-browser tests in `tests/e2e` that skip if
Chromium is not installed). `python -m pytest -q -m live` runs the live-provider tests; they need `ANTHROPIC_API_KEY`, use synthetic
Brewline text only, and also run from GitHub Actions (**Live AI check**, manual). The full path they cover is in `tests/test_ai_privacy.py`.

## Demo login and role-switch smoke test

When demo seeding is intentionally enabled:

1. Open the public landing page and confirm **Try demo** is visible.
2. Select it and confirm the `/login` form contains the configured demo email and password.
3. Sign in once.
4. Open the account menu (your name in the header) and switch between the seeded roles with **Switch demo role**.
5. Confirm each switch changes the active role without another email/password prompt, and that **Change password** and **Two-step sign-in** are not offered to the shared demo accounts.
6. Confirm the normal **Sign in** path remains available separately and does not prefill demo credentials unless the user explicitly selects the demo shortcut.

## Deployment smoke test (after every deploy)

```
python scripts/smoke_test.py https://brandguard.example.com --email you@example.com --password '...'
```
Checks health, HTTPS/HSTS, security headers, the strict CSP, refusal of anonymous and cross-site requests, and a real sign-in and
sign-out through the actual proxy. Exit code 0 means every check passed. Then look at the app once by hand (below).

## Manual checklist: phone and tablet (10 minutes, before a release)

Use a real phone, or browser dev tools at 375 x 740 and 768 x 1024.
- [ ] Sign-in fits without sideways scrolling; the keyboard does not hide the Sign in button.
- [ ] Content list, review screen, Knowledge base tables and Users table scroll inside their cards; the page itself does not scroll sideways.
- [ ] Highlights in the text are tappable and scroll to their finding; Accept / Edit / Dismiss buttons are easy to hit (not touching).
- [ ] Rotating the phone keeps what was typed in the new-content form.
- [ ] The AI notice and the "Use AI" checkbox are readable and tappable.
- [ ] Printing the approval record (browser "Print") fits one column, with the Print button hidden.
- [ ] Text zoomed to 200% is still usable.

## Manual checklist: keyboard-only and screen reader

Unplug the mouse. Automated checks (`tests/e2e/test_keyboard.py`) cover names on every control and Enter/Space on list items and highlights.
By hand, also confirm:
- [ ] Tab order follows the visual order on every screen; focus is always visible.
- [ ] After "Review now", "Save as new version", Approve and sign-out, focus lands somewhere sensible (not lost at the top of a long page).
- [ ] The account menu opens with Enter/Space, closes with Esc, and the in-page dialogs (Change password, Two-step sign-in) can be filled, submitted and cancelled with the keyboard. Esc closes a dialog.
- [ ] With a screen reader (NVDA or VoiceOver): toasts are announced (role status / alert), findings read as issue, source, severity, and the tour panel reads as a dialog.
- [ ] Colour is never the only signal: severity and status always have a text label.

## Restore drill (quarterly, and before relying on a new backup setup)

1. Take a backup: `python scripts/backup.py backup /data/brandguard.db /backups/drill.db.enc`.
2. On a spare machine or a scratch directory (never the live one): `python scripts/backup.py restore /backups/drill.db.enc /tmp/drill/brandguard.db`.
3. Start the app against it: `BRANDGUARD_DB=/tmp/drill/brandguard.db BRANDGUARD_SECRET=... python run.py`, open `/healthz` (expect `ok` and the same `schema_version`).
4. Sign in and open a recent piece of content; confirm its versions, findings and audit trail are there.
5. Write down the date, the backup's age and how long it took. A backup never restored is a hope, not a backup.
