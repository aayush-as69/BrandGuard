"""Engine tests: seeded traps, citations, claim statuses, and rejection of fabricated AI output."""
import json
import sqlite3
from pathlib import Path

from brandguard import db, engine, kb, llm, retrieve
from brandguard.models import Finding

SEED = Path(__file__).resolve().parent.parent / "seed"


def make_kb(tmp_path):
    conn = db.connect(str(tmp_path / "e.db"))
    db.init(conn)
    kb.seed_demo(conn, SEED)
    return conn, engine.load_kb(conn)


def by_source(findings, source_id):
    return [f for f in findings if f.source_id == source_id]


def test_all_seeded_traps_are_caught(tmp_path, demo):
    _, k = make_kb(tmp_path)
    r = engine.review(k, demo["body"], demo["images"])
    f = r.findings
    # unsupported claim
    rank = [x for x in f if x.category == "claim"]
    assert len(rank) == 1 and "#1" in rank[0].span_text and rank[0].source_id == "G-04"
    # outdated facts: price, launch date, roast
    price = by_source(f, "F-01")[0]
    assert (price.span_text, price.suggested_fix) == ("₹399", "₹449")
    date = by_source(f, "F-02")[0]
    assert (date.span_text, date.suggested_fix) == ("1 December 2026", "15 December 2026")
    assert by_source(f, "F-04")[0].suggested_fix == "medium-dark roast"
    # banned term and off-tone language
    assert any(x.category == "terminology" and x.span_text.endswith("cheap") for x in f)
    assert {x.span_text for x in f if x.category == "tone"} >= {"Dude", "insanely good", "!!!"}
    # accessibility: missing alt text and low contrast
    acc = [x for x in f if x.category == "accessibility"]
    assert len(acc) == 2
    assert any("no usable alt text" in x.issue for x in acc)
    assert any("contrast" in x.issue.lower() for x in acc)


def test_every_finding_cites_a_real_source_and_quote(tmp_path, demo):
    _, k = make_kb(tmp_path)
    r = engine.review(k, demo["body"], demo["images"])
    assert r.findings and not r.rejected
    for f in r.findings:
        assert engine.verify(f, k, demo["body"], demo["images"]) is None
        assert f.source_quote.strip()


def test_supported_claim_is_not_flagged_and_unsupported_is_never_guessed(tmp_path, demo):
    _, k = make_kb(tmp_path)
    r = engine.review(k, demo["body"], demo["images"])
    statuses = {(c["status"], c["source_id"]) for c in r.claims}
    assert ("supported", "F-03") in statuses  # Coorg / Chikmagalur sourcing matches the fact sheet
    assert ("no_approved_source", "") in statuses  # the #1 claim has no source and no invented one
    assert not by_source(r.findings, "F-03")


def test_clean_content_has_no_findings(tmp_path):
    _, k = make_kb(tmp_path)
    body = ("Hello,\n\nSignature Blend launches on 15 December 2026. A 250g pouch is ₹449, "
            "with beans sourced from Coorg and Chikmagalur. It is a medium-dark roast.\n\nWarmly, Brewline")
    imgs = [{"name": "hero.png", "alt": "A copper pouch of Signature Blend", "text_color": "#000000", "bg_color": "#FFFFFF"}]
    r = engine.review(k, body, imgs)
    assert r.findings == []
    assert {c["status"] for c in r.claims} == {"supported"}


def test_contrast_math():
    assert round(engine.contrast_ratio("#000000", "#FFFFFF"), 1) == 21.0
    assert round(engine.contrast_ratio("#777777", "#FFFFFF"), 2) == 4.48  # known WCAG borderline grey
    assert engine.contrast_ratio("nothex", "#FFFFFF") is None
    fixed = engine.darken_to_pass("#9A9A9A", "#FFFFFF", 4.5)
    assert engine.contrast_ratio(fixed, "#FFFFFF") >= 4.5


def test_missing_rule_in_settings_is_reported_not_crashed(tmp_path, demo):
    conn, _ = make_kb(tmp_path)
    kb.import_settings(conn, {"rule_checks": {"claims": {"rule_code": "G-99"}}})
    r = engine.review(engine.load_kb(conn), demo["body"], demo["images"])
    assert any("G-99" in w for w in r.warnings)


def test_kb_import_unstructured_text_and_docx(tmp_path):
    import io

    import docx

    conn = db.connect(str(tmp_path / "k.db"))
    db.init(conn)
    out = kb.import_guidelines(conn, "Loose", "Always be kind to customers in every message.\n\nNever promise delivery dates.")
    assert out["rules"] == 2
    d = docx.Document()
    d.add_paragraph("G-50 | Greeting: Start every email with a greeting.")
    buf = io.BytesIO()
    d.save(buf)
    text = kb.extract_text("rules.docx", buf.getvalue())
    assert kb.import_guidelines(conn, "Docx", text)["rules"] == 1
    assert conn.execute("SELECT code FROM rules WHERE code='G-50'").fetchone()
    try:
        kb.extract_text("x.exe", b"")
        raise AssertionError("should reject")
    except ValueError:
        pass


