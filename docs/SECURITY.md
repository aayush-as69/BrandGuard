# Security model

**Accounts.** Email and password, hashed with scrypt, minimum 10 characters, failed sign-ins throttled per address and per email.
Sessions are signed, HttpOnly, SameSite=Lax cookies (Secure in production) valid for 8 hours and tied to a per-user epoch,
so deactivating a user, changing their role or password ends their sessions immediately. The last active admin cannot be removed.

**Roles.** creator (writes), manager and reviewer (approve something they did not write), admin (knowledge base and users).
Agency users are *external*: they see only their own content and only public guidance.

**Source access.** Every rule and fact is public, internal or confidential. A finding that cites something the viewer may not see
is redacted (no quote, no rule text, no suggested fix from it), and "Accept fix" is refused. A missing source is treated as hidden.

**Request safety.** State-changing requests with a cross-site `Origin` or `Sec-Fetch-Site: cross-site` are refused. The CSP allows
no inline script (`script-src 'self'`), no framing, no plugins. All server text is HTML-escaped before display. Uploads are capped at 10 MB.

**AI.** Output is verified: a finding must quote a real rule and real text from the content or it is dropped. AI findings are labelled,
capped at medium confidence, never auto-applied. See PRIVACY.md.

**Image analysis uses metadata, not pixels.** BrandGuard checks the alt text, declared colours and declared dimensions that come with
an image. It does not look at the image itself, so it cannot tell that a picture shows the wrong logo. Vision analysis is future work.

**Out of scope today:** SSO, multi-factor sign-in, encryption at rest, per-tenant isolation (one database serves one brand/organisation),
a queued asynchronous AI worker. Report problems privately to the maintainer before opening a public issue.
