"""Review and approval workflow: roles, decisions, versions, comments, audit.

Human-control rules enforced here (not just in the UI):
  * Nothing is applied without a person clicking accept or edit.
  * Dismissals need a written reason.
  * Dismissing a fact or claim finding needs a manager or reviewer.
  * Approval needs every finding decided, a manager or reviewer (not the author),
    and a reviewer specifically if any fact, claim or low-confidence finding was dismissed.
  * The AI judge sees content only when it is created, edited by its author or explicitly
    re-run. Applying a fix never re-sends the content; earlier AI suggestions are carried over.
  * Two people deciding at once cannot both win: writes are guarded and the loser is told.
  * Approved content is locked.
  * Every action is written to the audit log.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from . import engine
from .db import now
from .errors import Forbidden, NotFound
from .kb import ACCESS_LEVELS
from .models import Finding

APPROVER_ROLES = {"manager", "reviewer"}
RISKY = {"fact", "claim"}

MAX_TITLE, MAX_BODY, MAX_IMAGES, MAX_FIELD, MAX_COMMENT = 200, 50_000, 20, 500, 2000
_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _text(value, label: str, limit: int, required: bool = False) -> str:
    """Validate user text: must be a string, within the limit, and non-blank when required."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = value.replace("\r\n", "\n")
    if required and not value.strip():
        raise ValueError(f"{label} is required")
    if len(value) > limit:
        raise ValueError(f"{label} is too long (maximum {limit:,} characters)")
    return value


def _colour(value, label: str) -> str:
    v = _text(value, label, 20).strip()
    if not v:
        return ""
    m = _HEX.match(v)
    if not m:
        raise ValueError(f"{label} must look like #RRGGBB")
    h = m.group(1)
    h = "".join(ch * 2 for ch in h) if len(h) == 3 else h
    return "#" + h.upper()


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
        raise NotFound("Content not found")
    c = dict(row)
    # Creators and agencies only see their own work; manager, reviewer and admin see all.
    if user["role"] == "creator" and c["author_id"] != user["id"]:
        raise Forbidden("You can only see your own content")
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
        "can_rerun": (is_author and editable) or (user["role"] in (APPROVER_ROLES | {"admin"})),
    }


# ---------------------------------------------------------------------- review
def run_review(conn, content_id: int, judge_factory: Optional[Callable] = None, ai: str = "fresh") -> dict:
    """(Re)review the current version. Dismissals made earlier on the same issue carry over.

    ai="fresh": ask the AI judge (it sees the content).  ai="inherit": do NOT contact the AI;
    suggestions it made on the previous version are re-located in the new text and kept."""
    c = dict(conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone())
    v = current(conn, c)
    ver = c["current_version"]
    previous = [dict(r) for r in conn.execute(
        "SELECT * FROM findings WHERE content_id=? AND decision='dismissed'", (content_id,))]
    carry = {(p["source_id"], p["span_text"], p["category"]): p for p in previous}

    inherited: list[Finding] = []
    if ai == "inherit" and ver > 1:
        for r in conn.execute(
                "SELECT * FROM findings WHERE content_id=? AND version=? AND ai_generated=1 "
                "AND target='body' AND decision IN ('open','dismissed')", (content_id, ver - 1)):
            start = v["body"].find(r["span_text"]) if r["span_text"] else -1
            if start < 0:
                continue  # the flagged text is gone, so the suggestion no longer applies
            try:
                inherited.append(Finding(
                    category=r["category"], issue=r["issue"], span_text=r["span_text"], span_start=start,
                    span_end=start + len(r["span_text"]), target="body", source_type=r["source_type"],
                    source_id=r["source_id"], source_quote=r["source_quote"], severity=r["severity"],
                    confidence=r["confidence"], suggested_fix=r["suggested_fix"], fix_note=r["fix_note"],
                    ai_generated=True))
            except Exception:
                continue
    judge = judge_factory(conn, content_id, ver) if (judge_factory and ai == "fresh") else None
    result = engine.review(engine.load_kb(conn), v["body"], v["images"], judge=judge, inherited=inherited)
    if ai == "inherit" and not inherited:
        previous = json.loads(version_row(conn, content_id, ver - 1)["review_meta"]).get("llm_status", "") if ver > 1 else ""
        result.llm_status = ("not re-run for this change (content was not re-sent)"
                             if previous.startswith(("used", "not re-run")) else "not used")

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
    title = _text(title, "Title", MAX_TITLE, required=True).strip()
    body = _text(body, "Content text", MAX_BODY, required=True)
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
    if images is None:
        return []
    if not isinstance(images, list):
        raise ValueError("Images must be a list")
    if len(images) > MAX_IMAGES:
        raise ValueError(f"At most {MAX_IMAGES} images per item")
    out, seen = [], set()
    for img in images:
        if not isinstance(img, dict):
            raise ValueError("Each image must be an object")
        name = _text(img.get("name"), "Image name", 200).strip()
        if not name:
            continue
        if name in seen:
            raise ValueError(f"Image name '{name}' is used twice; names must be unique")
        seen.add(name)
        out.append({
            "name": name,
            "alt": _text(img.get("alt"), "Alt text", MAX_FIELD).strip(),
            "text_color": _colour(img.get("text_color"), "Text colour"),
            "bg_color": _colour(img.get("bg_color"), "Background colour"),
        })
    return out


