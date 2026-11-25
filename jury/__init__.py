"""Kimi Jury Brief: whole-repo hackathon briefs with Kimi K3.1 Pro."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

from .citations import Citation


def brief_to_json(brief: dict, **meta) -> str:
    def default(o):
        if isinstance(o, Citation):
            return dataclasses.asdict(o)
        raise TypeError(type(o))

    return json.dumps({"meta": meta, "brief": brief}, ensure_ascii=False, indent=2, default=default)


def slug(name: str, ref: str = "") -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return f"{s}-{ref[:7]}" if ref else s


def save(out_dir: Path, name: str, ref: str, markdown: str, json_text: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / slug(name, ref)
    base.with_suffix(".md").write_text(markdown, encoding="utf-8")
    base.with_suffix(".json").write_text(json_text, encoding="utf-8")
    return base
