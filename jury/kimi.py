"""Thin wrapper around the Kimi API (OpenAI-compatible) for one-shot, whole-repo review.

Facts used here were checked on platform.kimi.ai/docs on 25 November 2026:
base URL, model IDs, prices, rate-limit tiers, fixed sampling parameters,
reasoning_effort, structured output, context caching and the token-estimate endpoint.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from .brief import BRIEF_SCHEMA, SYSTEM_PROMPT, Challenge, json_object_fallback_prompt, task_prompt
from .repo import RepoPack

BASE_URL = "https://api.moonshot.ai/v1"
CONTEXT_WINDOW = 1_048_576

# USD per million tokens (platform.kimi.ai/docs/pricing/chat, checked 2026-11-25).
# Cache writes on the default 5-minute tier cost the same as normal input.
PRICES = {
    "kimi-k3.1-pro": {"input": 2.00, "cached": 0.20, "output": 10.00},
    "kimi-k3.1-pro-highspeed": {"input": 4.00, "cached": 0.20, "output": 20.00},
    "kimi-k3": {"input": 3.00, "cached": 0.30, "output": 15.00},
}

# Tokens per minute by cumulative recharge (platform.kimi.ai/docs/pricing/limits).
# The gateway counts prompt tokens + max_completion_tokens against this limit.
TIERS = {
    "Tier0 (recharged $1–9)": 500_000,
    "Tier1 ($10+)": 2_000_000,
    "Tier2 ($20+)": 3_000_000,
}

DEFAULT_MAX_OUTPUT = 65_536  # thinking + JSON answer


class KimiError(Exception):
    pass


def api_key() -> str | None:
    return os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")


def client() -> OpenAI:
    key = api_key()
    if not key:
        raise KimiError("No API key. Copy .env.example to .env and set KIMI_API_KEY (created on platform.kimi.ai).")
    # max_retries=0: on Tier0 (3 requests/minute) the SDK's silent retries can burn the whole quota
    # on one failure, as the Kimi troubleshooting guide warns.
    return OpenAI(api_key=key, base_url=BASE_URL, max_retries=0,
                  timeout=httpx.Timeout(1800.0, connect=20.0))


def base_messages(pack: RepoPack) -> list[dict]:
    """System prompt + repository: the identical prefix that context caching reuses."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": pack.text},
    ]


def brief_messages(pack: RepoPack, ch: Challenge, lang: str) -> list[dict]:
    return base_messages(pack) + [{"role": "user", "content": task_prompt(ch, lang)}]


def count_tokens(messages: list[dict], model: str) -> int:
    """Exact prompt size from Kimi's /tokenizers/estimate-token-count endpoint."""
    key = api_key()
    if not key:
        raise KimiError("No API key")
    r = httpx.post(
        f"{BASE_URL}/tokenizers/estimate-token-count",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": messages},
        timeout=120,
    )
    if r.status_code != 200:
        raise KimiError(_describe_http(r.status_code, r.text))
    data = r.json()
    if "error" in data:
        raise KimiError(str(data["error"]))
    return int(data["data"]["total_tokens"])


def preflight(prompt_tokens: int, tier: str, max_output: int = DEFAULT_MAX_OUTPUT) -> str | None:
    """Return a blocking problem, or None if the request can go."""
    if prompt_tokens >= CONTEXT_WINDOW:
        return f"{prompt_tokens:,} tokens is more than K3.1 Pro's {CONTEXT_WINDOW:,}-token window."
    tpm = TIERS[tier]
    if prompt_tokens + max_output > tpm:
        return (f"{prompt_tokens:,} prompt + {max_output:,} output budget = {prompt_tokens + max_output:,} tokens, "
                f"above the {tpm:,} tokens/minute limit of {tier}. Recharge to reach a higher tier, or trim the repo.")
    return None


# --------------------------------------------------------------------------- usage & cost

