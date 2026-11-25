# ⚖️ Kimi Jury Brief

**Kimi K3.1 Pro reads an entire hackathon repository in one request and tells the jury what's real, what's only claimed, and what to ask the team.**

<!-- Add after recording: ![demo](docs/demo.gif)  ·  [60-second demo video](https://...) -->

| What the jury gets | Why it needs Kimi K3.1 Pro |
|---|---|
| **Claims vs. code**: each promise in the README checked against the code path | The whole repo (often 100k–500k tokens) fits in **one** 1M-token request |
| **Sponsor stack check**: is the required tech really called, or just listed? | Structured output (JSON Schema) for a brief that's always complete |
| **Scores per criterion**, each with quoted evidence | Context caching: follow-up questions cost **$0.20 instead of $2.00** per M input tokens |
| **Three questions** to ask the team on stage, in **English or French** | Reasoning effort control (`low` / `high` / `max`) to trade depth against time |

## Why I built this

I co-organised **HAKS 2026** (Télécom Paris, June 2026) as corporate relations lead: 150 students in teams of 5, a live Airbus use case on aircraft corrosion, built with IBM and AWS tools. Every hackathon jury has the same problem. Jurors get a few minutes per team, the demo is polished, and nobody has time to open the code. They can't tell a working pipeline from a well-designed slide in front of a hard-coded `return {"corrosion": "severe"}`. Sponsors ask a second question the jury can't answer either: did this team actually use our stack?

Both questions need **the whole repository at once**: the README's promise, the UI button, the API route and the function that does (or fakes) the work. That's what Kimi K3.1 Pro's 1M-token context makes possible in a single call, with no chunking and no retrieval pipeline that finds the `import watsonx` line and stops looking.

It's also the tool I'd bring to a **Kimi track at a Paris student hackathon**. The `kimi-paris-challenge` preset checks that each entry really calls the Kimi API on its main code path.

## What it looks like

<!-- Replace with a real screenshot after your first run: docs/brief.png -->
A brief has: a verdict · claims marked ✅ verified / 🟡 partial / ⚪ not found / ❌ contradicted · required stack marked used / superficial / absent · weighted score per criterion · red flags (hard-coded outputs, committed secrets, prompt injection aimed at AI judges) · 3 questions for the team · run cost and token counts.

Every piece of evidence is a **verbatim quote** that the app looks up in the repository and marks **✓ found** (with line numbers), **≈ close** or **✗ not found**. The jury can see exactly which citations to trust.

## Results on real repositories

<!-- Fill from real runs: `python cli.py <url> --challenge ...` prints every number below. -->
| Repository | Files | Prompt tokens | Time | Cost | Citations found |
|---|---|---|---|---|---|
| _to fill after the first runs_ | | | | | |

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your platform.kimi.ai key after KIMI_API_KEY=
streamlit run app.py        # http://localhost:8501
```

Command line, for several teams at once:

```bash
python cli.py https://github.com/team1/repo https://github.com/team2/repo --challenge haks-2026 --lang fr
python cli.py https://github.com/team/repo --dry-run     # pack + exact token count, no model call
```

Challenges are YAML files in [`challenges/`](challenges): brief, required stack, weighted criteria with rubrics. Copy one to run your own event.

## How it works

1. **Pack** ([`jury/repo.py`](jury/repo.py)): download the GitHub archive (pinned to the commit SHA), drop dependencies, lock files, binaries and notebook outputs, keep the first 60 lines of data files, put the README first, and redact credentials. `.env` files are never read.
2. **Count** with Kimi's `/tokenizers/estimate-token-count` endpoint, then check the request against the window and the account's rate-limit tier before spending anything.
3. **Brief** ([`jury/kimi.py`](jury/kimi.py), [`jury/brief.py`](jury/brief.py)): one streamed `kimi-k3.1-pro` call with a strict JSON Schema. The system prompt and repository go first, so the prefix is cacheable (`prompt_cache_key` = repo + commit).
4. **Verify** ([`jury/citations.py`](jury/citations.py)): every quote is located in the repo, so the evidence can be checked.
5. **Ask**: follow-up questions reuse the cached repository prefix.

Costs at list price ($2 / $10 per M input / output tokens): a 200k-token repo costs about $0.40 of input plus the output. Follow-ups on the same repo are billed at the cached rate.

## Privacy and safety

- Public repositories only, or submissions whose teams agreed. Kimi's platform privacy policy allows inputs to be used to improve its models.
- Credentials are redacted before sending and reported to the jury. Repository text is treated as untrusted: instructions aimed at an "AI judge" are ignored and flagged.
- Kimi doesn't pick winners. The brief tells a human jury where to look.

## Next

- **Batch mode** for a whole hackathon overnight: Kimi's Batch API runs `kimi-k3.1-pro` at 60% of the standard price.
- **GitHub Action** for organisers: brief every submission when the deadline closes.
- **Friction log**: what a developer in France runs into when getting started with the Kimi API, in [FRICTION_LOG.md](FRICTION_LOG.md).

---
Built by Charles Husson with Kimi K3.1 Pro on platform.kimi.ai, November 2026.
