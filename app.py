"""Kimi Jury Brief: Streamlit app.

    streamlit run app.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from jury import brief_to_json, save  # noqa: E402
from jury import kimi as K  # noqa: E402
from jury.brief import load_challenges, weighted_score  # noqa: E402
from jury.citations import Citation, verify_brief  # noqa: E402
from jury.repo import RepoError, RepoPack, load_dir, load_github, load_zip_upload  # noqa: E402
from jury.report import LABELS, STATUS_ICON, to_markdown  # noqa: E402

st.set_page_config(page_title="Kimi Jury Brief", page_icon="⚖️", layout="wide")

CHALLENGES = load_challenges()
SMALL_CONTEXT = 128_000
OUT_DIR = Path(__file__).parent / "briefs"
SAMPLE_DIR = Path(__file__).parent / "evals" / "planted_flaws"

ss = st.session_state
ss.setdefault("pack", None)
ss.setdefault("result", None)
ss.setdefault("board", [])
ss.setdefault("qa", [])

# --------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    ch_id = st.selectbox("Challenge", list(CHALLENGES), index=list(CHALLENGES).index("haks-2026")
                         if "haks-2026" in CHALLENGES else 0, format_func=lambda k: CHALLENGES[k].name)
    ch = CHALLENGES[ch_id]
    lang = st.radio("Brief language", ["en", "fr"], horizontal=True,
                    format_func=lambda x: {"en": "English", "fr": "Français"}[x])
    model = st.selectbox("Model", list(K.PRICES), index=0)
    effort = st.select_slider("Reasoning effort", ["low", "high", "max"], value="high",
                              help="K3.1 Pro always thinks. 'max' is the API default; 'high' is faster and cheaper.")
    keep_cached = st.toggle("Keep the repo cached for 1 hour", value=True,
                            help="A brief takes several minutes, longer than Kimi's default 5-minute cache. A 1-hour "
                                 "cache write costs 2x input once, then every follow-up question reads the repo at "
                                 "a tenth of the input price.")
    tier = st.selectbox("Your account tier", list(K.TIERS), index=1,
                        help="Tiers depend on cumulative recharge. The gateway counts prompt + output budget "
                             "against your tokens-per-minute limit.")
    p = K.PRICES[model]
    st.caption(f"**{model}**: ${p['input']:.2f} in / ${p['output']:.2f} out per M tokens, "
               f"cached input ${p['cached']:.2f}. 1,048,576-token window.")
    st.caption("🔑 API key loaded" if K.api_key() else "🔑 **No API key**: add KIMI_API_KEY to .env")
    with st.expander("Challenge details"):
        st.markdown(f"**{ch.event}**\n\n{ch.brief}")
        if ch.required_stack:
            st.markdown("**Required stack**\n" + "\n".join(f"- {s}" for s in ch.required_stack))
        st.markdown("**Criteria**\n" + "\n".join(f"- {c.name} ({c.weight:g})" for c in ch.criteria))

L = LABELS[lang]

# --------------------------------------------------------------------------- header
st.title("⚖️ Kimi Jury Brief")
st.markdown("Kimi K3.1 Pro reads **an entire hackathon repository in one request** and gives the jury a brief: "
            "which claims the code backs up, whether the required stack is really used, scores with "
            "evidence, and three questions to ask the team. Every quote it cites is checked against the repo.")

tab_brief, tab_board, tab_how = st.tabs(["Brief a repo", "Leaderboard", "How it works"])


# --------------------------------------------------------------------------- helpers
def render_citations(item: dict) -> None:
    cites: list[Citation] = item.get("_citations") or []
    for c in cites:
        if c.status in ("exact", "approximate"):
            badge = "✓ found in repo" if c.status == "exact" else "≈ close match"
            loc = f"{c.resolved_path}:{c.start_line}" + (f"-{c.end_line}" if c.end_line != c.start_line else "")
            st.caption(f"{badge} · `{loc}`")
            st.code(c.snippet, language=None)
        else:
            st.caption(f"✗ not found in repo ({c.status.replace('_', ' ')}) · `{c.file}`")
            st.code(c.quote, language=None)


def evidence_expander(item: dict, label: str = "Evidence") -> None:
    cites = item.get("_citations") or []
    if cites:
        ok = sum(c.status in ("exact", "approximate") for c in cites)
        with st.expander(f"{label} ({ok}/{len(cites)} verified)"):
            render_citations(item)


def render_brief(res: dict) -> None:
    brief, pack, chx, lg = res["brief"], res["pack"], res["challenge"], res["lang"]
    Lx = LABELS[lg]
    totals, usage = res["totals"], res["usage"]
    score = weighted_score(brief, chx)
    claims = brief.get("claims", [])
    n_ver = sum(c.get("status") == "verified" for c in claims)

    st.subheader(brief.get("project_name") or pack.name)
    st.caption(f"`{pack.name}`" + (f" @ `{pack.ref[:7]}`" if pack.ref else "") + f" · {chx.name}")
    st.markdown(f"> {brief.get('what_it_does', '')}")

    m = st.columns(5)
    m[0].metric(Lx["overall"], f"{score}/10" if score is not None else "n/a")
    m[1].metric("Claims backed by code", f"{n_ver}/{len(claims)}")
    m[2].metric("Citations found in repo", f"{totals['verified']}/{totals['total']}")
    m[3].metric("Cost of this brief", f"${usage.cost(res['model']):.3f}")
    m[4].metric("Time", f"{res['seconds']:.0f}s")

    st.info(f"**{Lx['verdict']}**: {brief.get('verdict', '')}")

    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"#### {Lx['claims']}")
        for c in claims:
            stt = c.get("status", "")
            st.markdown(f"{STATUS_ICON.get(stt, '')} **{Lx['status'].get(stt, stt)}**: {c.get('claim', '')}  \n"
                        f"<small>{c.get('explanation', '')} _({c.get('made_in', '')})_</small>",
                        unsafe_allow_html=True)
            evidence_expander(c)
        if brief.get("required_stack"):
            st.markdown(f"#### {Lx['stack']}")
            for s in brief["required_stack"]:
                stt = s.get("status", "")
                st.markdown(f"{STATUS_ICON.get(stt, '')} **{s.get('item', '')}**: {Lx['status'].get(stt, stt)}  \n"
                            f"<small>{s.get('explanation', '')}</small>", unsafe_allow_html=True)
                evidence_expander(s)
        st.markdown(f"#### {Lx['flags']}")
        if not brief.get("red_flags"):
            st.caption(Lx["none"])
        for f in brief.get("red_flags", []):
            st.markdown(f"{STATUS_ICON.get(f.get('severity', ''), '')} {f.get('issue', '')}")
            evidence_expander(f)

    with right:
        st.markdown(f"#### {Lx['questions']}")
        for i, q in enumerate(brief.get("jury_questions", []), 1):
            st.markdown(f"**{i}. {q.get('question', '')}**  \n<small>{q.get('why', '')}</small>",
                        unsafe_allow_html=True)
        st.markdown(f"#### {Lx['scores']}")
        for c in brief.get("criteria", []):
            sc = max(0, min(10, int(c.get("score", 0))))
            st.markdown(f"**{c.get('name', '')}**: {sc}/10")
            st.progress(sc / 10)
            st.caption(c.get("justification", ""))
            evidence_expander(c)
        if brief.get("strengths"):
            st.markdown(f"#### {Lx['strengths']}")
            st.markdown("\n".join(f"- {s}" for s in brief["strengths"]))

    reasoning_tokens = f" ({usage.reasoning:,} thinking)" if usage.reasoning else ""
    st.caption(f"{res['model']} · effort {res['effort']} · structured output: {res['mode']} · "
               f"prompt {usage.prompt:,} tokens ({usage.cached:,} cached) · output {usage.completion:,}"
               f"{reasoning_tokens} · {len(pack.files)} files in one request")
    d1, d2 = st.columns(2)
    d1.download_button("Download brief (.md)", res["markdown"], file_name=f"{pack.name.replace('/', '_')}-brief.md")
    d2.download_button("Download brief (.json)", res["json"], file_name=f"{pack.name.replace('/', '_')}-brief.json")


# --------------------------------------------------------------------------- tab: brief
with tab_brief:
    c1, c2 = st.columns([3, 2])
    url = c1.text_input("Public GitHub repository", placeholder="https://github.com/team/project")
    upload = c2.file_uploader("…or a .zip of the submission", type=["zip"])
    if st.button("1 · Load repository", type="secondary"):
        try:
            with st.spinner("Downloading and packing…"):
                if upload is not None:
                    ss.pack = load_zip_upload(upload.getvalue(), upload.name)
                elif url.strip():
                    ss.pack = load_github(url)
                else:
                    st.warning("Paste a GitHub URL or upload a .zip.")
                    ss.pack = None
            ss.result, ss.qa = None, []
            ss.pop("exact_tokens", None)
        except RepoError as e:
            st.error(str(e))

    sample_runs = sorted(SAMPLE_DIR.glob("results/raw-*.json"))
    if sample_runs and st.button("…or see a sample brief (replayed, no API key or cost)", type="tertiary"):
        # Replays a saved Kimi answer on the synthetic planted-flaw submission in evals/.
        raw = json.loads(sample_runs[-1].read_text(encoding="utf-8"))
        run = raw["run"]
        sch = CHALLENGES["haks-2026"]
        spack = load_dir(str(SAMPLE_DIR / "submission"), name="planted-flaws-submission (synthetic)")
        sbrief = raw["brief"]
        stotals = verify_brief(spack, sbrief)
        susage = K.Usage(prompt=run["prompt"], cached=run["cached"], completion=run["completion"],
                         reasoning=run.get("reasoning"))
        smd = to_markdown(sbrief, sch, "en", repo=spack.name, ref="")
        ss.pack, ss.qa, ss.result = spack, [], {
            "brief": sbrief, "pack": spack, "challenge": sch, "lang": "en", "model": run["model"],
            "effort": run["effort"], "usage": susage, "seconds": run["seconds"], "totals": stotals,
            "mode": run.get("structured_output", "json_schema"), "markdown": smd,
            "json": brief_to_json(sbrief, replay_of=sample_runs[-1].name), "replay": True}
        st.caption("Sample: a synthetic HAKS 2026 submission with 7 planted flaws (see evals/planted_flaws). "
                   "This is Kimi's saved answer, re-checked against the repo now.")

    pack: RepoPack | None = ss.pack
    if pack:
        tokens = ss.get("exact_tokens") or pack.approx_tokens
        exact = "exact_tokens" in ss
        m = st.columns(4)
        m[0].metric("Files sent", len(pack.files))
        m[1].metric("Files skipped", len(pack.skipped))
        m[2].metric("Secrets redacted", len(pack.redactions))
        m[3].metric("Tokens" + ("" if exact else " (est.)"), f"{tokens / 1000:,.0f}k", help=f"{tokens:,} tokens")
        st.progress(min(tokens / K.CONTEXT_WINDOW, 1.0),
                    text=f"{tokens / K.CONTEXT_WINDOW:.0%} of K3.1 Pro's 1,048,576-token window, in one request")
        if tokens > SMALL_CONTEXT:
            st.caption(f"A 128k-context model would need at least {-(-tokens // SMALL_CONTEXT)} separate calls, "
                       "and no single call would see how the README, the UI and the backend connect.")
        with st.expander("Files"):
            fc1, fc2 = st.columns(2)
            fc1.markdown("**Sent to Kimi**\n" + "\n".join(f"- `{f.path}`" + (f" _{f.note}_" if f.note else "")
                                                         for f in pack.files[:400]))
            fc2.markdown("**Skipped**\n" + "\n".join(f"- `{p}`: {r}" for p, r in pack.skipped[:400]))
            if pack.redactions:
                st.warning("Redacted before sending: " + ", ".join(
                    f"`{r.path}:{r.line}` ({r.kind})" for r in pack.redactions))

        est = K.estimate_cost(tokens, model)
        if st.button(f"2 · Brief the jury with {model} (≈ ${est:.2f})", type="primary",
                     disabled=not K.api_key()):
            messages = K.brief_messages(pack, ch, lang)
            try:
                with st.spinner("Counting tokens with Kimi's tokenizer…"):
                    ss.exact_tokens = tokens = K.count_tokens(messages, model)
            except K.KimiError as e:
                st.caption(f"Exact token count unavailable ({e}); using the estimate.")
            problem = K.preflight(tokens, tier)
            if problem:
                st.error(problem)
            else:
                status = st.status(f"Kimi is reading {len(pack.files)} files ({tokens:,} tokens)…", expanded=True)
                counter = status.empty()
                think_box = status.empty()
                buf = {"r": [], "c": 0, "t": time.time(), "last": 0.0}

                def on_reasoning(t: str) -> None:
                    buf["r"].append(t)
                    now = time.time()
                    if now - buf["last"] > 0.4:
                        buf["last"] = now
                        text = "".join(buf["r"])
                        counter.caption(f"Thinking… {len(text):,} characters · {now - buf['t']:.0f}s")
                        think_box.code(text[-1500:], language=None, wrap_lines=True)

                def on_content(t: str) -> None:
                    buf["c"] += len(t)
                    now = time.time()
                    if now - buf["last"] > 0.4:
                        buf["last"] = now
                        counter.caption(f"Writing the brief… {buf['c']:,} characters · {now - buf['t']:.0f}s")

                try:
                    res = K.run_brief(pack, ch, lang, model=model, effort=effort,
                                      cache_ttl="1h" if keep_cached else "5m",
                                      on_reasoning=on_reasoning, on_content=on_content)
                    status.update(label=f"Done in {res.seconds:.0f}s", state="complete", expanded=False)
                    totals = verify_brief(pack, res.brief)
                    cost = res.usage.cost(model)
                    stats = {"model": model, "effort": effort, "prompt tokens": f"{res.usage.prompt:,}",
                             "cached": f"{res.usage.cached:,}", "output tokens": f"{res.usage.completion:,}",
                             "cost": f"${cost:.3f}", "time": f"{res.seconds:.0f}s",
                             "citations": f"{totals['verified']}/{totals['total']} found in the repo"}
                    md = to_markdown(res.brief, ch, lang, repo=pack.name, ref=pack.ref, stats=stats)
                    js = brief_to_json(res.brief, repo=pack.name, ref=pack.ref, challenge=ch.id, lang=lang, **stats)
                    save(OUT_DIR, pack.name, pack.ref, md, js)
                    ss.result = {"brief": res.brief, "pack": pack, "challenge": ch, "lang": lang, "model": model,
                                 "effort": effort, "usage": res.usage, "seconds": res.seconds, "totals": totals,
                                 "mode": res.structured_output, "markdown": md, "json": js}
                    ss.qa = []
                    row = {"Repo": pack.name, "Project": res.brief.get("project_name", ""), "Challenge": ch.name,
                           "Score": weighted_score(res.brief, ch)}
                    for i, crit in enumerate(res.brief.get("criteria", [])):
                        name = ch.criteria[i].name if i < len(ch.criteria) else crit.get("name", f"C{i + 1}")
                        row[name] = crit.get("score")
                    claims = res.brief.get("claims", [])
                    row["Claims verified"] = f"{sum(c.get('status') == 'verified' for c in claims)}/{len(claims)}"
                    row["High red flags"] = sum(f.get("severity") == "high" for f in res.brief.get("red_flags", []))
                    row["Cost ($)"] = round(cost, 3)
                    ss.board = [r for r in ss.board if not (r["Repo"] == pack.name and r["Challenge"] == ch.name)]
                    ss.board.append(row)
                except K.KimiError as e:
                    status.update(label="Failed", state="error")
                    st.error(str(e))

    if ss.result and ss.result["pack"] is pack:
        st.divider()
        render_brief(ss.result)

        st.divider()
        st.markdown("#### Ask Kimi about this repo")
        ttl_text = "1 hour" if ss.result["usage"].cache_ttl == "1h" else "5 minutes"
        st.caption("Follow-ups reuse the same repository prefix, so Kimi serves it from its context cache "
                   f"at ${K.PRICES[model]['cached']:.2f} instead of ${K.PRICES[model]['input']:.2f} per million "
                   f"input tokens (cache kept for {ttl_text} after the last call).")
        for q, a, u, secs in ss.qa:
            st.markdown(f"**Q: {q}**")
            st.markdown(a)
            st.caption(f"{u.cached:,} of {u.prompt:,} prompt tokens from cache · ${u.cost(model):.3f} · {secs:.0f}s")
        with st.form("ask", clear_on_submit=True):
            q = st.text_input("Question", placeholder="Where exactly is the model called, and on what data?")
            if st.form_submit_button("Ask") and q.strip():
                out = st.empty()
                acc = []

                def on_answer(t: str) -> None:
                    acc.append(t)
                    out.markdown("".join(acc))

                try:
                    with st.spinner("Kimi is answering from the cached repo…"):
                        ans, u, secs = K.ask(pack, ss.result["markdown"], q, ss.result["lang"], model=model,
                                             on_content=on_answer)
                    ss.qa.append((q, ans, u, secs))
                    st.rerun()
                except K.KimiError as e:
                    st.error(str(e))

# --------------------------------------------------------------------------- tab: leaderboard
with tab_board:
    if not ss.board:
        st.caption("Brief several repos with the same challenge to compare teams here.")
    else:
        df = pd.DataFrame(ss.board).sort_values("Score", ascending=False)
        st.dataframe(df, hide_index=True)
        st.download_button("Download leaderboard (.csv)", df.to_csv(index=False), file_name="leaderboard.csv")
        st.caption("Scores help the jury order its reading. The jury decides.")

# --------------------------------------------------------------------------- tab: how
with tab_how:
    st.markdown(Path(__file__).with_name("HOW_IT_WORKS.md").read_text(encoding="utf-8"))
