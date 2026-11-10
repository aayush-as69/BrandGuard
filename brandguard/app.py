"""Flask app: JSON API plus the single-page review UI."""
from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from . import db as dbm
from . import insights
from . import imaging
from . import record
from . import throttle
from . import totp
from . import vault
from . import kb as kbm
from . import llm
from . import workflow as wf
from .errors import Forbidden, NotFound, RateLimited

ROOT = Path(__file__).resolve().parent.parent
LEVELS = kbm.ACCESS_LEVELS


class AuthError(Exception):
    pass


def payload() -> dict:
    """The JSON body as a dict; anything else (a list, a string) is a clear 400, not a crash."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    return data


def _persistent_secret(db_path: str) -> str:
    """A session key that survives restarts, kept beside the database (never in git)."""
    path = Path(db_path + ".secret")
    try:
        if path.exists():
            value = path.read_text().strip()
            if value:
                return value
        value = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(value)
        return value
    except OSError:
        return secrets.token_hex(32)  # read-only disk: fine for a demo, sessions reset on restart


MIN_PASSWORD = 10
ROLES = ("creator", "manager", "reviewer", "admin")
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _check_password_strength(pw: str) -> str:
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
    return pw


def _bootstrap_admin(c: sqlite3.Connection, required: bool) -> None:
    """Make sure a real deployment has someone who can sign in and add everyone else."""
    if c.execute("SELECT 1 FROM users WHERE role='admin' AND active=1 AND password_hash IS NOT NULL").fetchone():
        return
    email = os.environ.get("BRANDGUARD_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("BRANDGUARD_ADMIN_PASSWORD", "")
    if not email or not password:
        if required:
            raise RuntimeError("Accounts mode has no admin yet: set BRANDGUARD_ADMIN_EMAIL and BRANDGUARD_ADMIN_PASSWORD "
                               "for the first start (you can remove them afterwards).")
        return
    _check_password_strength(password)
    try:
        c.execute("INSERT INTO users(name, role, is_external, email, password_hash) VALUES (?,?,?,?,?)",
                  ("Administrator", "admin", 0, email, generate_password_hash(password)))
        c.commit()
    except sqlite3.IntegrityError:
        # Several workers start at once and all see "no admin yet"; the first insert wins. That is fine
        # if an admin exists now. If the email belongs to someone who is not an admin, say so plainly.
        c.rollback()
        if c.execute("SELECT 1 FROM users WHERE role='admin' AND active=1 AND password_hash IS NOT NULL").fetchone():
            return
        raise RuntimeError(f"BRANDGUARD_ADMIN_EMAIL ({email}) is already used by an account that is not an active "
                           "admin. Use another email, or fix that account.") from None


DEMO_ACCOUNTS = [  # (name, role, external): the same cast as demo mode, signed in with real accounts
    ("Neha", "creator", 1), ("Arjun", "manager", 0), ("Meera", "reviewer", 0), ("Rahul", "creator", 0)]


def _seed_demo_workspace(conn: sqlite3.Connection, db_file: str) -> None:
    """BRANDGUARD_SEED_DEMO=1: on an empty workspace, load the synthetic Brewline knowledge base, and, if
    BRANDGUARD_DEMO_PASSWORD is set (10+ characters), add the demo accounts and one sample draft. Safe to run
    from several workers at once (file lock) and on every start (only fills what is empty). For demo sites only."""
    import fcntl
    with open(db_file + ".seed.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not conn.execute("SELECT 1 FROM guidelines LIMIT 1").fetchone():
            kbm.seed_demo(conn, ROOT / "seed")
        password = os.environ.get("BRANDGUARD_DEMO_PASSWORD", "")
        if password:
            _check_password_strength(password)
            pw_hash = generate_password_hash(password)
            for name, role, ext in DEMO_ACCOUNTS:
                email = f"{name.lower()}@brewline.demo"
                if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                    conn.execute("INSERT INTO users(name, role, is_external, email, password_hash) VALUES (?,?,?,?,?)",
                                 (name, role, ext, email, pw_hash))
            conn.commit()
            rahul = conn.execute("SELECT * FROM users WHERE email='rahul@brewline.demo'").fetchone()
            if rahul and not conn.execute("SELECT 1 FROM content LIMIT 1").fetchone():
                sample = json.loads((ROOT / "seed" / "demo_email.json").read_text(encoding="utf-8"))
                wf.create_content(conn, dict(rahul), sample["title"], sample["body"], sample.get("images", []), None, "fresh")


def create_app(db_path: str | None = None, llm_call=None) -> Flask:
    """llm_call(system, user, model) -> str lets tests (or a private model) replace the AI backend."""
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    production = os.environ.get("BRANDGUARD_ENV") == "production"
    auth_mode = os.environ.get("BRANDGUARD_AUTH") or ("accounts" if production else "demo")
    if auth_mode not in ("demo", "accounts"):
        raise RuntimeError("BRANDGUARD_AUTH must be 'accounts' or 'demo'")
    passcode = os.environ.get("BRANDGUARD_PASSCODE", "")
    admin_passcode = os.environ.get("BRANDGUARD_ADMIN_PASSCODE", "") or passcode
    secret = os.environ.get("BRANDGUARD_SECRET", "")
    if production and not secret:
        raise RuntimeError("BRANDGUARD_ENV=production needs BRANDGUARD_SECRET (the session signing key).")
    if production and auth_mode == "demo" and not passcode:
        raise RuntimeError(
            "BRANDGUARD_AUTH=demo in production needs BRANDGUARD_PASSCODE. Without it anyone could sign in as admin. "
            "Use BRANDGUARD_AUTH=accounts for a real deployment.")
    accounts = auth_mode == "accounts"
    proxies = int(os.environ.get("BRANDGUARD_TRUSTED_PROXIES", "0") or 0)
    sso_header = os.environ.get("BRANDGUARD_SSO_EMAIL_HEADER", "")
    sso_secret = os.environ.get("BRANDGUARD_SSO_SECRET", "") if accounts and sso_header else ""
    if sso_header and accounts and len(sso_secret) < 16:
        raise RuntimeError("BRANDGUARD_SSO_EMAIL_HEADER needs BRANDGUARD_SSO_SECRET of at least 16 characters")
    db_file = db_path or os.environ.get("BRANDGUARD_DB", str(ROOT / "brandguard.db"))
    app.config.update(
        SECRET_KEY=secret or _persistent_secret(db_file),
        DB_PATH=db_file,
        LLM_CALL=llm_call,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB uploads
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=8 * 3600,  # sign-in lasts a working day at most
    )

    boot = dbm.connect(app.config["DB_PATH"])
    try:
        dbm.init(boot, demo_users=not accounts)
        if accounts:
            _bootstrap_admin(boot, production)
            if os.environ.get("BRANDGUARD_SEED_DEMO") == "1":
                _seed_demo_workspace(boot, app.config["DB_PATH"])
        wf.settle_interrupted_reviews(boot)
        llm.purge_log(boot)  # honour the retention period at every start
    finally:
        boot.close()

    # ----------------------------------------------------------------- plumbing
    def conn() -> sqlite3.Connection:
        if "db" not in g:
            g.db = dbm.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    def me() -> dict:
        uid = session.get("uid")
        row = conn().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
        if not row or not row["active"] or session.get("epoch", 0) != row["session_epoch"]:
            raise AuthError("Please sign in")
        user = dict(row)
        user.pop("password_hash", None)
        user["mfa"] = bool(user.get("totp_secret"))
        for secret_col in ("totp_secret", "totp_pending", "totp_last"):
            user.pop(secret_col, None)
        return user

    def ai_mode(data: dict) -> str:
        """"fresh" unless the author switched AI review off for this request."""
        flag = data.get("use_ai", True)
        if not isinstance(flag, bool):
            raise ValueError("use_ai must be true or false")
        return "fresh" if flag else "off"

    def judge_factory(c, content_id, version):
        return llm.make_judge(c, content_id, version, call=app.config["LLM_CALL"])

    # With a real provider the AI check runs in the background so the author sees rule findings at once.
    # (An injected test backend stays synchronous unless BRANDGUARD_AI_ASYNC=1.)
    ai_async = (os.environ.get("BRANDGUARD_AI_ASYNC") == "1"
                or (llm_call is None and os.environ.get("BRANDGUARD_AI_ASYNC", "1") != "0"))
    if proxies:  # behind N reverse proxies: use their X-Forwarded-For/Proto/Host so client IPs and https are right
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies)
    elif production:
        app.logger.warning("BRANDGUARD_TRUSTED_PROXIES is not set: behind a proxy every visitor shares one address, "
                           "so the sign-in throttle would count them together. Set it to the number of proxies in front.")
    def seal(v: str) -> str:
        return vault.seal(v, app.secret_key)

    def unseal(v):
        return vault.unseal(v, app.secret_key)

    app.ai_futures = []
    if ai_async:
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-review")

        def run_ai_job(content_id: int, version: int) -> None:
            c = dbm.connect(app.config["DB_PATH"])
            try:
                wf.complete_ai_review(c, content_id, version, judge_factory)
            except Exception:
                app.logger.exception("AI review job failed")
            finally:
                c.close()

        def schedule(cid: int, ver: int) -> None:
            app.ai_futures[:] = [f for f in app.ai_futures if not f.done()]  # keep only unfinished jobs (no slow leak)
            app.ai_futures.append(pool.submit(run_ai_job, cid, ver))

        judge_factory.schedule = schedule

    @app.before_request
    def guard_origin():
        """Refuse cross-site writes: a state-changing request must come from this site."""
        g.t0 = time.perf_counter()
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                return jsonify(error="Cross-site request refused"), 403
            origin = request.headers.get("Origin")
            if origin == "null":
                return jsonify(error="Cross-site request refused"), 403
            if origin:
                # Compare the host, not the scheme: behind a TLS-terminating proxy the app sees http while the browser sent https.
                allowed_hosts = {request.host.lower()}
                allowed_hosts.update(urlsplit(o.strip()).netloc.lower() for o in
                                     os.environ.get("BRANDGUARD_ALLOWED_ORIGINS", "").split(",") if o.strip())
                if urlsplit(origin).netloc.lower() not in allowed_hosts:
                    return jsonify(error="Cross-site request refused"), 403
        return None

    @app.get("/healthz")
    def healthz():
        try:
            version = dbm.schema_version(conn())
            conn().execute("SELECT 1").fetchone()
        except Exception:
            app.logger.exception("health check failed")
            return jsonify(status="error"), 503
        return jsonify(status="ok", schema_version=version)

    @app.after_request
    def access_log(resp):
        if os.environ.get("BRANDGUARD_LOG_JSON") == "1":
            print(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "method": request.method, "path": request.path,
                "status": resp.status_code, "user": session.get("uid"),
                "ms": round((time.perf_counter() - g.get("t0", time.perf_counter())) * 1000, 1)}), flush=True)
        return resp

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if production:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(AuthError)
    def _auth(e):
        return jsonify(error=str(e)), 401

    @app.errorhandler(Forbidden)
    def _perm(e):
        return jsonify(error=str(e)), 403

    @app.errorhandler(NotFound)
    def _missing(e):
        return jsonify(error=str(e) or "Not found"), 404

    @app.errorhandler(RateLimited)
    def _limited(e):
        return jsonify(error=str(e)), 429

    @app.errorhandler(HTTPException)
    def _http(e):
        if not request.path.startswith("/api/"):
            return e
        msg = "That file is too large (limit 10 MB)" if e.code == 413 else (e.description or e.name)
        return jsonify(error=msg), e.code

    @app.errorhandler(Exception)
    def _unexpected(e):
        # A genuine bug (KeyError, TypeError, ...) is a 500 that is logged, never dressed up as a 404.
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return jsonify(error="Something went wrong on the server."), 500

    @app.errorhandler(ValueError)
    def _bad(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def _integrity(e):
        app.logger.warning("integrity error on %s %s: %s", request.method, request.path, e)  # detail stays on the server
        if "users.email" in str(e) or "idx_users_email" in str(e):
            return jsonify(error="That email address is already in use"), 400
        return jsonify(error="That change conflicts with existing data and was not saved"), 400

    # -------------------------------------------------------------------- pages
    @app.get("/")
    @app.get("/login")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # --------------------------------------------------------------------- auth
    @app.get("/api/users")
    def users():
        if accounts:  # a real deployment never publishes who has an account
            if me()["role"] != "admin":
                raise Forbidden("Only an admin can list accounts")
            rows = conn().execute("SELECT id, name, role, is_external, email, active, last_login, (totp_secret IS NOT NULL) AS mfa FROM users ORDER BY id")
        else:
            rows = conn().execute("SELECT id, name, role, is_external FROM users ORDER BY id")
        return jsonify([dict(r) for r in rows])

    @app.get("/api/config")
    def config():
        ai_on = llm.ai_available(app.config["LLM_CALL"])
        demo_available = bool(accounts and os.environ.get("BRANDGUARD_SEED_DEMO") == "1" and os.environ.get("BRANDGUARD_DEMO_PASSWORD"))
        return jsonify(
            auth=auth_mode, sso=bool(sso_secret),
            demo_available=demo_available,
            demo_email="arjun@brewline.demo" if demo_available else "",
            demo_password=os.environ.get("BRANDGUARD_DEMO_PASSWORD", "") if demo_available else "",
            passcode_required=bool(not accounts and (passcode or admin_passcode)),
            ai={"enabled": ai_on, "provider": llm.provider_name(), "log": llm.log_mode(), "retention_days": llm.retention_days(),
                "redaction": llm.redact_enabled(),
                "notice": ("When AI review is on, the text of your content and the few guideline rules that match it are "
                           f"sent to {llm.provider_name()} to judge tone"
                           + (", with email addresses, links, money amounts, phone numbers and @handles masked first" if llm.redact_enabled() else "")
                           + ". Nothing else is sent. You can switch it off for any "
                           f"review. A record of each request is kept for {llm.retention_days()} days "
                           + ("including the full text sent." if llm.log_mode() == "full" else "without the text itself."))
                if ai_on else ""},
        )

    def start_session(row, demo: bool = False) -> None:
        session.clear()
        session.permanent = True
        session["uid"] = row["id"]
        session["epoch"] = row["session_epoch"]
        if demo:
            session["demo"] = True

    @app.post("/api/login")
    def login():
        data = payload()
        c = conn()
        if accounts:
            email = str(data.get("email") or "").strip().lower()
            who = request.remote_addr or "?"
            throttle.check(c, who, "email:" + email)
            row = c.execute("SELECT * FROM users WHERE lower(email)=? AND active=1", (email,)).fetchone() if email else None
            good = check_password_hash(row["password_hash"] if row and row["password_hash"] else _DUMMY_HASH,
                                       str(data.get("password") or ""))
            if not (row and row["password_hash"] and good):
                throttle.record(c, who, "email:" + email)
                raise AuthError("Wrong email or password")
            if row["totp_secret"]:
                key = unseal(row["totp_secret"])
                step = totp.verify(key, str(data.get("code") or ""), row["totp_last"]) if (data.get("code") and key) else None
                if step is None:
                    if data.get("code"):  # a wrong code counts like a wrong password
                        throttle.record(c, who, "email:" + email)
                    return jsonify(error="Enter the 6-digit code from your authenticator app", mfa_required=True), 401
                c.execute("UPDATE users SET totp_last=? WHERE id=?", (step, row["id"]))
            c.execute("UPDATE users SET last_login=? WHERE id=?", (dbm.now(), row["id"]))
            c.commit()
        else:
            row = c.execute("SELECT * FROM users WHERE id=?", (data.get("user_id"),)).fetchone()
            if not row:
                raise NotFound("No such user")
            expected = admin_passcode if row["role"] == "admin" else passcode
            if expected:
                who = request.remote_addr or "?"
                throttle.check(c, who)
                given = str(data.get("passcode") or "")
                if not hmac.compare_digest(given.encode(), expected.encode()):
                    throttle.record(c, who)
                    raise Forbidden("Wrong passcode")
        start_session(row, demo=not accounts)
        return jsonify({k: row[k] for k in ("id", "name", "role", "is_external", "email")})

    @app.post("/api/demo/switch-role")
    def demo_switch_role():
        c = conn()
        demo_site = bool(accounts and os.environ.get("BRANDGUARD_SEED_DEMO") == "1" and os.environ.get("BRANDGUARD_DEMO_PASSWORD"))
        if accounts:
            # A seeded demo site: only someone already signed in as one of the demo accounts may hop between them.
            if not demo_site or not str(me().get("email") or "").endswith("@brewline.demo"):
                raise Forbidden("Demo role switching is only available in the demo workspace")
        elif not session.get("demo"):
            raise Forbidden("Demo role switching is only available in the demo workspace")
        role = str(payload().get("role") or "").strip().lower()
        if accounts:
            email = {"creator": "rahul", "manager": "arjun", "reviewer": "meera", "agency": "neha"}.get(role)
            row = c.execute("SELECT * FROM users WHERE email=? AND active=1", (email + "@brewline.demo",)).fetchone() if email else None
            if not email:
                raise ValueError("Choose a valid demo role")
        else:
            user_id = {"creator": 5, "manager": 2, "reviewer": 3, "admin": 4}.get(role)
            if not user_id:
                raise ValueError("Choose a valid demo role")
            row = c.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not row:
            raise NotFound("That demo role is unavailable")
        start_session(row, demo=True)
        return jsonify({k: row[k] for k in ("id", "name", "role", "is_external", "email")})

    @app.post("/api/password")
    def change_password():
        user, data = me(), payload()
        c = conn()
        row = c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row["password_hash"] or not check_password_hash(row["password_hash"], str(data.get("current") or "")):
            raise Forbidden("Current password is wrong")
        c.execute("UPDATE users SET password_hash=?, session_epoch=session_epoch+1 WHERE id=?",
                  (generate_password_hash(_check_password_strength(data.get("new"))), user["id"]))
        c.commit()
        start_session(c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())  # other devices are signed out
        return jsonify(ok=True)

    @app.post("/api/sso/login")
    def sso_login():
        """Sign in via an identity-aware reverse proxy (oauth2-proxy, Cloudflare Access, ...). The proxy must strip these
        headers from client requests and add them itself; the shared secret proves the request came through it."""
        if not sso_secret:
            raise NotFound("Single sign-on is not configured")
        given = request.headers.get("X-SSO-Secret", "")
        email = request.headers.get(sso_header, "").strip().lower()
        if not hmac.compare_digest(given.encode(), sso_secret.encode()) or not email:
            raise AuthError("Single sign-on failed")
        c = conn()
        row = c.execute("SELECT * FROM users WHERE lower(email)=? AND active=1", (email,)).fetchone()
        if not row:
            raise Forbidden("No BrandGuard account for this identity. Ask an admin to add you.")
        c.execute("UPDATE users SET last_login=? WHERE id=?", (dbm.now(), row["id"]))
        c.commit()
        start_session(row)
        return jsonify({k: row[k] for k in ("id", "name", "role", "is_external", "email")})

    @app.post("/api/image/analyze")
    def image_analyze():
        me()
        f = request.files.get("image")
        if not f:
            raise ValueError("Attach an image file")
        try:
            return jsonify(imaging.analyse(f.read(imaging.MAX_BYTES + 1)))
        except imaging.ImageError as exc:
            raise ValueError(str(exc))

    @app.post("/api/mfa/setup")
    def mfa_setup():
        user = me()
        secret = totp.new_secret()
        conn().execute("UPDATE users SET totp_pending=? WHERE id=?", (seal(secret), user["id"]))
        conn().commit()
        return jsonify(secret=secret, uri=totp.uri(secret, user.get("email") or user["name"]))

    @app.post("/api/mfa/enable")
    def mfa_enable():
        user, data, c = me(), payload(), conn()
        row = c.execute("SELECT totp_pending FROM users WHERE id=?", (user["id"],)).fetchone()
        pending = unseal(row["totp_pending"])
        step = totp.verify(pending, str(data.get("code") or "")) if pending else None
        if step is None:
            raise ValueError("That code is not right. Check the time on your phone and try the next code.")
        c.execute("UPDATE users SET totp_secret=totp_pending, totp_pending=NULL, totp_last=?, session_epoch=session_epoch+1 WHERE id=?",
                  (step, user["id"]))
        c.commit()
        start_session(c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        return jsonify(ok=True)

    @app.post("/api/mfa/disable")
    def mfa_disable():
        user, data, c = me(), payload(), conn()
        row = c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row["totp_secret"]:
            raise ValueError("Two-step sign-in is not on")
        if not check_password_hash(row["password_hash"] or _DUMMY_HASH, str(data.get("password") or "")) \
                or totp.verify(unseal(row["totp_secret"]) or "", str(data.get("code") or ""), row["totp_last"]) is None:
            raise Forbidden("Password or code is wrong")
        c.execute("UPDATE users SET totp_secret=NULL, totp_pending=NULL, session_epoch=session_epoch+1 WHERE id=?", (user["id"],))
        c.commit()
        start_session(c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        return jsonify(ok=True)

    def admin_only() -> dict:
        user = me()
        if user["role"] != "admin":
            raise Forbidden("Only an admin can manage accounts")
        return user

    def other_admins(c, user_id: int) -> int:
        return c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (user_id,)).fetchone()[0]

    @app.post("/api/users")
    def create_user():
        admin_only()
        data, c = payload(), conn()
        name, email = str(data.get("name") or "").strip(), str(data.get("email") or "").strip().lower()
        role = data.get("role")
        if not name or "@" not in email:
            raise ValueError("A name and a valid email are required")
        if role not in ROLES:
            raise ValueError("Role must be one of: " + ", ".join(ROLES))
        if data.get("is_external") and role != "creator":
            raise ValueError("An agency (external) account can only be a writer (creator)")
        pw = generate_password_hash(_check_password_strength(data.get("password")))
        cur = c.execute("INSERT INTO users(name, role, is_external, email, password_hash) VALUES (?,?,?,?,?)",
                        (name, role, 1 if data.get("is_external") else 0, email, pw))
        c.commit()
        return jsonify(id=cur.lastrowid), 201

    @app.patch("/api/users/<int:user_id>")
    def update_user(user_id: int):
        admin = admin_only()
        data, c = payload(), conn()
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise NotFound("No such user")
        for flag in ("active", "is_external", "reset_mfa"):
            if flag in data and not isinstance(data[flag], bool):
                raise ValueError(f"{flag} must be true or false")
        role = data.get("role", row["role"])
        active = 1 if data.get("active", bool(row["active"])) else 0
        external = 1 if data.get("is_external", bool(row["is_external"])) else 0
        if role not in ROLES:
            raise ValueError("Role must be one of: " + ", ".join(ROLES))
        if external and role != "creator":
            raise ValueError("An agency (external) account can only be a writer (creator)")
        if row["role"] == "admin" and (role != "admin" or not active) and other_admins(c, user_id) == 0:
            raise ValueError("There must always be at least one active admin")
        sets, args = ["role=?", "active=?", "is_external=?"], [role, active, external]
        if "name" in data and str(data["name"]).strip():
            sets.append("name=?"); args.append(str(data["name"]).strip())
        # anything that changes what someone may do, or a new password, ends their current sign-ins
        if data.get("reset_mfa"):  # lost phone: the admin clears it, the person sets it up again
            sets.append("totp_secret=NULL"); sets.append("totp_pending=NULL")
        if data.get("password") or data.get("reset_mfa") or role != row["role"] or active != row["active"] or external != row["is_external"]:
            sets.append("session_epoch=session_epoch+1")
        if data.get("password"):
            sets.append("password_hash=?"); args.append(generate_password_hash(_check_password_strength(data["password"])))
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, user_id))
        c.commit()
        if user_id == admin["id"]:  # an admin editing themselves stays signed in
            start_session(c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    def whoami():
        return jsonify(me())

    # ----------------------------------------------------------- knowledge base
    @app.get("/api/kb")
    def kb_browse():
        user = me()
        level = wf.clearance(user)
        if level < 0:
            raise Forbidden("External users cannot browse confidential brand material")
        c = conn()
        guidelines = []
        for gl in c.execute("SELECT * FROM guidelines ORDER BY id"):
            if LEVELS[gl["access_level"]] > level:
                continue
            rules = [dict(r) for r in c.execute(
                "SELECT code, title, text FROM rules WHERE guideline_id=? ORDER BY id", (gl["id"],))]
            guidelines.append({**dict(gl), "rules": rules})
        facts = [dict(r) for r in c.execute("SELECT code, kind, statement, source, access_level, data FROM facts ORDER BY id")
                 if LEVELS[r["access_level"]] <= level]
        for f in facts:
            f["data"] = json.loads(f["data"]) if user["role"] == "admin" else None  # the checking data is for editing
        assets = [dict(r) for r in c.execute("SELECT id, name, kind, note, access_level FROM assets ORDER BY id")
                  if LEVELS[r["access_level"]] <= level]
        glossary = [dict(r) for r in c.execute("SELECT id, term, preferred, kind, rule_code, note FROM glossary ORDER BY id")]
        return jsonify(guidelines=guidelines, facts=facts, glossary=glossary, assets=assets)

    @app.route("/api/kb/<kind>/<key>", methods=["PATCH", "DELETE"])
    def kb_item(kind: str, key: str):
        """Admin: change or remove one rule, fact, glossary term or asset."""
        user = me()
        if user["role"] != "admin":
            raise Forbidden("Only an admin can change the knowledge base")
        ops = {"rules": (kbm.update_rule, kbm.delete_rule, False), "facts": (kbm.update_fact, kbm.delete_fact, False),
               "glossary": (kbm.update_glossary, kbm.delete_glossary, True), "assets": (kbm.update_asset, kbm.delete_asset, True)}
        if kind not in ops:
            raise NotFound("Unknown knowledge-base section")
        update, delete, numeric = ops[kind]
        if numeric:
            if not key.isdigit():
                raise NotFound("No such item")
            key = int(key)
        c = conn()
        if request.method == "PATCH":
            patch = payload()
            update(c, key, patch)
            wf.audit(c, None, user["id"], "kb_edited", f"{kind}/{key}: {', '.join(sorted(patch))}")
        else:
            delete(c, key)
            wf.audit(c, None, user["id"], "kb_deleted", f"{kind}/{key}")
        c.commit()
        return jsonify(ok=True)

    @app.post("/api/kb/seed")
    def kb_seed():
        if me()["role"] != "admin":
            raise Forbidden("Only an admin can load the knowledge base")
        out = kbm.seed_demo(conn(), ROOT / "seed")
        wf.audit(conn(), None, me()["id"], "kb_seeded", json.dumps(out))
        conn().commit()
        return jsonify(out)

    @app.post("/api/kb/import")
    def kb_import():
        user = me()
        if user["role"] != "admin":
            raise Forbidden("Only an admin can import knowledge-base material")
        kind = request.form.get("kind", "")
        upload = request.files.get("file")
        text = request.form.get("text", "")
        raw_name = upload.filename if upload else "pasted.txt"
        if upload:
            data = upload.read()
            text = kbm.extract_text(raw_name, data) if kind == "guidelines" else data.decode("utf-8-sig", "replace")
        text = text.lstrip("\ufeff")  # Windows editors add an invisible byte-order mark
        if not text.strip():
            raise ValueError("Provide a file or paste text")
        level = request.form.get("access_level", "internal")
        c = conn()
        if kind == "guidelines":
            title = request.form.get("title") or Path(raw_name).stem
            result = kbm.import_guidelines(c, title, text, level)
        elif kind in ("facts", "glossary", "assets", "settings"):
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, RecursionError) as exc:
                raise ValueError(f"{kind} must be valid JSON" + (f": {exc}" if isinstance(exc, json.JSONDecodeError) else " (too deeply nested)")) from exc
            fn = {"facts": kbm.import_facts, "glossary": kbm.import_glossary,
                  "assets": kbm.import_assets, "settings": kbm.import_settings}[kind]
            if kind != "settings" and not isinstance(payload, list):
                raise ValueError(f"{kind} must be a JSON list")
            result = {"imported": fn(c, payload)}
        else:
            raise ValueError("kind must be guidelines, facts, glossary, assets or settings")
        wf.audit(c, None, user["id"], "kb_import", f"{kind}: {result}")
        c.commit()
        return jsonify(result)

    @app.get("/api/demo")
    def demo():
        me()
        return jsonify(json.loads((ROOT / "seed" / "demo_email.json").read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ content
    def finding_dict(r, visible: set[str]) -> dict:
        d = dict(r)
        d["ai_generated"] = bool(d["ai_generated"])
        d["needs_reviewer"] = bool(d["needs_reviewer"])
        d["restricted"] = False
        return wf.redact(d) if wf.is_restricted(d, visible) else d

    @app.get("/api/content")
    def content_list():
        user = me()
        try:
            limit = min(200, max(1, int(request.args.get("limit", 50))))
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            raise ValueError("limit and offset must be whole numbers")
        resp = jsonify(wf.list_content(conn(), user, limit, offset))
        resp.headers["X-Total-Count"] = str(wf.count_content(conn(), user))
        return resp

    @app.post("/api/content")
    def content_create():
        user, data = me(), payload()
        cid = wf.create_content(conn(), user, data.get("title"), data.get("body"), data.get("images"), judge_factory,
                                ai_mode(data))
        return jsonify(id=cid), 201

    def detail_payload(user: dict, c: sqlite3.Connection, cid: int) -> dict:
        content = wf.get_content(c, user, cid)
        v = wf.current(c, content)
        visible = wf.visible_sources(c, user)
        findings = [finding_dict(r, visible) for r in c.execute(
            "SELECT f.*, u.name AS decided_by_name FROM findings f LEFT JOIN users u ON u.id=f.decided_by "
            "WHERE f.content_id=? AND f.version=? ORDER BY CASE WHEN f.span_start<0 THEN 1 ELSE 0 END, f.span_start, f.id",
            (cid, content["current_version"]))]
        history = [finding_dict(r, visible) for r in c.execute(
            "SELECT f.*, u.name AS decided_by_name FROM findings f LEFT JOIN users u ON u.id=f.decided_by "
            "WHERE f.content_id=? AND f.version<? AND f.decision IN ('accepted','edited') ORDER BY f.id",
            (cid, content["current_version"]))]
        claims = [dict(r) for r in c.execute(
            "SELECT text, status, source_id FROM claims WHERE content_id=? AND version=? ORDER BY id",
            (cid, content["current_version"]))]
        comments = [dict(r) for r in c.execute(
            "SELECT m.*, u.name AS author, u.role AS role FROM comments m JOIN users u ON u.id=m.user_id "
            "WHERE m.content_id=? ORDER BY m.id", (cid,))]
        versions = [dict(r) for r in c.execute(
            "SELECT v.version, v.note, v.created_at, u.name AS author FROM versions v JOIN users u ON u.id=v.created_by "
            "WHERE v.content_id=? ORDER BY v.version DESC", (cid,))]
        author = c.execute("SELECT name FROM users WHERE id=?", (content["author_id"],)).fetchone()["name"]
        approver = c.execute(
            "SELECT u.name FROM audit a JOIN users u ON u.id=a.user_id "
            "WHERE a.content_id=? AND a.action='approved' ORDER BY a.id DESC LIMIT 1", (cid,)).fetchone()
        content["approved_by"] = approver["name"] if approver else None
        content["approved_at"] = c.execute(
            "SELECT created_at FROM audit WHERE content_id=? AND action='approved' ORDER BY id DESC LIMIT 1",
            (cid,)).fetchone()
        content["approved_at"] = content["approved_at"]["created_at"] if content["approved_at"] else None
        audit_rows = []
        if user["role"] != "creator":  # audit trail is for managers, reviewers and admins
            audit_rows = [dict(r) for r in c.execute(
                "SELECT a.*, u.name AS who FROM audit a LEFT JOIN users u ON u.id=a.user_id "
                "WHERE a.content_id=? ORDER BY a.id DESC", (cid,))]
        return dict(
            content={**content, "author": author}, body=v["body"], images=v["images"],
            review_meta=v["review_meta"], findings=findings, history=history, claims=claims,
            comments=comments, versions=versions, audit=audit_rows,
            permissions=wf.permissions(c, user, content),
        )

    @app.get("/api/content/<int:cid>")
    def content_detail(cid: int):
        return jsonify(detail_payload(me(), conn(), cid))

    @app.get("/api/content/<int:cid>/record")
    def content_record(cid: int):
        """A printable record: the text, every finding with its source and decision, who approved, and when."""
        user = me()
        return Response(record.render(detail_payload(user, conn(), cid), user["name"]),
                        mimetype="text/html; charset=utf-8")

    @app.post("/api/content/<int:cid>/revise")
    def content_revise(cid: int):
        data = payload()
        ver = wf.revise(conn(), me(), cid, data.get("body"), data.get("images"), judge_factory, ai_mode(data))
        return jsonify(version=ver)

    @app.post("/api/content/<int:cid>/review")
    def content_rereview(cid: int):
        user = me()
        content = wf.get_content(conn(), user, cid)
        if not wf.permissions(conn(), user, content)["can_rerun"]:
            raise Forbidden("You cannot re-run the review on this content")
        if content["status"] == "approved":
            raise Forbidden("Approved content is locked")
        return jsonify(wf.run_review(conn(), cid, judge_factory, ai_mode(request.get_json(silent=True) or {})))

    @app.post("/api/findings/<int:fid>/decide")
    def finding_decide(fid: int):
        data = payload()
        out = wf.decide(conn(), me(), fid, data.get("action"), data.get("text"), data.get("reason"), judge_factory)
        return jsonify(out)

    @app.post("/api/content/<int:cid>/comments")
    def content_comment(cid: int):
        data = payload()
        wf.comment(conn(), me(), cid, data.get("body"), data.get("finding_id"))
        return jsonify(ok=True), 201

    @app.post("/api/content/<int:cid>/submit")
    def content_submit(cid: int):
        wf.submit(conn(), me(), cid)
        return jsonify(ok=True)

    @app.post("/api/content/<int:cid>/approve")
    def content_approve(cid: int):
        wf.approve(conn(), me(), cid)
        return jsonify(ok=True)

    @app.post("/api/content/<int:cid>/request-changes")
    def content_request_changes(cid: int):
        wf.request_changes(conn(), me(), cid, payload().get("note"))
        return jsonify(ok=True)

    @app.get("/api/insights")
    def insights_view():
        user = me()
        if user["role"] not in ("admin", "manager", "reviewer") or user["is_external"]:
            raise Forbidden("Insights are for your own managers, reviewers and admins")
        return jsonify(insights.compute(conn()))

    @app.get("/api/llm-log")
    def llm_log():
        """Record of what was sent to the AI service. Managers and reviewers see the metadata; the full text of a
        request (only kept when BRANDGUARD_AI_LOG=full) is for admins."""
        user = me()
        if user["role"] not in ("admin", "manager", "reviewer") or user["is_external"]:
            raise Forbidden("Not allowed")
        rows = [dict(r) for r in conn().execute(
            "SELECT id, content_id, version, model, content_sha256, chars, rules, status, payload, created_at "
            "FROM llm_log ORDER BY id DESC LIMIT 50")]
        for r in rows:
            r["rules"] = json.loads(r["rules"] or "[]")
            r["has_payload"] = bool(r["payload"])
            if user["role"] != "admin":
                del r["payload"]
        return jsonify(rows)

    return app