def test_retrieval_finds_relevant_rule():
    rules = {"G-1": {"title": "Voice", "text": "Avoid slang and hype in a warm calm voice"},
             "G-2": {"title": "Accessibility", "text": "Every image needs alt text and contrast"}}
    assert retrieve.top_rules("this slang is hype", rules, k=1) == ["G-1"]
    assert retrieve.top_rules("image alt text", rules, k=1) == ["G-2"]


# ----------------------------------------------------------------------- AI judge
def run_judge(tmp_path, demo, reply):
    conn, k = make_kb(tmp_path)
    judge = llm.make_judge(conn, call=lambda s, u, m: reply)
    return engine.review(k, demo["body"], demo["images"], judge=judge), conn


def test_ai_finding_is_labelled_capped_and_verified(tmp_path, demo):
    reply = json.dumps([{
        "rule_code": "G-01", "quote": "Avoid slang and hype", "span": "taste the difference",
        "issue": "Generic hype phrase.", "severity": "low", "confidence": "high", "fix": "enjoy it for yourself",
    }])
    r, conn = run_judge(tmp_path, demo, reply)
    ai = [f for f in r.findings if f.ai_generated]
    assert len(ai) == 1
    assert ai[0].confidence == "medium"  # AI is never "high"
    assert r.llm_status.startswith("used")
    assert conn.execute("SELECT COUNT(*) FROM llm_log").fetchone()[0] == 1  # what was sent is logged


def test_fabricated_ai_output_is_rejected(tmp_path, demo):
    reply = json.dumps([
        {"rule_code": "G-01", "quote": "Never mention coffee", "span": "taste the difference", "issue": "Invented quote."},
        {"rule_code": "G-77", "quote": "anything at all", "span": "taste the difference", "issue": "Invented rule."},
        {"rule_code": "G-01", "quote": "Avoid slang and hype", "span": "words that are not in the email", "issue": "Invented span."},
        {"issue": "x"},
    ])
    r, _ = run_judge(tmp_path, demo, reply)
    assert not [f for f in r.findings if f.ai_generated]
    assert len([x for x in r.rejected if x.startswith("[AI]")]) == 3


def test_ai_failure_does_not_break_the_review(tmp_path, demo):
    conn, k = make_kb(tmp_path)

    def boom(s, u, m):
        raise ConnectionError("network down")

    r = engine.review(k, demo["body"], demo["images"], judge=llm.make_judge(conn, call=boom))
    assert r.llm_status.startswith("failed") and len(r.findings) >= 10


def test_ai_does_not_duplicate_rule_findings(tmp_path, demo):
    reply = json.dumps([{"rule_code": "G-01", "quote": "Avoid slang and hype", "span": "insanely good", "issue": "Hype."}])
    r, _ = run_judge(tmp_path, demo, reply)
    assert not [f for f in r.findings if f.ai_generated]


def test_finding_schema_rejects_malformed_records():
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        Finding(category="tone", issue="ok issue", source_type="guideline", source_id="G-01",
                source_quote="", severity="low", confidence="high")
    with pytest.raises(pydantic.ValidationError):
        Finding(category="nonsense", issue="ok issue", source_type="guideline", source_id="G-01",
                source_quote="quote", severity="low", confidence="high")


# ------------------------------------------------------------- fix wording
def test_fix_at_sentence_start_is_capitalised(tmp_path, demo):
    _, k = make_kb(tmp_path)
    r = engine.review(k, demo["body"], demo["images"])
    rank = next(f for f in r.findings if f.category == "claim")
    assert rank.suggested_fix == "Our coffee"  # starts the sentence
    mid = engine.review(k, "Hello,\n\nWe think this is India's #1 coffee for sure.", [])
    assert next(f for f in mid.findings if f.category == "claim").suggested_fix == "our coffee"


def test_article_agrees_after_replacement(tmp_path, demo):
    _, k = make_kb(tmp_path)
    r = engine.review(k, demo["body"], demo["images"])
    cheap = next(f for f in r.findings if f.category == "terminology")
    assert cheap.span_text == "a cheap" and cheap.suggested_fix == "an affordable"
    assert engine.verify(cheap, k, demo["body"], demo["images"]) is None
    applied = demo["body"][:cheap.span_start] + cheap.suggested_fix + demo["body"][cheap.span_end:]
    assert "an affordable price" in applied and "a affordable" not in applied
    # no article change needed when it already agrees
    ok = engine.review(k, "This is an addictive blend.", [])
    assert next(f for f in ok.findings).suggested_fix == "irresistible"  # "an" is already right
    plain = engine.review(k, "Our cheap beans.", [])
    assert next(f for f in plain.findings).suggested_fix == "affordable"
