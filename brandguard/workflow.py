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

import datetime as dt
import json
import types
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
CONTEXT = 40  # text either side (within the sentence) that must match for a dismissal to carry to the same spot
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


def source_key(source_type: str, source_id: str) -> str:
    return f"{'fact' if source_type == 'fact' else 'rule'}:{source_id}"


def visible_sources(conn, user: dict) -> set[str]:
    """The approved facts and guideline rules this person may see, as "fact:F-01" / "rule:G-01" keys.
    Agency users see public material only; internal creators public and internal; others everything.
    A source that no longer exists is not visible to anyone, which is the safe default."""
    level = 0 if user["is_external"] else clearance(user)
    seen = {source_key("fact", r["code"]) for r in conn.execute("SELECT code, access_level FROM facts")
            if ACCESS_LEVELS[r["access_level"]] <= level}
    seen |= {source_key("guideline", r["code"]) for r in conn.execute(
        "SELECT r.code, g.access_level FROM rules r JOIN guidelines g ON g.id = r.guideline_id")
        if ACCESS_LEVELS[r["access_level"]] <= level}
    return seen


def is_restricted(f: dict, visible: set[str]) -> bool:
    return source_key(f.get("source_type", ""), f.get("source_id", "")) not in visible


def redact(f: dict) -> dict:
    """What a person without clearance sees of a finding that rests on a restricted fact or guideline: that
    something conflicts, and where, but not the source, the approved value or a fix that would reveal it."""
    what = "approved fact" if f.get("source_type") == "fact" else "guideline"
    f = dict(f)
    f.update(
        restricted=True,
        issue=f"This conflicts with an {what} that only the brand team can see.",
        source_quote=f"Restricted: this {what} is not visible to your account.",
        suggested_fix=None, decision_text=None,
        fix_note="Ask the brand team for the approved wording, or rewrite this part yourself.",
    )
    return f


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
class _Dismissals:
    """Remembers earlier dismissals so a person's decision survives a re-review. A dismissal is matched by
    rule, flagged text, category and the words around it within the same sentence, so it covers that spot
    and not every identical word elsewhere."""

    def __init__(self, conn, content_id: int) -> None:
        self.conn, self.content_id = conn, content_id
        self._bodies: dict[int, str] = {}
        self._carry = {}
        for p in conn.execute("SELECT * FROM findings WHERE content_id=? AND decision='dismissed'", (content_id,)):
            p = dict(p)
            near = self.context(p["version"], p["span_start"], p["span_end"]) if p["target"] == "body" else ("", "")
            self._carry[(p["source_id"], p["span_text"], p["category"], *near)] = p

    def context(self, version: int, start: int, end: int) -> tuple[str, str]:
        if version not in self._bodies:
            self._bodies[version] = version_row(self.conn, self.content_id, version)["body"]
        b = self._bodies[version]
        before = re.split(r"[.!?\n]", b[max(0, start - CONTEXT):start])[-1]   # same sentence only, so an
        after = re.split(r"[.!?\n]", b[end:end + CONTEXT])[0]                 # edit next door changes nothing
        return " ".join(before.split()), " ".join(after.split())

    def earlier(self, f: Finding, version: int) -> Optional[dict]:
        """The dismissal that covers finding `f` of `version`, if a person already made one."""
        near = self.context(version, f.span_start, f.span_end) if f.target == "body" else ("", "")
        return self._carry.get((f.source_id, f.span_text, f.category, *near))


def _inherited_ai_findings(conn, content_id: int, ver: int, body: str) -> list[Finding]:
    """AI suggestions from the previous version, re-located in this text (the AI is not contacted again)."""
    out: list[Finding] = []
    if ver <= 1:
        return out
    for r in conn.execute(
            "SELECT * FROM findings WHERE content_id=? AND version=? AND ai_generated=1 "
            "AND target='body' AND decision IN ('open','dismissed')", (content_id, ver - 1)):
        start = body.find(r["span_text"]) if r["span_text"] else -1
        if start < 0:
            continue  # the flagged text is gone, so the suggestion no longer applies
        try:
            out.append(Finding(
                category=r["category"], issue=r["issue"], span_text=r["span_text"], span_start=start,
                span_end=start + len(r["span_text"]), target="body", source_type=r["source_type"],
                source_id=r["source_id"], source_quote=r["source_quote"], severity=r["severity"],
                confidence=r["confidence"], suggested_fix=r["suggested_fix"], fix_note=r["fix_note"],
                ai_generated=True))
        except Exception:
            continue
    return out