def _new_version(conn, c: dict, user_id: int, body: str, images: list[dict], note: str,
                 judge_factory: Optional[Callable], ai: str = "fresh") -> int:
    ver = c["current_version"] + 1
    # Guarded: succeeds only if nobody else created a version since this request read the content.
    moved = conn.execute("UPDATE content SET current_version=? WHERE id=? AND current_version=?",
                         (ver, c["id"], c["current_version"])).rowcount
    if not moved:
        raise ValueError("Someone else changed this content a moment ago. Reload and try again.")
    conn.execute(
        "INSERT INTO versions(content_id, version, body, images, created_by, note, created_at) VALUES (?,?,?,?,?,?,?)",
        (c["id"], ver, body, json.dumps(images), user_id, note, now()))
    audit(conn, c["id"], user_id, "version_created", f"v{ver}: {note}")
    conn.commit()
    c["current_version"] = ver
    run_review(conn, c["id"], judge_factory, ai)
    return ver


def revise(conn, user: dict, content_id: int, body: str, images: list[dict],
           judge_factory: Optional[Callable] = None) -> int:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_revise"]:
        raise Forbidden("Only the author can edit, and only while the content is a draft or has changes requested")
    body = _text(body, "Content text", MAX_BODY, required=True)
    return _new_version(conn, c, user["id"], body, _clean_images(images), "Edited by author", judge_factory)


