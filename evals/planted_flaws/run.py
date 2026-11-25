"""Planted-flaw test: does Kimi catch the flaws I hid in a synthetic HAKS submission?

    python evals/planted_flaws/run.py            # one run, prints a scorecard
    python evals/planted_flaws/run.py --effort max
    python evals/planted_flaws/run.py --regrade evals/planted_flaws/results/raw-<stamp>.json

Only submission/ is sent to Kimi. answer_key.yaml stays local and is used to grade the brief.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from jury import brief_to_json, save  # noqa: E402
from jury import kimi as K  # noqa: E402
from jury.brief import load_challenges, weighted_score  # noqa: E402
from jury.citations import verify_brief  # noqa: E402
from jury.repo import load_dir  # noqa: E402
from jury.report import to_markdown  # noqa: E402

NEGATIVE = {"claims": {"partial", "not_found", "contradicted"}, "required_stack": {"superficial", "absent"}}


def findings(brief: dict) -> list[dict]:
    """Every negative statement in the brief (claims, stack, red flags), with the files it points at."""
    out = []

    def add(kind: str, text: str, item: dict, extra_files: tuple[str, ...] = ()):
        files = {e.get("file", "") for e in item.get("evidence", [])} | set(extra_files)
        quotes = " ".join(e.get("quote", "") for e in item.get("evidence", []))
        out.append({"kind": kind, "text": f"{text} {quotes}".lower(), "files": {f.lstrip('./') for f in files if f}})

    for c in brief.get("claims", []):
        if c.get("status") in NEGATIVE["claims"]:
            add("claim", f"{c.get('claim', '')} {c.get('explanation', '')}", c, (c.get("made_in", ""),))
    for s in brief.get("required_stack", []):
        if s.get("status") in NEGATIVE["required_stack"]:
            add("stack", f"{s.get('item', '')} {s.get('explanation', '')}", s)
    for f in brief.get("red_flags", []):
        add("red flag", f.get("issue", ""), f)
    # Criterion justifications are left out on purpose: they mix praise and criticism
    # ("the target is correct, but the split leaks"), so keyword matching on them is unreliable.
    return out


def matches(entry: dict, f: dict) -> bool:
    wanted = set(entry["files"])
    file_hit = bool(wanted & f["files"]) or any(p.lower() in f["text"] for p in wanted)
    return file_hit and any(k.lower() in f["text"] for k in entry["keywords"])


def grade(brief: dict, key: dict) -> tuple[int, int, list[str], list[str]]:
    fs = findings(brief)
    rows, caught = [], 0
    for flaw in key["flaws"]:
        hit = next((f for f in fs if matches(flaw, f)), None)
        caught += hit is not None
        rows.append(f"| {'✅' if hit else '❌'} | `{flaw['id']}` | {flaw['what']} | {hit['kind'] if hit else ''} |")
    control_rows, false_alarms = [], 0
    for c in key.get("controls", []):
        alarm = next((f for f in fs if matches(c, f)), None)
        false_alarms += alarm is not None
        control_rows.append(f"| {'⚠️' if alarm else '✅'} | `{c['id']}` | {c['what']} | "
                            f"{'flagged by mistake' if alarm else 'not flagged'} |")
    return caught, false_alarms, rows, control_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--effort", default="high", choices=["low", "high", "max"])
    ap.add_argument("--model", default="kimi-k3.1-pro")
    ap.add_argument("--regrade", type=Path, help="Grade a saved raw-*.json again, without calling Kimi")
    args = ap.parse_args()

    key = yaml.safe_load((HERE / "answer_key.yaml").read_text())
    ch = load_challenges()[key["challenge"]]
    pack = load_dir(str(HERE / "submission"), name="planted-flaws-submission")
    out = HERE / "results"
    out.mkdir(exist_ok=True)

    if args.regrade:
        raw = json.loads(args.regrade.read_text())
        brief, run = raw["brief"], raw["run"]
        stamp = args.regrade.stem.removeprefix("raw-")
    else:
        print(f"Packed {len(pack.files)} files, {len(pack.redactions)} secret(s) redacted. Asking {args.model}…")
        res = K.run_brief(pack, ch, "en", model=args.model, effort=args.effort)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
        brief = res.brief
        run = {"model": res.model, "effort": args.effort, "prompt": res.usage.prompt, "cached": res.usage.cached,
               "completion": res.usage.completion, "reasoning": res.usage.reasoning,
               "cost": round(res.usage.cost(res.model), 4), "seconds": round(res.seconds, 1),
               "structured_output": res.structured_output}
        # Save Kimi's answer before anything else can fail.
        (out / f"raw-{stamp}.json").write_text(json.dumps({"run": run, "brief": brief}, ensure_ascii=False, indent=2),
                                               encoding="utf-8")

    totals = verify_brief(pack, brief)
    caught, false_alarms, rows, control_rows = grade(brief, key)
    n_controls = len(key.get("controls", []))
    summary = (f"**Kimi caught {caught}/{len(key['flaws'])} planted flaws** and raised {false_alarms} false alarm(s) "
               f"on {n_controls} control(s). Citations found in the repo: {totals['verified']}/{totals['total']}. "
               f"{run['model']}, effort {run['effort']}, "
               f"{run['prompt']:,} prompt + {run['completion']:,} output tokens, "
               f"${run['cost']:.3f}, {run['seconds']:.0f}s.")
    table = "\n".join(["| | Planted flaw | What | Caught as |", "|---|---|---|---|", *rows, "",
                       "| | Control | What | Result |", "|---|---|---|---|", *control_rows])
    print("\n" + summary + "\n\n" + table)

    stats = {"model": run["model"], "effort": run["effort"], "prompt tokens": f"{run['prompt']:,}",
             "output tokens": f"{run['completion']:,}", "cost": f"${run['cost']:.3f}", "time": f"{run['seconds']:.0f}s",
             "citations": f"{totals['verified']}/{totals['total']} found in the repo"}
    md = to_markdown(brief, ch, "en", repo=pack.name, ref="", stats=stats)
    (out / f"scorecard-{stamp}.md").write_text(f"# Planted-flaw test, {stamp}\n\n{summary}\n\n{table}\n\n"
                                               f"Weighted score given: {weighted_score(brief, ch)}/10\n",
                                               encoding="utf-8")
    save(out, f"brief-{stamp}", "", md, brief_to_json(brief, **stats))
    print(f"\nSaved to {out}/scorecard-{stamp}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
