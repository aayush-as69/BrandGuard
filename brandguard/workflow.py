"""Review and approval workflow: roles, decisions, versions, comments, audit.

Human-control rules enforced here (not just in the UI):
  * Nothing is applied without a person clicking accept or edit.
  * Dismissals need a written reason.
  * Dismissing a fact or claim finding needs a manager or reviewer.
  * Approval needs every finding decided, a manager or reviewer (not the author),
    and a reviewer specifically if any claim was dismissed or any finding is low confidence.
  * Approved content is locked.
  * Every action is written to the audit log.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Callable, Optional

from . import engine, llm
from .db import now
from .kb import ACCESS_LEVELS

APPROVER_ROLES = {"manager", "reviewer"}
RISKY = {"fact", "claim"}


# ---------------------------------------------------------------------- helpers
def audit(conn, content_id: Optional[int], user_id: Optional[int], action: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit(content_id, user_id, action, detail, created_at) VALUES (?,?,?,?,?)",
        (content_id, user_id, action, detail, now()),
    )


def clearance(user: dict) -> int:
    """How much of the knowledge base this user may browse."""
    if user["is_external"]:
        return -1  # no browsing at all
    return ACCESS_LEVELS["internal"] if user["role"] == "creator" else ACCESS_LEVELS["confidential"]


def get_content(conn, user: dict, content_id: int) -> dict:
    row = conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone()
    if not row:
        raise LookupError("Content not found")
    c = dict(row)
    # Creators and agencies only see their own work; manager, reviewer and admin see all.
    if user["role"] == "creator" and c["author_id"] != user["id"]:
        raise PermissionError("You can only see your own content")
    return c


def version_row(conn, content_id: int, version: int) -> dict:
    return dict(conn.execute(
        "SELECT * FROM versions WHERE content_id=? AND version=?", (content_id, version)).fetchone())


def current(conn, c: dict) -> dict:
    v = version_row(conn, c["id"], c["current_version"])
    v["images"] = json.loads(v["images"])
    v["review_meta"] = json.loads(v["review_meta"])
    return v


def open_findings(conn, c: dict) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM findings WHERE content_id=? AND version=? AND decision='open'",
        (c["id"], c["current_version"]))]


def permissions(conn, user: dict, c: dict) -> dict:
    is_author = c["author_id"] == user["id"]
    approver = user["role"] in APPROVER_ROLES
    editable = c["status"] in ("draft", "changes_requested")
    return {
        "can_revise": is_author and editable,
        "can_decide": (is_author and editable) or (approver and c["status"] in ("in_review", "draft", "changes_requested")),
        "can_dismiss_risky": approver,
        "can_submit": is_author and editable,
        "can_approve": approver and not is_author and c["status"] == "in_review",
        "can_request_changes": approver and not is_author and c["status"] == "in_review",
        "can_comment": True,
        "can_rerun": (is_author and editable) or user["role"] in APPROVER_ROLES | {"admin"},
    }


# ---------------------------------------------------------------------- review
def run_review(conn, content_id: int, judge_factory: Optional[Callable] = None) -> dict:
    """(Re)review the current version. Dismissals made earlier on the same issue carry over."""
    c = dict(conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone())
    v = current(conn, c)
    ver = c["current_version"]
    previous = [dict(r) for r in conn.execute(
        "SELECT * FROM findings WHERE content_id=? AND decision='dismissed'", (content_id,))]
    carry = {(p["source_id"], p["span_text"], p["category"]): p for p in previous}

    judge = judge_factory(conn, content_id, ver) if judge_factory else None
    result = engine.review(engine.load_kb(conn), v["body"], v["images"], judge=judge)

    conn.execute("DELETE FROM findings WHERE content_id=? AND version=?", (content_id, ver))
    conn.execute("DELETE FROM claims WHERE content_id=? AND version=?", (content_id, ver))
    carried = 0
    for f in result.findings:
        old = carry.get((f.source_id, f.span_text, f.category))
        decision = ("dismissed", f"(carried over) {old['decision_reason']}", old["decided_by"], old["decided_at"]) \
            if old else ("open", "", None, None)
        carried += 1 if old else 0
        conn.execute(
            """INSERT INTO findings(content_id, version, category, issue, span_text, span_start, span_end, target,
                 source_type, source_id, source_quote, severity, confidence, suggested_fix, fix_note,
                 ai_generated, needs_reviewer, decision, decision_reason, decided_by, decided_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (content_id, ver, f.category, f.issue, f.span_text, f.span_start, f.span_end, f.target,
             f.source_type, f.source_id, f.source_quote, f.severity, f.confidence, f.suggested_fix, f.fix_note,
             int(f.ai_generated), int(f.needs_reviewer), *decision),
        )
    for cl in result.claims:
        conn.execute(
            "INSERT INTO claims(content_id, version, text, status, source_id) VALUES (?,?,?,?,?)",
            (content_id, ver, cl["text"], cl["status"], cl["source_id"]),
        )
    meta = {"warnings": result.warnings, "rejected": result.rejected, "llm_status": result.llm_status}
    conn.execute("UPDATE versions SET review_meta=? WHERE content_id=? AND version=?",
                 (json.dumps(meta), content_id, ver))
    audit(conn, content_id, None, "review_run",
          f"v{ver}: {len(result.findings)} findings, {carried} carried over; AI judge: {result.llm_status}")
    conn.commit()
    return {"findings": len(result.findings), "carried_over": carried, **meta}


