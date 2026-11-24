<div align="right"><img src="../assets/brandguard-mark.svg" width="34" alt="BrandGuard"></div>

> A practical overview of identity, access boundaries, request protections, upload handling, and known security limits.

[Documentation index](README.md) · [Deployment](DEPLOYMENT.md) · [Testing](TESTING.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md)

---

# Security model

**Accounts.** Email and password, hashed with scrypt, minimum 10 characters, failed sign-ins throttled per address and per email. Demo deployments may expose a separate prefilled **Try demo** entry point; it must not be enabled for real-content production environments. Demo role switching uses the existing authenticated demo session rather than repeatedly submitting credentials, and only hops between the seeded demo accounts (never to the real admin). Because those accounts share one public password, the server refuses password changes and two-step setup for them, so a visitor cannot lock the others out.
Sessions are signed, HttpOnly, SameSite=Lax cookies (Secure in production) valid for 8 hours and tied to a per-user epoch,
so deactivating a user, changing their role or password ends their sessions immediately. The last active admin cannot be removed.

**Demo mode is for demos only.** `BRANDGUARD_SEED_DEMO=1` together with `BRANDGUARD_DEMO_PASSWORD` publishes that password to every unauthenticated visitor (`/api/config` hands it to the landing page's **Try demo** button). Never set either on a deployment that holds real content. Local demo auth (`BRANDGUARD_AUTH=demo`, the default outside production) also lists every user at `/api/users` without signing in and signs anyone in with only the optional passcode (production refuses demo auth unless a passcode is set). Use real accounts for anything beyond a demo.

**Two-step sign-in.** Optional TOTP (secrets encrypted at rest) (RFC 6238, any authenticator app), checked on every password sign-in once enabled. A used code cannot be reused,
wrong codes count toward the same throttle, an admin can reset a lost device. **Single sign-on** works through an identity-aware proxy (see DEPLOYMENT.md).

**Roles.** creator (writes), manager and reviewer (approve something they did not write), admin (knowledge base and users).
Agency users are *external*: they see only their own content and only public guidance.

**Source access.** Every rule and fact is public, internal, confidential or restricted. Creators can see public/internal material; managers, reviewers and admins can see all four tiers. A finding that cites something the viewer may not see
is redacted (no quote, no rule text, no suggested fix from it), and "Accept fix" is refused. A missing source is treated as hidden.

**Request safety.** State-changing requests with a cross-site `Origin` or `Sec-Fetch-Site: cross-site` are refused. The CSP allows
no inline script (`script-src 'self'`), no framing, no plugins. All server text is HTML-escaped before display. Uploads are capped at 10 MB.

**Uploads.** 10 MB cap per request, then per file: at most 500,000 characters of text, 200 PDF pages, no password-protected PDFs, and a .docx is
refused before parsing if its parts would unzip to over 50 MB or more than 100 times its size (zip bombs). Errors are clear 400s.

**Errors.** Database errors are logged on the server and never shown; the client gets a short safe message (for example "That email address is already in use").

**Throttle.** Failed sign-ins (and failed single sign-on attempts, counted separately) are counted (10 per client address, 40 per target email, so one attacker cannot lock a colleague out) in the shared database, so several workers enforce one limit; if the store fails, sign-in is refused. Requests that send text to the AI provider (creating or revising content, re-running a review, AI rewrites, the AI benchmark) are capped per signed-in user, 30 per 5 minutes by default (`BRANDGUARD_AI_RATE_LIMIT`, `0` turns the cap off), so one account cannot burn through the provider budget.

**AI.** Output is verified: a finding must quote a real rule and real text from the content or it is dropped. AI findings are labelled,
capped at medium confidence, never auto-applied. See PRIVACY.md.

**Images.** An uploaded image is decoded on the server (Pillow, size and pixel limits checked first) and measured with numpy: brand-palette share, logo
shape, clear space and text contrast (see QUALITY.md). Measurements are stored per uploader and can only be attached to content by that user; the image
itself is not stored. The text colour is an estimate unless typed, so the author should confirm it. Alt text is
still typed by the author, and BrandGuard does not recognise what a picture shows (wrong logo, wrong product); a vision model for that is future work.

**Operational traceability.** API responses include a request ID and the same ID is emitted in structured JSON access logs. AI audit metadata also records provider and latency without storing prompts unless the explicit full-log setting is enabled.

**Out of scope today:** forced multi-factor sign-in, encryption at rest by the app (use an encrypted volume), per-tenant isolation (one database serves one
brand/organisation), an external job queue for AI checks (the in-process one is described in DEPLOYMENT.md). Report problems privately to the maintainer before opening a public issue.