def _insert_finding(conn, content_id: int, ver: int, f, dismissals: _Dismissals) -> int:
    """Store one finding (a matching earlier dismissal carries over). Returns 1 if one was carried over."""
    old = dismissals.earlier(f, ver)
    decision = ("dismissed", f"(carried over) {old['decision_reason']}", old["decided_by"], old["decided_at"]) \
        if old else ("open", "", None, None)
    conn.execute(
        """INSERT INTO findings(content_id, version, category, issue, span_text, span_start, span_end, target,
             source_type, source_id, source_quote, severity, confidence, suggested_fix, fix_note,
             ai_generated, needs_reviewer, decision, decision_reason, decided_by, decided_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (content_id, ver, f.category, f.issue, f.span_text, f.span_start, f.span_end, f.target,
         f.source_type, f.source_id, f.source_quote, f.severity, f.confidence, f.suggested_fix, f.fix_note,
         int(f.ai_generated), int(f.needs_reviewer), *decision),
    )
    return 1 if old else 0


def _store_review(conn, content_id: int, ver: int, result, dismissals: _Dismissals) -> int:
    """Replace this version's findings and claims with `result`. Returns how many dismissals were carried over."""
    conn.execute("DELETE FROM findings WHERE content_id=? AND version=?", (content_id, ver))
    conn.execute("DELETE FROM claims WHERE content_id=? AND version=?", (content_id, ver))
    carried = 0
    for f in result.findings:
        carried += _insert_finding(conn, content_id, ver, f, dismissals)
    for cl in result.claims:
        conn.execute(
            "INSERT INTO claims(content_id, version, text, status, source_id) VALUES (?,?,?,?,?)",
            (content_id, ver, cl["text"], cl["status"], cl["source_id"]),
        )
    return carried


def run_review(conn, content_id: int, judge_factory: Optional[Callable] = None, ai: str = "fresh") -> dict:
    """(Re)review the current version. Dismissals made earlier on the same issue carry over.

    ai="fresh": ask the AI judge (it sees the content).  ai="inherit": do NOT contact the AI;
    suggestions it made on the previous version are re-located in the new text and kept.
    ai="off": the author chose not to send the text to the AI service; rules only."""
    c = dict(conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone())
    v = current(conn, c)
    ver = c["current_version"]
    dismissals = _Dismissals(conn, content_id)

    inherited = _inherited_ai_findings(conn, content_id, ver, v["body"]) if ai == "inherit" else []
    judge = judge_factory(conn, content_id, ver) if (judge_factory and ai == "fresh") else None
    schedule = getattr(judge_factory, "schedule", None) if judge else None
    if schedule:  # rules now, AI afterwards: the author is not kept waiting for the provider
        result = engine.review(engine.load_kb(conn), v["body"], v["images"], judge=None, inherited=inherited)
        result.llm_status = PENDING
    else:
        result = engine.review(engine.load_kb(conn), v["body"], v["images"], judge=judge, inherited=inherited)
    if ai == "off":
        result.llm_status = "skipped: AI review was switched off for this review (the text was not sent anywhere)"
    elif ai == "inherit" and not inherited:
        before = json.loads(version_row(conn, content_id, ver - 1)["review_meta"]).get("llm_status", "") if ver > 1 else ""
        result.llm_status = ("not re-run for this change (content was not re-sent)"
                             if before.startswith(("used", "not re-run")) else "not used")

    carried = _store_review(conn, content_id, ver, result, dismissals)
    meta = {"warnings": result.warnings, "rejected": result.rejected, "llm_status": result.llm_status,
            "truncated": result.truncated}
    if schedule:
        meta["pending_since"] = now()
    conn.execute("UPDATE versions SET review_meta=? WHERE content_id=? AND version=?",
                 (json.dumps(meta), content_id, ver))
    audit(conn, content_id, None, "review_run",
          f"v{ver}: {len(result.findings)} findings, {carried} carried over; AI judge: {result.llm_status}")
    conn.commit()
    if schedule:
        schedule(content_id, ver)
    return {"findings": len(result.findings), "carried_over": carried, **meta}


PENDING = "pending: the AI tone check is still running; the rule-based findings below are complete"


def complete_ai_review(conn, content_id: int, ver: int, judge_factory: Callable) -> None:
    """Background half of a review: ask the AI judge and add what survives verification to this version.
    Does nothing if the content has moved on to a newer version in the meantime."""
    def finish(status: str, rejected=(), added=0) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = version_row(conn, content_id, ver)
            meta = json.loads(row["review_meta"] or "{}")
            if not str(meta.get("llm_status", "")).startswith("pending"):
                conn.execute("ROLLBACK")
                return
            meta["llm_status"] = status
            meta["rejected"] = list(meta.get("rejected", [])) + list(rejected)
            conn.execute("UPDATE versions SET review_meta=? WHERE content_id=? AND version=?",
                         (json.dumps(meta), content_id, ver))
            audit(conn, content_id, None, "ai_review_done", f"v{ver}: {added} AI suggestion(s); {status}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    c = dict(conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone())
    if c["current_version"] != ver:
        return
    v = version_row(conn, content_id, ver)
    body, images = v["body"], json.loads(v["images"])
    try:
        judge = judge_factory(conn, content_id, ver)
        if judge is None:
            return finish("not used")
        existing = [types.SimpleNamespace(span_start=r["span_start"], span_end=r["span_end"], target=r["target"])
                    for r in conn.execute("SELECT span_start, span_end, target FROM findings WHERE content_id=? AND version=?",
                                          (content_id, ver))]
        accepted, rejected, status = engine.ai_pass(engine.load_kb(conn), body, images, existing, judge)
        dismissals = _Dismissals(conn, content_id)
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT current_version FROM content WHERE id=?", (content_id,)).fetchone()[0] != ver:
                conn.execute("ROLLBACK")
                return
            for f in accepted:
                _insert_finding(conn, content_id, ver, f, dismissals)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finish(status, rejected, len(accepted))
    except Exception as exc:  # never leave a review "pending" forever
        finish(f"failed: {type(exc).__name__}: {exc}"[:200])


def settle_interrupted_reviews(conn) -> int:
    """At start-up: an AI check that was running when the server stopped will never finish; say so."""
    n = 0
    for r in conn.execute("SELECT content_id, version, review_meta FROM versions WHERE review_meta LIKE '%pending%'").fetchall():
        meta = json.loads(r["review_meta"] or "{}")
        started = meta.get("pending_since") or ""
        stale = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=120)).isoformat(timespec="seconds")
        if str(meta.get("llm_status", "")).startswith("pending") and started < stale:  # another worker may be mid-job
            meta["llm_status"] = "interrupted: the AI tone check did not finish (server restarted); run the review again"
            conn.execute("UPDATE versions SET review_meta=? WHERE content_id=? AND version=?",
                         (json.dumps(meta), r["content_id"], r["version"]))
            n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------- content