@dataclass
class Usage:
    prompt: int = 0
    cached: int = 0
    completion: int = 0
    reasoning: int | None = None

    @classmethod
    def from_api(cls, u) -> "Usage":
        if u is None:
            return cls()
        d = u.model_dump() if hasattr(u, "model_dump") else dict(u)
        details = d.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens") or d.get("cached_tokens") or 0
        cdetails = d.get("completion_tokens_details") or {}
        return cls(
            prompt=int(d.get("prompt_tokens") or 0),
            cached=int(cached),
            completion=int(d.get("completion_tokens") or 0),
            reasoning=cdetails.get("reasoning_tokens"),
        )

    def cost(self, model: str) -> float:
        p = PRICES.get(model, PRICES["kimi-k3.1-pro"])
        fresh = max(self.prompt - self.cached, 0)
        return (fresh * p["input"] + self.cached * p["cached"] + self.completion * p["output"]) / 1_000_000


def estimate_cost(prompt_tokens: int, model: str, expected_output: int = 12_000) -> float:
    p = PRICES.get(model, PRICES["kimi-k3.1-pro"])
    return (prompt_tokens * p["input"] + expected_output * p["output"]) / 1_000_000


# --------------------------------------------------------------------------- calls

@dataclass
class BriefResult:
    brief: dict
    raw: str
    reasoning: str
    usage: Usage
    model: str
    seconds: float
    structured_output: str  # "json_schema" or "json_object"
    finish_reason: str | None = None
    extra: dict = field(default_factory=dict)


def _stream(cl: OpenAI, *, model: str, messages: list[dict], effort: str, max_output: int,
            response_format: dict | None, cache_key: str,
            on_reasoning: Callable[[str], None] | None, on_content: Callable[[str], None] | None):
    kwargs = dict(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        max_completion_tokens=max_output,
        prompt_cache_key=cache_key,
        # K3-series always thinks; effort is low | high | max. temperature/top_p are fixed
        # server-side and must not be sent.
        extra_body={"reasoning_effort": effort},
    )
    if response_format:
        kwargs["response_format"] = response_format
    content, reasoning, usage, finish = [], [], None, None
    for chunk in cl.chat.completions.create(**kwargs):
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        r = getattr(delta, "reasoning_content", None)
        if r is None and getattr(delta, "model_extra", None):
            r = delta.model_extra.get("reasoning_content")
        if r:
            reasoning.append(r)
            if on_reasoning:
                on_reasoning(r)
        if delta.content:
            content.append(delta.content)
            if on_content:
                on_content(delta.content)
        if choice.finish_reason:
            finish = choice.finish_reason
        # Some OpenAI-compatible servers put usage on the last choice instead.
        cu = getattr(choice, "usage", None) or (getattr(choice, "model_extra", None) or {}).get("usage")
        if cu and usage is None:
            usage = cu
    return "".join(content), "".join(reasoning), usage, finish


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