# -------------------------------------------------------------------- decisions
def decide(conn, user: dict, finding_id: int, action: str, text: Optional[str] = None,
           reason: Optional[str] = None, judge_factory: Optional[Callable] = None) -> dict:
    row = conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
    if not row:
        raise NotFound("Finding not found")
    f = dict(row)
    c = get_content(conn, user, f["content_id"])
    perms = permissions(conn, user, c)
    if c["status"] == "approved":
        raise Forbidden("Approved content is locked")
    if not perms["can_decide"]:
        raise Forbidden("You cannot make decisions on this content right now")
    if f["version"] != c["current_version"]:
        raise ValueError("This finding belongs to an older version")
    if f["decision"] != "open":
        raise ValueError("This finding already has a decision")
    if action not in ("accept", "edit", "dismiss"):
        raise ValueError("action must be accept, edit or dismiss")

    if action == "dismiss":
        reason = _text(reason, "Reason", MAX_FIELD).strip()
        if not reason:
            raise ValueError("A reason is required to dismiss a finding")
        if (f["category"] in RISKY or f["needs_reviewer"]) and not perms["can_dismiss_risky"]:
            raise Forbidden("Only a manager or reviewer can dismiss fact, claim or low-confidence findings")
        if not conn.execute(
                "UPDATE findings SET decision='dismissed', decision_reason=?, decided_by=?, decided_at=? "
                "WHERE id=? AND decision='open'", (reason, user["id"], now(), finding_id)).rowcount:
            raise ValueError("Someone else already decided this finding")
        audit(conn, c["id"], user["id"], "finding_dismissed", f"#{finding_id} {f['source_id']}: {reason}")
        conn.commit()
        return {"decision": "dismissed", "new_version": None}

    if action == "accept":
        replacement = f["suggested_fix"]
        if not replacement:
            raise ValueError("This finding has no suggested fix. Use edit to write one, or dismiss it.")
    else:
        if text is None:
            raise ValueError("Provide the replacement text")
        replacement = _text(text, "Replacement", 2000)
    v = current(conn, c)
    body, images = v["body"], [dict(i) for i in v["images"]]
    if f["target"] == "body":
        s, e = f["span_start"], f["span_end"]
        if body[s:e] != f["span_text"]:
            raise ValueError("The content changed since this review. Re-run the review first.")
        body = body[:s] + replacement + body[e:]
        if not body.strip():
            raise ValueError("That change would leave the content empty")
    else:
        field, name = f["target"].split(":", 1)
        img = next((i for i in images if i["name"] == name), None)
        if not img:
            raise ValueError("Image no longer exists in this version")
        if field == "image.alt":
            replacement = replacement.strip()
            img["alt"] = replacement
        else:
            replacement = _colour(replacement, "Colour")
            img["text_color"] = replacement
        if not replacement:
            raise ValueError("Provide the replacement text")
    verb = "accepted" if action == "accept" else "edited"
    if not conn.execute(
            "UPDATE findings SET decision=?, decision_text=?, decided_by=?, decided_at=? "
            "WHERE id=? AND decision='open'", (verb, replacement, user["id"], now(), finding_id)).rowcount:
        raise ValueError("Someone else already decided this finding")
    audit(conn, c["id"], user["id"], f"finding_{verb}",
          f"#{finding_id} {f['source_id']}: {f['span_text']!r} -> {replacement!r}")
    ver = _new_version(conn, c, user["id"], body, images,
                       f"{verb.capitalize()} fix for {f['source_id']} ({f['span_text']})",
                       judge_factory, ai="inherit")  # applying a fix never re-sends content to the AI
    return {"decision": verb, "new_version": ver}


# --------------------------------------------------------------- collaboration
def comment(conn, user: dict, content_id: int, body: str, finding_id: Optional[int] = None) -> None:
    c = get_content(conn, user, content_id)
    body = _text(body, "Comment", MAX_COMMENT).strip()
    if not body:
        raise ValueError("Comment is empty")
    conn.execute("INSERT INTO comments(content_id, finding_id, user_id, body, created_at) VALUES (?,?,?,?,?)",
                 (c["id"], finding_id, user["id"], body, now()))
    audit(conn, c["id"], user["id"], "comment", body[:120])
    conn.commit()


def submit(conn, user: dict, content_id: int) -> None:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_submit"]:
        raise Forbidden("Only the author can submit, and only a draft or content with changes requested")
    conn.execute("UPDATE content SET status='in_review' WHERE id=?", (c["id"],))
    audit(conn, c["id"], user["id"], "submitted", f"v{c['current_version']} with {len(open_findings(conn, c))} open findings")
    conn.commit()


def approve(conn, user: dict, content_id: int) -> None:
    c = get_content(conn, user, content_id)
    if user["role"] not in APPROVER_ROLES:
        raise Forbidden("Only a manager or reviewer can approve")
    if c["author_id"] == user["id"]:
        raise Forbidden("You cannot approve your own content")
    if c["status"] != "in_review":
        raise ValueError("Only content that is in review can be approved")
    if open_findings(conn, c):
        raise ValueError("Every finding needs a decision before approval")
    cur = conn.execute("SELECT * FROM findings WHERE content_id=? AND version=?", (c["id"], c["current_version"]))
    needs_reviewer = any(
        (r["category"] in RISKY and r["decision"] == "dismissed") or (r["needs_reviewer"] and r["decision"] == "dismissed")
        for r in cur)
    if needs_reviewer and user["role"] != "reviewer":
        raise Forbidden("A reviewer must approve because a claim or low-confidence finding was dismissed")
    conn.execute("UPDATE content SET status='approved' WHERE id=?", (c["id"],))
    audit(conn, c["id"], user["id"], "approved", f"v{c['current_version']}")
    conn.commit()


def request_changes(conn, user: dict, content_id: int, note: str) -> None:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_request_changes"]:
        raise Forbidden("Only a manager or reviewer can request changes on content in review")
    note = _text(note, "Note", MAX_FIELD)
    if not note.strip():
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