def create_content(conn, user: dict, title: str, body: str, images: list[dict],
                   judge_factory: Optional[Callable] = None, ai: str = "fresh") -> int:
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
    run_review(conn, cid, judge_factory, ai)
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
           judge_factory: Optional[Callable] = None, ai: str = "fresh") -> int:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_revise"]:
        raise Forbidden("Only the author can edit, and only while the content is a draft or has changes requested")
    body = _text(body, "Content text", MAX_BODY, required=True)
    return _new_version(conn, c, user["id"], body, _clean_images(images), "Edited by author", judge_factory, ai)


# -------------------------------------------------------------------- decisions
def _dismiss(conn, user: dict, c: dict, f: dict, perms: dict, reason: Optional[str]) -> dict:
    reason = _text(reason, "Reason", MAX_FIELD).strip()
    if not reason:
        raise ValueError("A reason is required to dismiss a finding")
    if (f["category"] in RISKY or f["needs_reviewer"]) and not perms["can_dismiss_risky"]:
        raise Forbidden("Only a manager or reviewer can dismiss fact, claim or low-confidence findings")
    if not conn.execute(
            "UPDATE findings SET decision='dismissed', decision_reason=?, decided_by=?, decided_at=? "
            "WHERE id=? AND decision='open'", (reason, user["id"], now(), f["id"])).rowcount:
        raise ValueError("Someone else already decided this finding")
    audit(conn, c["id"], user["id"], "finding_dismissed", f"#{f['id']} {f['source_id']}: {reason}")
    conn.commit()
    return {"decision": "dismissed", "new_version": None}


def _apply(f: dict, replacement: str, body: str, images: list[dict]) -> tuple[str, list[dict], str]:
    """Put `replacement` where the finding points: into the text, or into an image's alt text or colour.
    Returns the new body, the new images and the (cleaned) replacement."""
    if f["target"] == "body":
        s, e = f["span_start"], f["span_end"]
        if body[s:e] != f["span_text"]:
            raise ValueError("The content changed since this review. Re-run the review first.")
        body = body[:s] + replacement + body[e:]
        if not body.strip():
            raise ValueError("That change would leave the content empty")
        return body, images, replacement
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
    return body, images, replacement