def run_brief(pack: RepoPack, ch: Challenge, lang: str, *, model: str = "kimi-k3.1-pro",
              effort: str = "high", max_output: int = DEFAULT_MAX_OUTPUT,
              on_reasoning: Callable[[str], None] | None = None,
              on_content: Callable[[str], None] | None = None) -> BriefResult:
    cl = client()
    messages = brief_messages(pack, ch, lang)
    cache_key = f"jury-brief:{pack.name}:{pack.ref or 'upload'}"
    mode = "json_schema"
    fmt = {"type": "json_schema",
           "json_schema": {"name": "jury_brief", "strict": True, "schema": BRIEF_SCHEMA}}
    t0 = time.time()
    try:
        try:
            raw, reasoning, usage, finish = _stream(
                cl, model=model, messages=messages, effort=effort, max_output=max_output,
                response_format=fmt, cache_key=cache_key, on_reasoning=on_reasoning, on_content=on_content)
        except BadRequestError as e:
            if "schema" not in str(e).lower() and "response_format" not in str(e).lower():
                raise
            # Fall back to plain JSON mode with the schema in the prompt.
            mode = "json_object"
            messages = messages[:-1] + [{"role": "user", "content": messages[-1]["content"] + json_object_fallback_prompt()}]
            raw, reasoning, usage, finish = _stream(
                cl, model=model, messages=messages, effort=effort, max_output=max_output,
                response_format={"type": "json_object"}, cache_key=cache_key,
                on_reasoning=on_reasoning, on_content=on_content)
    except Exception as e:  # noqa: BLE001 - turn SDK errors into something a juror can act on
        raise KimiError(describe_error(e)) from e

    if finish == "length":
        raise KimiError(f"Kimi ran out of output budget ({max_output:,} tokens, thinking included) before "
                        "finishing the brief. Lower the reasoning effort or raise the output budget.")
    try:
        brief = _parse_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise KimiError(f"Kimi's answer was not valid JSON ({e}). First 300 chars: {raw[:300]!r}") from e
    return BriefResult(brief=brief, raw=raw, reasoning=reasoning, usage=Usage.from_api(usage), model=model,
                       seconds=time.time() - t0, structured_output=mode, finish_reason=finish)


def ask(pack: RepoPack, brief_md: str, question: str, lang: str, *, model: str = "kimi-k3.1-pro",
        effort: str = "low", on_content: Callable[[str], None] | None = None) -> tuple[str, Usage, float]:
    """Follow-up question about the same repo. The system prompt + repository prefix is identical to
    the brief request, so it is served from Kimi's context cache at a tenth of the input price."""
    cl = client()
    lang_name = "French" if lang == "fr" else "English"
    messages = base_messages(pack) + [{
        "role": "user",
        "content": (f"A juror has read this brief about the repository:\n\n{brief_md}\n\n"
                    f"Their question: {question}\n\nAnswer in {lang_name}, in under 150 words, "
                    "citing file paths (and short verbatim quotes) for anything you state about the code."),
    }]
    t0 = time.time()
    try:
        text, _, usage, _ = _stream(cl, model=model, messages=messages, effort=effort, max_output=16_000,
                                    response_format=None, cache_key=f"jury-brief:{pack.name}:{pack.ref or 'upload'}",
                                    on_reasoning=None, on_content=on_content)
    except Exception as e:  # noqa: BLE001
        raise KimiError(describe_error(e)) from e
    return text, Usage.from_api(usage), time.time() - t0


# --------------------------------------------------------------------------- errors

def _describe_http(status: int, body: str) -> str:
    if status == 401:
        return ("401: the key was rejected. Check it was created on platform.kimi.ai (keys from kimi.com "
                "membership or Kimi Code don't work here), and that it hasn't expired or been disabled.")
    if status == 403:
        return "403: this IP is not on the organization's access-policy allowlist."
    if status == 429:
        if "quota" in body.lower() or "balance" in body.lower():
            return "429: balance or quota exhausted. Recharge on platform.kimi.ai."
        return ("429: rate limit. Tier0 allows 1 request at a time and 3 per minute; wait a minute "
                "or recharge to $10 for Tier1.")
    return f"HTTP {status}: {body[:300]}"


def describe_error(e: Exception) -> str:
    if isinstance(e, KimiError):
        return str(e)
    if isinstance(e, AuthenticationError):
        return _describe_http(401, str(e))
    if isinstance(e, PermissionDeniedError):
        return _describe_http(403, str(e))
    if isinstance(e, RateLimitError):
        return _describe_http(429, str(e))
    if isinstance(e, APITimeoutError):
        return "The request timed out. Try reasoning effort 'low' or 'high' instead of 'max'."
    if isinstance(e, APIConnectionError):
        return f"Could not reach {BASE_URL}: {e}"
    if isinstance(e, APIStatusError):
        return _describe_http(e.status_code, str(e))
    return f"{type(e).__name__}: {e}"
