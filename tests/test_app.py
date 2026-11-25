"""Render the Streamlit app with a canned brief, no API call."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from jury import brief_to_json
from jury.brief import load_challenges
from jury.citations import verify_brief
from jury.kimi import Usage
from jury.report import to_markdown

from test_offline import sample_pack

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def canned_brief(ch):
    ev = [{"file": "api/app.py", "quote": 'return {"corrosion": "severe", "confidence": 0.97}'}]
    return {
        "project_name": "CorroScan",
        "what_it_does": "Flags corrosion on aircraft panel photos.",
        "verdict": "The UI and API exist, but the prediction is hard-coded.",
        "claims": [{"claim": "Real-time detection with watsonx", "made_in": "README.md", "status": "contradicted",
                    "explanation": "The endpoint returns a constant.", "evidence": ev}],
        "required_stack": [{"item": s, "status": "superficial", "explanation": "Mentioned only.", "evidence": []}
                           for s in ch.required_stack],
        "criteria": [{"name": c.name, "score": 5, "justification": "ok", "evidence": ev} for c in ch.criteria],
        "red_flags": [{"issue": "Committed credentials", "severity": "high",
                       "evidence": [{"file": "config.py", "quote": "WATSONX_API_KEY"}]}],
        "strengths": ["Clear README"],
        "jury_questions": [{"question": f"Q{i}?", "why": "w"} for i in range(1, 4)],
    }


def test_app_renders_canned_brief():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception

    ch = load_challenges()["haks-2026"]
    pack = sample_pack()
    brief = canned_brief(ch)
    totals = verify_brief(pack, brief)
    md = to_markdown(brief, ch, "en", repo=pack.name, ref=pack.ref)
    at.session_state["pack"] = pack
    at.session_state["result"] = {
        "brief": brief, "pack": pack, "challenge": ch, "lang": "en", "model": "kimi-k3.1-pro", "effort": "high",
        "usage": Usage(prompt=200_000, cached=0, completion=9_000, reasoning=6_000), "seconds": 42.0,
        "totals": totals, "mode": "json_schema", "markdown": md, "json": brief_to_json(brief),
    }
    at.run()
    assert not at.exception
    assert any(m.value == "CorroScan" for m in at.subheader)
    labels = [m.label for m in at.metric]
    assert "Citations found in repo" in labels
    assert "Committed credentials" in "\n".join(m.value for m in at.markdown)
