"""Check every quote Kimi cites against the real repository.

The model is asked for verbatim quotes instead of line numbers: line numbers
would cost ~25% more tokens on a big repo, and a quote can be verified. Each
citation comes back as exact, approximate or not found, so the jury knows
which evidence to trust.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .repo import RepoPack

_WS = re.compile(r"\s+")


@dataclass
class Citation:
    file: str
    quote: str
    status: str  # "exact" | "approximate" | "file_not_found" | "quote_not_found"
    resolved_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    snippet: str = ""


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _snippet(lines: list[str], start: int, end: int, pad: int = 2) -> str:
    lo, hi = max(start - pad, 1), min(end + pad, len(lines))
    width = len(str(hi))
    return "\n".join(f"{n:>{width}}  {lines[n - 1]}" for n in range(lo, hi + 1))


def locate(pack: RepoPack, file: str, quote: str) -> Citation:
    f = pack.file(file)
    if f is None:
        return Citation(file, quote, "file_not_found")
    lines = f.text.splitlines()
    normed = [_norm(line) for line in lines]
    q_lines = [_norm(q) for q in quote.splitlines() if _norm(q)]
    if not q_lines:
        return Citation(file, quote, "quote_not_found", f.path)

    # 1) exact match of consecutive (whitespace-normalised) lines, allowing a partial first/last line
    n = len(q_lines)
    for i in range(len(normed) - n + 1):
        window = normed[i:i + n]
        if n == 1:
            ok = q_lines[0] in window[0]
        else:
            ok = (window[0].endswith(q_lines[0]) and window[-1].startswith(q_lines[-1])
                  and window[1:-1] == q_lines[1:-1])
        if ok:
            return Citation(file, quote, "exact", f.path, i + 1, i + n, _snippet(lines, i + 1, i + n))

    # 2) the quote spans lines differently: search the normalised file as one string
    joined = " ".join(normed)
    target = " ".join(q_lines)
    pos = joined.find(target)
    if pos >= 0:
        def line_at(offset: int) -> int:
            acc = 0
            for idx, line in enumerate(normed):
                acc += len(line) + 1
                if offset < acc:
                    return idx + 1
            return len(normed)

        start, end = line_at(pos), line_at(pos + len(target) - 1)
        return Citation(file, quote, "exact", f.path, start, end, _snippet(lines, start, end))

    # 3) fuzzy: best single line matching the longest quoted line
    probe = max(q_lines, key=len)
    best, best_i = 0.0, -1
    for i, line in enumerate(normed):
        if not line:
            continue
        r = difflib.SequenceMatcher(None, probe, line).quick_ratio()
        if r > best - 1e-9 and r >= 0.75:
            r = difflib.SequenceMatcher(None, probe, line).ratio()
            if r > best:
                best, best_i = r, i
    if best >= 0.85:
        return Citation(file, quote, "approximate", f.path, best_i + 1, best_i + 1,
                        _snippet(lines, best_i + 1, best_i + 1))
    return Citation(file, quote, "quote_not_found", f.path)


def verify_brief(pack: RepoPack, brief: dict) -> dict:
    """Attach a `_citations` list to every evidence-bearing item and return totals."""
    totals = {"exact": 0, "approximate": 0, "file_not_found": 0, "quote_not_found": 0}
    for section in ("claims", "required_stack", "criteria", "red_flags"):
        for item in brief.get(section, []) or []:
            cites = []
            for ev in item.get("evidence", []) or []:
                c = locate(pack, str(ev.get("file", "")), str(ev.get("quote", "")))
                totals[c.status] += 1
                cites.append(c)
            item["_citations"] = cites
    total = sum(totals.values())
    totals["total"] = total
    totals["verified"] = totals["exact"] + totals["approximate"]
    return totals
