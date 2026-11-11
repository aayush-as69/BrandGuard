"""Smoke test for a running deployment, through the real proxy. Uses only the standard library.

    python scripts/smoke_test.py https://brandguard.example.com [--email you@x.in --password ...]

Checks: health endpoint, HTTPS and HSTS, security headers, no inline-script CSP, cross-site writes refused,
anonymous requests refused, and a real sign-in and sign-out (credentials are required unless --public-only). Exit code 0 = all passed.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

PASS, FAIL = "ok  ", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{PASS if ok else FAIL} {name}{(' - ' + detail) if detail and not ok else ''}")


def call(base, path, method="GET", body=None, headers=None, cookie=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, dict(r.headers), r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode(errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--code", help="current authenticator code, if two-step sign-in is on")
    ap.add_argument("--public-only", action="store_true", help="skip the signed-in checks (not recommended: they catch proxy problems)")
    a = ap.parse_args()
    if not a.public_only and not (a.email and a.password):
        ap.error("give --email and --password so a real sign-in is tested, or pass --public-only to skip it")
    base = a.base.rstrip("/")
    secure = base.startswith("https://")
    check("served over HTTPS", secure, "use the https:// address; production cookies are Secure")

    s, h, b = call(base, "/healthz")
    check("healthz returns ok", s == 200 and json.loads(b).get("status") == "ok", f"status {s}")
    h = {k.lower(): v for k, v in h.items()}
    s, h, _ = call(base, "/")
    h = {k.lower(): v for k, v in h.items()}
    check("page loads", s == 200)
    csp = h.get("content-security-policy", "")
    script = [d for d in csp.split(";") if d.strip().startswith("script-src")]
    check("CSP forbids inline script", bool(script) and "unsafe-inline" not in script[0], csp)
    check("clickjacking and sniffing headers", h.get("x-frame-options") == "DENY" and h.get("x-content-type-options") == "nosniff")
    if secure:
        check("HSTS present", "strict-transport-security" in h)
    s, _, _ = call(base, "/api/content")
    check("anonymous API request refused", s == 401, f"status {s}")
    s, _, _ = call(base, "/api/login", "POST", {"email": "x@y.z", "password": "x"}, {"Origin": "https://evil.example"})
    check("cross-site write refused", s == 403, f"status {s}")
    s, _, _ = call(base, "/api/users")
    check("account list not public", s in (401, 403), f"status {s}")

    if not a.public_only:
        body = {"email": a.email, "password": a.password}
        if a.code:
            body["code"] = a.code
        s, h, _ = call(base, "/api/login", "POST", body, {"Origin": base})
        check("sign-in works", s == 200, f"status {s}")
        cookie = (h.get("Set-Cookie") or h.get("set-cookie") or "").split(";")[0]
        if s == 200:
            check("session cookie is HttpOnly and Secure",
                  "httponly" in (h.get("Set-Cookie") or "").lower() and (not secure or "secure" in (h.get("Set-Cookie") or "").lower()))
            s, _, _ = call(base, "/api/content", cookie=cookie)
            check("signed-in request works", s == 200, f"status {s}")
            s, _, _ = call(base, "/api/logout", "POST", {}, {"Origin": base}, cookie)
            check("sign-out works", s == 200, f"status {s}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
