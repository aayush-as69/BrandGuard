"""Knowledge base import: guidelines, approved facts, glossary, assets, check settings."""
from __future__ import annotations

import datetime as dt
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
    try:
        if name.endswith((".txt", ".md", ".markdown")):
            return data.decode("utf-8", errors="replace")
        if name.endswith(".docx"):
            import docx  # python-docx

            document = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in document.paragraphs)
        if name.endswith(".pdf"):
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if not text.strip():
                raise ValueError("That PDF has no selectable text (it may be a scan). Paste the text instead.")
            return text
    except ValueError:
        raise
    except Exception as exc:  # corrupt or encrypted files
        raise ValueError(f"Could not read that file ({type(exc).__name__}). Is it a valid {name.rsplit('.', 1)[-1]}?") from exc
    raise ValueError("Unsupported file type. Use .txt, .md, .docx or .pdf")


def parse_rules(text: str, guideline_id: int) -> list[tuple[str, str, str]]:
    """Structured lines become coded rules. Anything else is split by paragraph
    and given generated codes, so an unstructured PDF still imports."""
    rules: list[tuple[str, str, str]] = []
    buffer: list[str] = []
    loose = 0

    def flush() -> None:
        nonlocal loose
        paragraph = " ".join(" ".join(buffer).split())
        buffer.clear()
        if len(paragraph) >= 20:
            loose += 1
            rules.append((f"S{guideline_id}-{loose}", " ".join(paragraph.split()[:6]), paragraph))

    for line in text.splitlines():
        m = _RULE_LINE.match(line)
        if m:
            flush()
            rules.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
        elif not line.strip() or line.lstrip().startswith("#"):
            flush()
        else:
            buffer.append(line.strip())
    flush()
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
        if not isinstance(f, dict):
            raise ValueError("Each fact must be an object")
        for key in ("code", "kind", "statement"):
            if not f.get(key):
                raise ValueError(f"Fact is missing '{key}': {f}")
        if f["kind"] not in {"price", "date", "claim", "superlative"}:
            raise ValueError(f"Unknown fact kind '{f['kind']}'")
        data = f.get("data", {})
        if not isinstance(data, dict):
            raise ValueError(f"Fact {f['code']}: 'data' must be an object")
        if conn.execute("SELECT 1 FROM facts WHERE code=?", (f["code"],)).fetchone():
            raise ValueError(f"Fact {f['code']} already exists")
        if f["kind"] == "price" and not isinstance(data.get("amount"), (int, float)):
            raise ValueError(f"Fact {f['code']}: a price fact needs a numeric data.amount")
        if f["kind"] == "date":
            try:
                dt.date.fromisoformat(str(data.get("date")))
            except ValueError:
                raise ValueError(f"Fact {f['code']}: a date fact needs data.date as YYYY-MM-DD") from None
        for key in ("match", "keywords", "contradicts", "phrases"):
            if key in data and not (isinstance(data[key], list) and all(isinstance(x, str) for x in data[key])):
                raise ValueError(f"Fact {f['code']}: data.{key} must be a list of text")
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
        if not isinstance(e, dict):
            raise ValueError("Each glossary entry must be an object")
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
        if not isinstance(a, dict) or not a.get("name") or not a.get("kind"):
            raise ValueError(f"Asset needs 'name' and 'kind': {a}")
        conn.execute(
            "INSERT INTO assets(name, kind, note, access_level) VALUES (?,?,?,?)",
            (a["name"], a["kind"], a.get("note", ""), _check_level(a.get("access_level", "internal"))),
        )
    conn.commit()
    return len(assets)


def import_settings(conn: sqlite3.Connection, settings: dict) -> int:
    """Which rule each automated check cites, and its parameters."""
    if not isinstance(settings, dict):
        raise ValueError("Settings must be a JSON object")
    checks = settings.get("rule_checks", {})
    if not isinstance(checks, dict) or not all(isinstance(v, dict) for v in checks.values()):
        raise ValueError("rule_checks must map each check name to an object")
    for name, cfg in checks.items():
        for key in ("max", "min_len", "max_len", "min_ratio"):
            if key in cfg and not isinstance(cfg[key], (int, float)):
                raise ValueError(f"rule_checks.{name}.{key} must be a number")
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
