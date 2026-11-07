"""Flask app: JSON API plus the single-page review UI."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session

from . import db as dbm
from . import kb as kbm
from . import llm
from . import workflow as wf

ROOT = Path(__file__).resolve().parent.parent
LEVELS = kbm.ACCESS_LEVELS


class AuthError(Exception):
    pass


def create_app(db_path: str | None = None, llm_call=None) -> Flask:
    """llm_call(system, user, model) -> str lets tests (or a private model) replace the AI backend."""
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config["SECRET_KEY"] = os.environ.get("BRANDGUARD_SECRET") or secrets.token_hex(16)
    app.config["DB_PATH"] = db_path or os.environ.get("BRANDGUARD_DB", str(ROOT / "brandguard.db"))
    app.config["LLM_CALL"] = llm_call
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB uploads

    with dbm.connect(app.config["DB_PATH"]) as boot:
        dbm.init(boot)

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
        if not row:
            raise AuthError("Pick a user first")
        return dict(row)

    def judge_factory(c, content_id, version):
        return llm.make_judge(c, content_id, version, call=app.config["LLM_CALL"])

    @app.errorhandler(AuthError)
    def _auth(e):
        return jsonify(error=str(e)), 401

    @app.errorhandler(PermissionError)
    def _perm(e):
        return jsonify(error=str(e)), 403

    @app.errorhandler(LookupError)
    def _missing(e):
        return jsonify(error=str(e.args[0]) if e.args else "Not found"), 404

    @app.errorhandler(ValueError)
    def _bad(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def _integrity(e):
        return jsonify(error=f"Could not save: {e}"), 400

    # -------------------------------------------------------------------- pages
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # --------------------------------------------------------------------- auth
    @app.get("/api/users")
    def users():
        rows = conn().execute("SELECT id, name, role, is_external FROM users ORDER BY id")
        return jsonify([dict(r) for r in rows])

    @app.post("/api/login")
    def login():
        uid = (request.get_json(silent=True) or {}).get("user_id")
        row = conn().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise LookupError("No such user")
        session["uid"] = row["id"]
        return jsonify(dict(row))

    @app.get("/api/me")
    def whoami():
        return jsonify(me())

    # ----------------------------------------------------------- knowledge base
    @app.get("/api/kb")
    def kb_browse():
        user = me()
        level = wf.clearance(user)
        if level < 0:
            raise PermissionError("External users cannot browse confidential brand material")
        c = conn()
        guidelines = []
        for gl in c.execute("SELECT * FROM guidelines ORDER BY id"):
            if LEVELS[gl["access_level"]] > level:
                continue
            rules = [dict(r) for r in c.execute(
                "SELECT code, title, text FROM rules WHERE guideline_id=? ORDER BY id", (gl["id"],))]
            guidelines.append({**dict(gl), "rules": rules})
        facts = [dict(r) for r in c.execute("SELECT code, kind, statement, source, access_level FROM facts ORDER BY id")
                 if LEVELS[r["access_level"]] <= level]
        assets = [dict(r) for r in c.execute("SELECT name, kind, note, access_level FROM assets ORDER BY id")
                  if LEVELS[r["access_level"]] <= level]
        glossary = [dict(r) for r in c.execute("SELECT term, preferred, kind, rule_code, note FROM glossary ORDER BY id")]
        return jsonify(guidelines=guidelines, facts=facts, glossary=glossary, assets=assets)

    @app.post("/api/kb/seed")
    def kb_seed():
        if me()["role"] != "admin":
            raise PermissionError("Only an admin can load the knowledge base")
        out = kbm.seed_demo(conn(), ROOT / "seed")
        wf.audit(conn(), None, me()["id"], "kb_seeded", json.dumps(out))
        conn().commit()
        return jsonify(out)

    @app.post("/api/kb/import")
    def kb_import():
        user = me()
        if user["role"] != "admin":
            raise PermissionError("Only an admin can import knowledge-base material")
        kind = request.form.get("kind", "")
        upload = request.files.get("file")
        text = request.form.get("text", "")
        raw_name = upload.filename if upload else "pasted.txt"
        if upload:
            data = upload.read()
            text = kbm.extract_text(raw_name, data) if kind == "guidelines" else data.decode("utf-8", "replace")
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
            except json.JSONDecodeError as exc:
                raise ValueError(f"{kind} must be valid JSON: {exc}") from exc
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
    def finding_dict(r) -> dict:
        d = dict(r)
        d["ai_generated"] = bool(d["ai_generated"])
        d["needs_reviewer"] = bool(d["needs_reviewer"])
        return d

    @app.get("/api/content")
    def content_list():
        return jsonify(wf.list_content(conn(), me()))

    @app.post("/api/content")
    def content_create():
        user, data = me(), request.get_json(silent=True) or {}
        cid = wf.create_content(conn(), user, data.get("title"), data.get("body"), data.get("images"), judge_factory)
        return jsonify(id=cid), 201

    @app.get("/api/content/<int:cid>")
    def content_detail(cid: int):
        user, c = me(), conn()
        content = wf.get_content(c, user, cid)
        v = wf.current(c, content)
        findings = [finding_dict(r) for r in c.execute(
            "SELECT f.*, u.name AS decided_by_name FROM findings f LEFT JOIN users u ON u.id=f.decided_by "
            "WHERE f.content_id=? AND f.version=? ORDER BY CASE WHEN f.span_start<0 THEN 1 ELSE 0 END, f.span_start, f.id",
            (cid, content["current_version"]))]
        history = [finding_dict(r) for r in c.execute(
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
        audit_rows = []
        if user["role"] != "creator":  # audit trail is for managers, reviewers and admins
            audit_rows = [dict(r) for r in c.execute(
                "SELECT a.*, u.name AS who FROM audit a LEFT JOIN users u ON u.id=a.user_id "
                "WHERE a.content_id=? ORDER BY a.id DESC", (cid,))]
        return jsonify(
            content={**content, "author": author}, body=v["body"], images=v["images"],
            review_meta=v["review_meta"], findings=findings, history=history, claims=claims,
            comments=comments, versions=versions, audit=audit_rows,
            permissions=wf.permissions(c, user, content),
        )

    @app.post("/api/content/<int:cid>/revise")
    def content_revise(cid: int):
        data = request.get_json(silent=True) or {}
        ver = wf.revise(conn(), me(), cid, data.get("body"), data.get("images"), judge_factory)
        return jsonify(version=ver)

    @app.post("/api/content/<int:cid>/review")
    def content_rereview(cid: int):
        user = me()
        content = wf.get_content(conn(), user, cid)
        if not wf.permissions(conn(), user, content)["can_rerun"]:
            raise PermissionError("You cannot re-run the review on this content")
        if content["status"] == "approved":
            raise PermissionError("Approved content is locked")
        return jsonify(wf.run_review(conn(), cid, judge_factory))

    @app.post("/api/findings/<int:fid>/decide")
    def finding_decide(fid: int):
        data = request.get_json(silent=True) or {}
        out = wf.decide(conn(), me(), fid, data.get("action"), data.get("text"), data.get("reason"), judge_factory)
        return jsonify(out)

    @app.post("/api/content/<int:cid>/comments")
    def content_comment(cid: int):
        data = request.get_json(silent=True) or {}
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
        wf.request_changes(conn(), me(), cid, (request.get_json(silent=True) or {}).get("note"))
        return jsonify(ok=True)

    @app.get("/api/llm-log")
    def llm_log():
        if me()["role"] not in ("admin", "manager", "reviewer"):
            raise PermissionError("Not allowed")
        rows = conn().execute("SELECT id, content_id, version, model, payload, created_at FROM llm_log ORDER BY id DESC LIMIT 50")
        return jsonify([dict(r) for r in rows])

    return app
