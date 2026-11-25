"""Render a brief as Markdown (for download, the CLI, and follow-up questions)."""

from __future__ import annotations

from .brief import Challenge, weighted_score
from .citations import Citation

STATUS_ICON = {
    "verified": "✅", "partial": "🟡", "not_found": "⚪", "contradicted": "❌",
    "used": "✅", "superficial": "🟡", "absent": "❌",
    "high": "🔴", "medium": "🟠", "low": "🟡",
}
CITE_ICON = {"exact": "✓", "approximate": "≈", "file_not_found": "✗", "quote_not_found": "✗"}

LABELS = {
    "en": {
        "verdict": "Verdict", "claims": "Claims vs. code", "stack": "Required stack", "scores": "Scores",
        "flags": "Red flags", "strengths": "Strengths", "questions": "Questions for the team",
        "overall": "Weighted score", "none": "None found.", "stats": "Run", "cites": "citations checked",
        "status": {"verified": "verified", "partial": "partial", "not_found": "not found",
                   "contradicted": "contradicted", "used": "used", "superficial": "superficial",
                   "absent": "absent"},
    },
    "fr": {
        "verdict": "Verdict", "claims": "Promesses vs. code", "stack": "Stack imposée", "scores": "Notes",
        "flags": "Points d'alerte", "strengths": "Points forts", "questions": "Questions à poser à l'équipe",
        "overall": "Note pondérée", "none": "Aucun.", "stats": "Exécution", "cites": "citations vérifiées",
        "status": {"verified": "vérifié", "partial": "partiel", "not_found": "introuvable",
                   "contradicted": "contredit", "used": "utilisée", "superficial": "superficielle",
                   "absent": "absente"},
    },
}


def _cites_md(item: dict) -> str:
    cites: list[Citation] = item.get("_citations") or []
    out = []
    for c in cites:
        loc = f"{c.resolved_path or c.file}"
        if c.start_line:
            loc += f":{c.start_line}" + (f"-{c.end_line}" if c.end_line and c.end_line != c.start_line else "")
        quote = c.quote.strip().splitlines()[0][:120] if c.quote.strip() else ""
        out.append(f"  - {CITE_ICON[c.status]} `{loc}` `{quote}`")
    return "\n".join(out)


def to_markdown(brief: dict, ch: Challenge, lang: str, *, repo: str, ref: str, stats: dict | None = None) -> str:
    L = LABELS[lang]
    score = weighted_score(brief, ch)
    lines = [f"# {brief.get('project_name', repo)}",
             f"`{repo}`" + (f" @ `{ref[:7]}`" if ref else "") + f" · {ch.name}",
             "", f"> {brief.get('what_it_does', '')}", ""]
    if score is not None:
        lines.append(f"**{L['overall']}: {score}/10**\n")
    lines += [f"## {L['verdict']}", brief.get("verdict", ""), ""]

    lines.append(f"## {L['claims']}")
    for c in brief.get("claims", []):
        st = c.get("status", "")
        lines.append(f"- {STATUS_ICON.get(st, '')} **{L['status'].get(st, st)}**: {c.get('claim', '')} "
                     f"_({c.get('made_in', '')})_. {c.get('explanation', '')}")
        cm = _cites_md(c)
        if cm:
            lines.append(cm)
    lines.append("")

    if brief.get("required_stack"):
        lines.append(f"## {L['stack']}")
        for s in brief["required_stack"]:
            st = s.get("status", "")
            lines.append(f"- {STATUS_ICON.get(st, '')} **{s.get('item', '')}**: {L['status'].get(st, st)}. "
                         f"{s.get('explanation', '')}")
            cm = _cites_md(s)
            if cm:
                lines.append(cm)
        lines.append("")

    lines.append(f"## {L['scores']}")
    for c in brief.get("criteria", []):
        lines.append(f"- **{c.get('name', '')}: {c.get('score', '?')}/10**. {c.get('justification', '')}")
        cm = _cites_md(c)
        if cm:
            lines.append(cm)
    lines.append("")

    lines.append(f"## {L['flags']}")
    flags = brief.get("red_flags", [])
    if not flags:
        lines.append(L["none"])
    for f in flags:
        lines.append(f"- {STATUS_ICON.get(f.get('severity', ''), '')} {f.get('issue', '')}")
        cm = _cites_md(f)
        if cm:
            lines.append(cm)
    lines.append("")

    if brief.get("strengths"):
        lines.append(f"## {L['strengths']}")
        lines += [f"- {s}" for s in brief["strengths"]]
        lines.append("")

    lines.append(f"## {L['questions']}")
    for i, q in enumerate(brief.get("jury_questions", []), 1):
        lines.append(f"{i}. **{q.get('question', '')}**  \n   _{q.get('why', '')}_")
    lines.append("")

    if stats:
        lines.append(f"## {L['stats']}")
        lines.append(" · ".join(f"{k}: {v}" for k, v in stats.items()))
    return "\n".join(lines).strip() + "\n"
