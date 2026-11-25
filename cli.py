"""Brief one or more repos from the terminal.

    python cli.py https://github.com/owner/repo --challenge haks-2026 --lang fr
    python cli.py team1.zip team2.zip --challenge kimi-paris-challenge
    python cli.py https://github.com/owner/repo --dry-run   # pack + count tokens, no model call
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from jury import brief_to_json, save  # noqa: E402
from jury import kimi as K  # noqa: E402
from jury.brief import load_challenges, weighted_score  # noqa: E402
from jury.citations import verify_brief  # noqa: E402
from jury.repo import RepoError, load_github, load_zip_upload  # noqa: E402
from jury.report import to_markdown  # noqa: E402


def load(src: str):
    p = Path(src)
    if p.suffix == ".zip" and p.exists():
        return load_zip_upload(p.read_bytes(), p.name)
    return load_github(src)


def main() -> int:
    challenges = load_challenges()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repos", nargs="+", help="GitHub URLs or .zip files")
    ap.add_argument("--challenge", default="generic", choices=sorted(challenges))
    ap.add_argument("--lang", default="en", choices=["en", "fr"])
    ap.add_argument("--model", default="kimi-k3.1-pro", choices=sorted(K.PRICES))
    ap.add_argument("--effort", default="high", choices=["low", "high", "max"])
    ap.add_argument("--tier", default="Tier1 ($10+)", choices=list(K.TIERS))
    ap.add_argument("--out", default="briefs", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="Pack and count tokens only; no model call")
    args = ap.parse_args()
    ch = challenges[args.challenge]

    board = []
    for src in args.repos:
        print(f"\n=== {src}")
        try:
            pack = load(src)
        except RepoError as e:
            print(f"  ! {e}")
            continue
        print(f"  {len(pack.files)} files packed, {len(pack.skipped)} skipped, "
              f"{len(pack.redactions)} secret(s) redacted, {pack.chars:,} chars (~{pack.approx_tokens:,} tokens)")
        messages = K.brief_messages(pack, ch, args.lang)
        try:
            tokens = K.count_tokens(messages, args.model)
            print(f"  exact prompt size: {tokens:,} tokens "
                  f"({tokens / K.CONTEXT_WINDOW:.0%} of the 1M window), est. cost ${K.estimate_cost(tokens, args.model):.2f}")
        except K.KimiError as e:
            tokens = pack.approx_tokens
            print(f"  (token count unavailable: {e})")
        if args.dry_run:
            continue
        problem = K.preflight(tokens, args.tier)
        if problem:
            print(f"  ! {problem}")
            continue

        n = {"r": 0}

        def on_reasoning(t: str) -> None:
            n["r"] += len(t)
            if n["r"] % 2000 < len(t):
                print(f"\r  thinking… {n['r']:,} chars", end="", flush=True)

        try:
            res = K.run_brief(pack, ch, args.lang, model=args.model, effort=args.effort, on_reasoning=on_reasoning)
        except K.KimiError as e:
            print(f"\n  ! {e}")
            continue
        print()
        totals = verify_brief(pack, res.brief)
        cost = res.usage.cost(res.model)
        stats = {"model": res.model, "effort": args.effort, "prompt tokens": f"{res.usage.prompt:,}",
                 "cached": f"{res.usage.cached:,}", "output tokens": f"{res.usage.completion:,}",
                 "cost": f"${cost:.3f}", "time": f"{res.seconds:.0f}s",
                 "citations": f"{totals['verified']}/{totals['total']} found in the repo"}
        md = to_markdown(res.brief, ch, args.lang, repo=pack.name, ref=pack.ref, stats=stats)
        base = save(args.out, pack.name, pack.ref, md,
                    brief_to_json(res.brief, repo=pack.name, ref=pack.ref, challenge=ch.id, lang=args.lang, **stats))
        score = weighted_score(res.brief, ch)
        print(f"  score {score}/10 · citations {totals['verified']}/{totals['total']} · ${cost:.3f} · {res.seconds:.0f}s")
        print(f"  -> {base}.md")
        board.append((score or 0, pack.name, cost))

    if len(board) > 1:
        print("\nLeaderboard")
        for score, name, cost in sorted(board, reverse=True):
            print(f"  {score:>4}  {name}  (${cost:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
