"""Check the real AI judge end to end. Needs network access and ANTHROPIC_API_KEY.

    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/check_live_ai.py

It loads the demo knowledge base into a throwaway database, reviews content that has tone problems the
rules cannot catch (no banned word in it), and reports what the model returned, what survived
verification, and what was rejected. Exit code 0 means the live path works.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brandguard import db as dbm, engine, kb as kbm, llm  # noqa: E402

TEXT = ("Hi there,\n\nListen up: our coffee will absolutely blow every other brand out of the water, "
        "and if you don't buy today you are honestly missing out on life.\n\n"
        "Brewline Signature Blend is a medium-dark roast from Coorg and Chikmagalur.\n\nWarmly, Brewline")


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY first."); return 2
    path = tempfile.mktemp(suffix=".db")
    conn = dbm.connect(path); dbm.init(conn)
    kbm.seed_demo(conn, Path(__file__).resolve().parent.parent / "seed")
    judge = llm.make_judge(conn, None, None)
    res = engine.review(engine.load_kb(conn), TEXT, [], judge=judge)
    print("status:", res.llm_status)
    for f in res.findings:
        tag = "AI  " if f.ai_generated else "rule"
        print(f"  [{tag}] {f.source_id:6} {f.confidence:6} {f.span_text!r}: {f.issue}")
    for r in res.rejected:
        print("  rejected:", r)
    log = conn.execute("SELECT COUNT(*) c FROM llm_log").fetchone()["c"]
    print(f"logged requests: {log}")
    ok = res.llm_status.startswith("used") and any(f.ai_generated for f in res.findings)
    print("RESULT:", "OK - the live judge returned verified findings" if ok else
          "CHECK - no verified AI findings (see status/rejected above; this may still be correct if the model found nothing)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
