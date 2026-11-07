"""Knowledge base import: guidelines, approved facts, glossary, assets, check settings."""
from __future__ import annotations

import io
import json
import re
import sqlite3
from pathlib import Path

from .db import now

ACCESS_LEVELS = {"public": 0, "internal": 1, "confidential": 2}

# "G-01 | Voice: Write in a warm, calm voice."  ->  code, title, text
_RULE_LINE = re.compile(r"^\s*([A-Z]{1,4}-\d+)\s*\|\s*([^:|]+?)\s*:\s*(.+?)\s*$")


def _check_level(level: str) -> str:
    if level not in ACCESS_LEVELS:
        raise ValueError(f"access_level must be one of {sorted(ACCESS_LEVELS)}")
    return level


def extract_text(filename: str, data: bytes) -> str:
    """Return plain text from a .txt/.md, .docx or .pdf upload."""
    name = filename.lower()
    if name.endswith((".txt", ".md", ".markdown")):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".docx"):
        import docx  # python-docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    raise ValueError("Unsupported file type. Use .txt, .md, .docx or .pdf")


def parse_rules(text: str, guideline_id: int) -> list[tuple[str, str, str]]:
    """Structured lines become coded rules. Anything else is split by paragraph
    and given generated codes, so an unstructured PDF still imports."""
    rules: list[tuple[str, str, str]] = []
    loose: list[str] = []
    for line in text.splitlines():
        m = _RULE_LINE.match(line)
        if m:
            rules.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
        elif line.strip() and not line.lstrip().startswith("#"):
            loose.append(line.strip())
    if not rules:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 20]
        for i, p in enumerate(paragraphs, 1):
            clean = " ".join(p.split())
            title = " ".join(clean.split()[:6])
            rules.append((f"S{guideline_id}-{i}", title, clean))
    return rules


def import_guidelines(conn: sqlite3.Connection, title: str, text: str, access_level: str = "internal") -> dict:
    _check_level(access_level)
    if not text.strip():
        raise ValueError("Guideline text is empty")
    cur = conn.execute(
        "INSERT INTO guidelines(title, access_level, imported_at) VALUES (?,?,?)",
        (title, access_level, now()),
    )
    gid = cur.lastrowid
    rules = parse_rules(text, gid)
    if not rules:
        raise ValueError("No rules could be found in that text")
    for code, rtitle, rtext in rules:
        if conn.execute("SELECT 1 FROM rules WHERE code=?", (code,)).fetchone():
            raise ValueError(f"Rule code {code} already exists in the knowledge base")
        conn.execute(
            "INSERT INTO rules(guideline_id, code, title, text) VALUES (?,?,?,?)",
            (gid, code, rtitle, rtext),
        )
    conn.commit()
    return {"guideline_id": gid, "rules": len(rules)}


def import_facts(conn: sqlite3.Connection, facts: list[dict]) -> int:
    """Each fact: code, kind (price|date|claim|superlative), statement, plus kind-specific data."""
    for f in facts:
        for key in ("code", "kind", "statement"):
            if not f.get(key):
                raise ValueError(f"Fact is missing '{key}': {f}")
        if f["kind"] not in {"price", "date", "claim", "superlative"}:
            raise ValueError(f"Unknown fact kind '{f['kind']}'")
        data = f.get("data", {})
        conn.execute(
            "INSERT INTO facts(code, kind, statement, data, source, access_level) VALUES (?,?,?,?,?,?)",
            (
                f["code"], f["kind"], f["statement"], json.dumps(data),
                f.get("source", ""), _check_level(f.get("access_level", "internal")),
            ),
        )
    conn.commit()
    return len(facts)


def import_glossary(conn: sqlite3.Connection, entries: list[dict]) -> int:
    for e in entries:
        for key in ("term", "preferred", "rule_code"):
            if not e.get(key):
                raise ValueError(f"Glossary entry is missing '{key}': {e}")
        if not conn.execute("SELECT 1 FROM rules WHERE code=?", (e["rule_code"],)).fetchone():
            raise ValueError(
                f"Glossary term '{e['term']}' cites rule {e['rule_code']}, which is not in the knowledge base. "
                "Import the guidelines first."
            )
        conn.execute(
            "INSERT INTO glossary(term, preferred, kind, rule_code, note) VALUES (?,?,?,?,?)",
            (e["term"], e["preferred"], e.get("kind", "banned"), e["rule_code"], e.get("note", "")),
        )
    conn.commit()
    return len(entries)


def import_assets(conn: sqlite3.Connection, assets: list[dict]) -> int:
    for a in assets:
        if not a.get("name") or not a.get("kind"):
            raise ValueError(f"Asset needs 'name' and 'kind': {a}")
        conn.execute(
            "INSERT INTO assets(name, kind, note, access_level) VALUES (?,?,?,?)",
            (a["name"], a["kind"], a.get("note", ""), _check_level(a.get("access_level", "internal"))),
        )
    conn.commit()
    return len(assets)


def import_settings(conn: sqlite3.Connection, settings: dict) -> int:
    """Which rule each automated check cites, and its parameters."""
    for key, value in settings.items():
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
    conn.commit()
    return len(settings)


def clear_kb(conn: sqlite3.Connection) -> None:
    for table in ("glossary", "rules", "guidelines", "facts", "assets", "settings"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def seed_demo(conn: sqlite3.Connection, seed_dir: Path) -> dict:
    """Load the synthetic Brewline Coffee knowledge base (replaces the current one)."""
    clear_kb(conn)
    out = {}
    out["guidelines"] = import_guidelines(
        conn, "Brewline Coffee Brand Guidelines (synthetic)",
        (seed_dir / "guidelines.md").read_text(encoding="utf-8"),
    )
    out["facts"] = import_facts(conn, json.loads((seed_dir / "facts.json").read_text(encoding="utf-8")))
    out["glossary"] = import_glossary(conn, json.loads((seed_dir / "glossary.json").read_text(encoding="utf-8")))
    out["assets"] = import_assets(conn, json.loads((seed_dir / "assets.json").read_text(encoding="utf-8")))
    out["settings"] = import_settings(conn, json.loads((seed_dir / "settings.json").read_text(encoding="utf-8")))
    return out