# --------------------------------------------------------------------- content
def create_content(conn, user: dict, title: str, body: str, images: list[dict],
                   judge_factory: Optional[Callable] = None) -> int:
    title, body = (title or "").strip(), body or ""
    if not title:
        raise ValueError("Title is required")
    if not body.strip():
        raise ValueError("Content text is required")
    images = _clean_images(images)
    cur = conn.execute(
        "INSERT INTO content(title, author_id, created_at) VALUES (?,?,?)", (title, user["id"], now()))
    cid = cur.lastrowid
    conn.execute(
        "INSERT INTO versions(content_id, version, body, images, created_by, note, created_at) VALUES (?,?,?,?,?,?,?)",
        (cid, 1, body, json.dumps(images), user["id"], "Created", now()))
    audit(conn, cid, user["id"], "content_created", title)
    conn.commit()
    run_review(conn, cid, judge_factory)
    return cid


def _clean_images(images) -> list[dict]:
    out = []
    for img in images or []:
        name = str(img.get("name", "")).strip()
        if not name:
            continue
        out.append({
            "name": name,
            "alt": str(img.get("alt", "") or "").strip(),
            "text_color": str(img.get("text_color", "") or "").strip(),
            "bg_color": str(img.get("bg_color", "") or "").strip(),
        })
    return out


def _new_version(conn, c: dict, user_id: int, body: str, images: list[dict], note: str,
                 judge_factory: Optional[Callable]) -> int:
    ver = c["current_version"] + 1
    conn.execute(
        "INSERT INTO versions(content_id, version, body, images, created_by, note, created_at) VALUES (?,?,?,?,?,?,?)",
        (c["id"], ver, body, json.dumps(images), user_id, note, now()))
    conn.execute("UPDATE content SET current_version=? WHERE id=?", (ver, c["id"]))
    audit(conn, c["id"], user_id, "version_created", f"v{ver}: {note}")
    conn.commit()
    c["current_version"] = ver
    run_review(conn, c["id"], judge_factory)
    return ver


def revise(conn, user: dict, content_id: int, body: str, images: list[dict],
           judge_factory: Optional[Callable] = None) -> int:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_revise"]:
        raise PermissionError("Only the author can edit, and only while the content is a draft or has changes requested")
    if not (body or "").strip():
        raise ValueError("Content text is required")
    return _new_version(conn, c, user["id"], body, _clean_images(images), "Edited by author", judge_factory)


# -------------------------------------------------------------------- decisions
def decide(conn, user: dict, finding_id: int, action: str, text: Optional[str] = None,
           reason: Optional[str] = None, judge_factory: Optional[Callable] = None) -> dict:
    f = conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
    if not f:
        raise LookupError("Finding not found")
    f = dict(f)
    c = get_content(conn, user, f["content_id"])
    perms = permissions(conn, user, c)
    if c["status"] == "approved":
        raise PermissionError("Approved content is locked")
    if not perms["can_decide"]:
        raise PermissionError("You cannot make decisions on this content right now")
    if f["version"] != c["current_version"]:
        raise ValueError("This finding belongs to an older version")
    if f["decision"] != "open":
        raise ValueError("This finding already has a decision")
    if action not in ("accept", "edit", "dismiss"):
        raise ValueError("action must be accept, edit or dismiss")

    if action == "dismiss":
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("A reason is required to dismiss a finding")
        if (f["category"] in RISKY or f["needs_reviewer"]) and not perms["can_dismiss_risky"]:
            raise PermissionError("Only a manager or reviewer can dismiss fact, claim or low-confidence findings")
        conn.execute(
            "UPDATE findings SET decision='dismissed', decision_reason=?, decided_by=?, decided_at=? WHERE id=?",
            (reason, user["id"], now(), finding_id))
        audit(conn, c["id"], user["id"], "finding_dismissed", f"#{finding_id} {f['source_id']}: {reason}")
        conn.commit()
        return {"decision": "dismissed", "new_version": None}

    replacement = f["suggested_fix"] if action == "accept" else text
    if action == "accept" and not replacement:
        raise ValueError("This finding has no suggested fix. Use edit to write one, or dismiss it.")
    if action == "edit" and (replacement is None or (replacement == "" and f["target"] != "body")):
        raise ValueError("Provide the replacement text")
    if f["category"] in RISKY and action == "edit" and f["ai_generated"]:
        pass  # allowed: a person is rewriting it
    v = current(conn, c)
    body, images = v["body"], [dict(i) for i in v["images"]]
    if f["target"] == "body":
        s, e = f["span_start"], f["span_end"]
        if body[s:e] != f["span_text"]:
            raise ValueError("The content changed since this review. Re-run the review first.")
        body = body[:s] + replacement + body[e:]
    else:
        field, name = f["target"].split(":", 1)
        img = next((i for i in images if i["name"] == name), None)
        if not img:
            raise ValueError("Image no longer exists in this version")
        img["alt" if field == "image.alt" else "text_color"] = replacement
    conn.execute(
        "UPDATE findings SET decision=?, decision_text=?, decided_by=?, decided_at=? WHERE id=?",
        ("accepted" if action == "accept" else "edited", replacement, user["id"], now(), finding_id))
    audit(conn, c["id"], user["id"], f"finding_{'accepted' if action == 'accept' else 'edited'}",
          f"#{finding_id} {f['source_id']}: {f['span_text']!r} -> {replacement!r}")
    ver = _new_version(conn, c, user["id"], body, images,
                       f"{'Accepted' if action == 'accept' else 'Edited'} fix for {f['source_id']} ({f['span_text']})",
                       judge_factory)
    return {"decision": "accepted" if action == "accept" else "edited", "new_version": ver}


