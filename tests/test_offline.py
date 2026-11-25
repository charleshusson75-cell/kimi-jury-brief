"""Offline tests: packing, secret redaction, citation checks. No API key needed."""

import io
import json
import zipfile

from jury.brief import load_challenges, weighted_score
from jury.citations import locate, verify_brief
from jury.repo import REDACTED, pack_zip

APP = '''from fastapi import FastAPI
app = FastAPI()

@app.post("/predict")
def predict(image: bytes):
    # TODO: call the watsonx model
    return {"corrosion": "severe", "confidence": 0.97}
'''

FAKE_IBM = "a1B2c3D4" + "e5F6g7H8i9J0kLmN"
FAKE_OPENAI = "sk-" + "proj-" + "Q7w" * 12

README = """# CorroScan
Real-time corrosion detection on aircraft panels with IBM watsonx and AWS.
"""


def make_zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr("team-repo-main/" + path, content)
    return buf.getvalue()


def sample_pack():
    nb = {"cells": [{"cell_type": "code", "source": ["import boto3\n", "s3 = boto3.client('s3')"],
                     "outputs": [{"data": {"image/png": "A" * 50_000}}]}]}
    return pack_zip(make_zip({
        "README.md": README,
        "api/app.py": APP,
        # Fake keys are assembled at runtime so this test file doesn't itself look like a leak.
        "config.py": "WATSONX_API_KEY = " + '"' + FAKE_IBM + '"\nOPENAI = "' + FAKE_OPENAI + '"\n',
        ".env.example": "KIMI_API_KEY=sk-ms-paste-your-key-here\n",
        ".env": "SECRET=should-never-be-sent\n",
        "node_modules/react/index.js": "module.exports = {}",
        "package-lock.json": "{}",
        "train.ipynb": json.dumps(nb),
        "data/labels.csv": "\n".join(f"img{i}.png,{i % 3}" for i in range(500)),
        "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
    }), name="team/corroscan", ref="abc1234")


def test_pack_filters_and_orders():
    pack = sample_pack()
    paths = [f.path for f in pack.files]
    assert paths[0] == "README.md"  # README first, like a juror reads
    assert "api/app.py" in paths and "train.ipynb" in paths
    skipped = dict(pack.skipped)
    assert skipped[".env"].startswith("env file")
    assert "node_modules/react/index.js" in skipped and "package-lock.json" in skipped
    assert "logo.png" in skipped
    assert "should-never-be-sent" not in pack.text


def test_notebook_outputs_dropped_and_data_truncated():
    pack = sample_pack()
    nb = pack.file("train.ipynb")
    assert "boto3.client" in nb.text and "AAAA" not in nb.text
    csv = pack.file("data/labels.csv")
    assert csv.lines <= 61 and "first 60 of 500 lines" in csv.note


def test_secrets_redacted_and_recorded():
    pack = sample_pack()
    cfg = pack.file("config.py").text
    assert FAKE_IBM not in cfg and FAKE_OPENAI not in cfg
    assert cfg.count(REDACTED) == 2
    assert {r.path for r in pack.redactions} == {"config.py"}  # .env.example placeholder left alone
    assert "sk-ms-paste-your-key-here" in pack.file(".env.example").text
    assert "likely credential(s) were committed" in pack.text


def test_locate_exact_approx_and_missing():
    pack = sample_pack()
    c = locate(pack, "api/app.py", 'return {"corrosion": "severe", "confidence": 0.97}')
    assert c.status == "exact" and c.start_line == 7
    multi = locate(pack, "./api/app.py", '@app.post("/predict")\ndef predict(image: bytes):')
    assert multi.status == "exact" and (multi.start_line, multi.end_line) == (4, 5)
    approx = locate(pack, "app.py", 'return {"corrosion": "severe", "confidence": 0.95}')
    assert approx.status == "approximate" and approx.resolved_path == "api/app.py"
    assert locate(pack, "api/app.py", "model = watsonx.load()").status == "quote_not_found"
    assert locate(pack, "src/missing.py", "x").status == "file_not_found"


def test_verify_brief_and_weighted_score():
    pack = sample_pack()
    ch = load_challenges()["haks-2026"]
    brief = {
        "claims": [{"claim": "Real-time detection with watsonx", "status": "contradicted",
                    "evidence": [{"file": "api/app.py", "quote": 'return {"corrosion": "severe", "confidence": 0.97}'},
                                 {"file": "api/app.py", "quote": "watsonx.predict(img)"}]}],
        "criteria": [{"name": c.name, "score": s} for c, s in zip(ch.criteria, [8, 2, 3, 5])],
    }
    totals = verify_brief(pack, brief)
    assert totals["total"] == 2 and totals["verified"] == 1
    # weights 30/30/20/20 -> (240 + 60 + 60 + 100) / 100
    assert weighted_score(brief, ch) == 4.6


def test_challenges_load():
    chs = load_challenges()
    assert {"haks-2026", "kimi-paris-challenge", "generic"} <= set(chs)
    assert all(c.criteria for c in chs.values())
