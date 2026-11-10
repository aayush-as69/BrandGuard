"""Review of knowledge-base import parsing: hostile input, validation, atomicity."""
import io
import json
import time

import pytest

from brandguard import kb
from conftest import IRA, NEHA, Session


def _import(ira, kind, text, **extra):
    return ira.c.post("/api/kb/import", data={"kind": kind, "text": text, **extra})


def test_rule_parser_is_linear_on_hostile_lines():
    start = time.perf_counter()
    kb.parse_rules("G-1 |" + " " * 400_000 + "x\nG-2 | Voice: Write warmly.", 1)
    kb.parse_rules("G-1 | " + ":" * 300_000 + "\n" + "G-1 |" * 50_000, 1)
    assert time.perf_counter() - start < 1.0  # the old regex needed minutes for the first line alone


def test_rule_lines_still_parse_as_before():
    assert kb.parse_rules("G-01 | Voice: Write warmly: always.", 1) == [("G-01", "Voice", "Write warmly: always.")]
    assert kb.parse_rules("G-01 | : no title", 1) == []  # empty title: not a rule line (and too short to be a paragraph)
    assert kb.parse_rules("G-01 | A|B: this line is long enough to count as text", 1)[0][0].startswith("S")  # a '|' inside the title: treated as plain text
    assert kb.parse_rules("x" * 6000 + "\nG-02 | T: ok", 1)[-1][0] == "G-02"


def test_settings_that_would_crash_reviews_are_refused(seeded):
    ira = Session(seeded, IRA)
    bad = [{"rule_checks": {"all_caps": {"allow": 5}}},
           {"rule_checks": {"all_caps": {"allow": [["x"]]}}},
           {"rule_checks": {"exclamation": {"max": float("nan")}}},
           {"rule_checks": {"exclamation": {"max": -1}}},
           {"rule_checks": {"alt_text": {"min_len": 50, "max_len": 5}}},
           {"rule_checks": {"contrast": {"rule_code": 7}}},
           {"other_key": 1}]
    for payload in bad:
        r = _import(ira, "settings", json.dumps(payload, allow_nan=True))
        assert r.status_code == 400, payload
    n = Session(seeded, NEHA)  # and reviewing still works afterwards
    assert n.post("/api/content", title="t", body="Hi Dude!!", images=[]).status_code == 201


def test_fact_glossary_asset_types_are_validated(seeded):
    ira = Session(seeded, IRA)
    facts = [{"code": 5, "kind": "claim", "statement": "x"}, {"code": "bad code!", "kind": "claim", "statement": "x"},
             {"code": "F-9", "kind": "claim", "statement": ["x"]}, {"code": "F-9", "kind": "claim", "statement": "x", "source": 3}]
    for f in facts:
        assert _import(ira, "facts", json.dumps([f])).status_code == 400, f
    gl = [{"term": "a", "preferred": "b", "rule_code": "G-03", "kind": "weird"},
          {"term": 5, "preferred": "b", "rule_code": "G-03"}, {"term": "a", "preferred": "b", "rule_code": "G-03", "note": 4}]
    for g in gl:
        assert _import(ira, "glossary", json.dumps([g])).status_code == 400, g
    assert _import(ira, "assets", json.dumps([{"name": ["x"], "kind": "logo"}])).status_code == 400


def test_nested_json_is_a_400_not_a_500(seeded):
    r = _import(Session(seeded, IRA), "facts", "[" * 200_000)
    assert r.status_code == 400 and "nested" in r.get_json()["error"]


def test_failed_guideline_import_leaves_nothing_behind(seeded):
    ira = Session(seeded, IRA)
    from brandguard import db
    before = db.connect(seeded.config["DB_PATH"]).execute("SELECT COUNT(*) FROM guidelines").fetchone()[0]
    text = "H-01 | Tone: Be kind to everyone.\nH-02 | Price: Quote INR.\nH-01 | Again: duplicate code in the file."
    assert _import(ira, "guidelines", text).status_code == 400
    after = db.connect(seeded.config["DB_PATH"]).execute("SELECT COUNT(*) FROM guidelines").fetchone()[0]
    assert after == before
    assert db.connect(seeded.config["DB_PATH"]).execute("SELECT COUNT(*) FROM rules WHERE code LIKE 'H-%'").fetchone()[0] == 0


def test_duplicate_fact_in_one_file_is_refused_whole(seeded):
    ira = Session(seeded, IRA)
    from brandguard import db
    facts = [{"code": "Z-1", "kind": "claim", "statement": "a"}, {"code": "Z-1", "kind": "claim", "statement": "b"}]
    assert _import(ira, "facts", json.dumps(facts)).status_code == 400
    assert db.connect(seeded.config["DB_PATH"]).execute("SELECT COUNT(*) FROM facts WHERE code='Z-1'").fetchone()[0] == 0