# --------------------------------------------------------------- collaboration
def comment(conn, user: dict, content_id: int, body: str, finding_id: Optional[int] = None) -> None:
    c = get_content(conn, user, content_id)
    body = (body or "").strip()
    if not body:
        raise ValueError("Comment is empty")
    conn.execute("INSERT INTO comments(content_id, finding_id, user_id, body, created_at) VALUES (?,?,?,?,?)",
                 (c["id"], finding_id, user["id"], body, now()))
    audit(conn, c["id"], user["id"], "comment", body[:120])
    conn.commit()


def submit(conn, user: dict, content_id: int) -> None:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_submit"]:
        raise PermissionError("Only the author can submit, and only a draft or content with changes requested")
    conn.execute("UPDATE content SET status='in_review' WHERE id=?", (c["id"],))
    audit(conn, c["id"], user["id"], "submitted", f"v{c['current_version']} with {len(open_findings(conn, c))} open findings")
    conn.commit()


def approve(conn, user: dict, content_id: int) -> None:
    c = get_content(conn, user, content_id)
    if user["role"] not in APPROVER_ROLES:
        raise PermissionError("Only a manager or reviewer can approve")
    if c["author_id"] == user["id"]:
        raise PermissionError("You cannot approve your own content")
    if c["status"] != "in_review":
        raise ValueError("Only content that is in review can be approved")
    if open_findings(conn, c):
        raise ValueError("Every finding needs a decision before approval")
    cur = conn.execute("SELECT * FROM findings WHERE content_id=? AND version=?", (c["id"], c["current_version"]))
    needs_reviewer = any(
        (r["category"] in RISKY and r["decision"] == "dismissed") or (r["needs_reviewer"] and r["decision"] == "dismissed")
        for r in cur)
    if needs_reviewer and user["role"] != "reviewer":
        raise PermissionError("A reviewer must approve because a claim or low-confidence finding was dismissed")
    conn.execute("UPDATE content SET status='approved' WHERE id=?", (c["id"],))
    audit(conn, c["id"], user["id"], "approved", f"v{c['current_version']}")
    conn.commit()


def request_changes(conn, user: dict, content_id: int, note: str) -> None:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_request_changes"]:
        raise PermissionError("Only a manager or reviewer can request changes on content in review")
    if not (note or "").strip():
        raise ValueError("Say what needs to change")
    conn.execute("UPDATE content SET status='changes_requested' WHERE id=?", (c["id"],))
    conn.execute("INSERT INTO comments(content_id, finding_id, user_id, body, created_at) VALUES (?,?,?,?,?)",
                 (c["id"], None, user["id"], f"Changes requested: {note.strip()}", now()))
    audit(conn, c["id"], user["id"], "changes_requested", note.strip()[:120])
    conn.commit()


def list_content(conn, user: dict) -> list[dict]:
    where, args = ("", ())
    if user["role"] == "creator":
        where, args = ("WHERE c.author_id=?", (user["id"],))
    rows = conn.execute(
        f"""SELECT c.*, u.name AS author,
              (SELECT COUNT(*) FROM findings f WHERE f.content_id=c.id AND f.version=c.current_version
                  AND f.decision='open') AS open_findings,
              (SELECT COUNT(*) FROM findings f WHERE f.content_id=c.id AND f.version=c.current_version) AS total_findings
            FROM content c JOIN users u ON u.id=c.author_id {where} ORDER BY c.id DESC""", args)
    return [dict(r) for r in rows]
