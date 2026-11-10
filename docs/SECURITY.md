<div align="right"><img src="../assets/brandguard-mark.svg" width="34" alt="BrandGuard"></div>

> A practical overview of identity, access boundaries, request protections, upload handling, and known security limits.

[Documentation index](README.md) · [Deployment](DEPLOYMENT.md) · [Testing](TESTING.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md)

---

# Security model

**Accounts.** Email and password, hashed with scrypt, minimum 10 characters, failed sign-ins throttled per address and per email.
Sessions are signed, HttpOnly, SameSite=Lax cookies (Secure in production) valid for 8 hours and tied to a per-user epoch,
so deactivating a user, changing their role or password ends their sessions immediately. The last active admin cannot be removed.

**Two-step sign-in.** Optional TOTP (secrets encrypted at rest) (RFC 6238, any authenticator app), checked on every password sign-in once enabled. A used code cannot be reused,
wrong codes count toward the same throttle, an admin can reset a lost device. **Single sign-on** works through an identity-aware proxy (see DEPLOYMENT.md).

**Roles.** creator (writes), manager and reviewer (approve something they did not write), admin (knowledge base and users).
Agency users are *external*: they see only their own content and only public guidance.

**Source access.** Every rule and fact is public, internal or confidential. A finding that cites something the viewer may not see
is redacted (no quote, no rule text, no suggested fix from it), and "Accept fix" is refused. A missing source is treated as hidden.

**Request safety.** State-changing requests with a cross-site `Origin` or `Sec-Fetch-Site: cross-site` are refused. The CSP allows
no inline script (`script-src 'self'`), no framing, no plugins. All server text is HTML-escaped before display. Uploads are capped at 10 MB.

**Uploads.** 10 MB cap per request, then per file: at most 500,000 characters of text, 200 PDF pages, no password-protected PDFs, and a .docx is
refused before parsing if its parts would unzip to over 50 MB or more than 100 times its size (zip bombs). Errors are clear 400s.

**Errors.** Database errors are logged on the server and never shown; the client gets a short safe message (for example "That email address is already in use").

**Throttle.** Failed sign-ins are counted (10 per client address, 40 per target email, so one attacker cannot lock a colleague out) in the shared database, so several workers enforce one limit; if the store fails, sign-in is refused.

**AI.** Output is verified: a finding must quote a real rule and real text from the content or it is dropped. AI findings are labelled,
capped at medium confidence, never auto-applied. See PRIVACY.md.

**Images.** An uploaded image is read on the server (Pillow): its size, and an *estimated* background and text colour from the pixels, which feed
the contrast check. The estimate is the most common colour and the one that contrasts most with it, so the author should confirm it. Alt text is
still typed by the author, and BrandGuard does not recognise what a picture shows (wrong logo, wrong product); a vision model for that is future work.

**Out of scope today:** forced multi-factor sign-in, encryption at rest by the app (use an encrypted volume), per-tenant isolation (one database serves one
brand/organisation), an external job queue for AI checks (the in-process one is described in DEPLOYMENT.md). Report problems privately to the maintainer before opening a public issue.