def decide(conn, user: dict, finding_id: int, action: str, text: Optional[str] = None,
           reason: Optional[str] = None, judge_factory: Optional[Callable] = None) -> dict:
    """Accept the suggested fix, edit it, or dismiss the finding. Accept and edit create a new version."""
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
        return _dismiss(conn, user, c, f, perms, reason)

    if action == "accept":
        if is_restricted(f, visible_sources(conn, user)):
            raise Forbidden("This fix comes from a restricted source. Ask the brand team, or use Edit to write your own wording.")
        replacement = f["suggested_fix"]
        if not replacement:
            raise ValueError("This finding has no suggested fix. Use edit to write one, or dismiss it.")
    else:
        if text is None:
            raise ValueError("Provide the replacement text")
        replacement = _text(text, "Replacement", 2000)
    v = current(conn, c)
    body, images, replacement = _apply(f, replacement, v["body"], [dict(i) for i in v["images"]])
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
    if finding_id is not None:
        if isinstance(finding_id, bool) or not isinstance(finding_id, int):
            raise ValueError("finding_id must be a number")
        if not conn.execute("SELECT 1 FROM findings WHERE id=? AND content_id=? AND version=?",
                            (finding_id, c["id"], c["current_version"])).fetchone():
            raise ValueError("That finding is not part of the current version of this content")
    conn.execute("INSERT INTO comments(content_id, finding_id, user_id, body, created_at) VALUES (?,?,?,?,?)",
                 (c["id"], finding_id, user["id"], body, now()))
    audit(conn, c["id"], user["id"], "comment", body[:120])
    conn.commit()


def submit(conn, user: dict, content_id: int) -> None:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_submit"]:
        raise Forbidden("Only the author can submit, and only a draft or content with changes requested")
    if str(current(conn, c)["review_meta"].get("llm_status", "")).startswith("pending"):
        raise ValueError("The AI tone check is still running. Wait a few seconds, then submit.")
    hidden = current(conn, c)["review_meta"].get("truncated", 0)
    if hidden:
        raise ValueError(f"{hidden} more findings are not shown yet. Fix the ones you can see and run the review again before submitting.")
    if not conn.execute("UPDATE content SET status='in_review' WHERE id=? AND status=? AND current_version=?",
                        (c["id"], c["status"], c["current_version"])).rowcount:
        raise ValueError("Someone else changed this content a moment ago. Reload and try again.")
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
    if conn.execute("SELECT 1 FROM versions WHERE content_id=? AND created_by=? AND version>1", (c["id"], user["id"])).fetchone():
        raise Forbidden("You edited this content, so someone else must approve it")
    if not conn.execute("UPDATE content SET status='approved' WHERE id=? AND status='in_review' AND current_version=?",
                        (c["id"], c["current_version"])).rowcount:
        raise ValueError("Someone else changed this content a moment ago. Reload and try again.")
    audit(conn, c["id"], user["id"], "approved", f"v{c['current_version']}")
    conn.commit()


def request_changes(conn, user: dict, content_id: int, note: str) -> None:
    c = get_content(conn, user, content_id)
    if not permissions(conn, user, c)["can_request_changes"]:
        raise Forbidden("Only a manager or reviewer can request changes on content in review")
    note = _text(note, "Note", MAX_FIELD)
    if not note.strip():
        raise ValueError("Say what needs to change")
    if not conn.execute("UPDATE content SET status='changes_requested' WHERE id=? AND status='in_review'",
                        (c["id"],)).rowcount:
        raise ValueError("Someone else changed this content a moment ago. Reload and try again.")
    conn.execute("INSERT INTO comments(content_id, finding_id, user_id, body, created_at) VALUES (?,?,?,?,?)",
                 (c["id"], None, user["id"], f"Changes requested: {note.strip()}", now()))
    audit(conn, c["id"], user["id"], "changes_requested", note.strip()[:120])
    conn.commit()


def list_content(conn, user: dict, limit: int = 50, offset: int = 0) -> list[dict]:
    where, args = ("", ())
    if user["role"] == "creator":
        where, args = ("WHERE c.author_id=?", (user["id"],))
    rows = conn.execute(
        f"""SELECT c.*, u.name AS author,
              (SELECT COUNT(*) FROM findings f WHERE f.content_id=c.id AND f.version=c.current_version
                  AND f.decision='open') AS open_findings,
              (SELECT COUNT(*) FROM findings f WHERE f.content_id=c.id AND f.version=c.current_version) AS total_findings
            FROM content c JOIN users u ON u.id=c.author_id {where} ORDER BY c.id DESC LIMIT ? OFFSET ?""", (*args, limit, offset))
    return [dict(r) for r in rows]


def count_content(conn, user: dict) -> int:
    if user["role"] == "creator":
        return conn.execute("SELECT COUNT(*) FROM content WHERE author_id=?", (user["id"],)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
