"""Probe providers/models: does a text call work, does native tool calling work, latency."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .providers import get_inspect_model, resolve

DEFAULT_PROBE_MODELS = {
    # one cheap, commonly-available model per provider (edit freely)
    "groq": "groq/llama-3.3-70b-versatile",
    "cerebras": "cerebras/llama-3.3-70b",
    "nvidia": "nvidia/meta/llama-3.3-70b-instruct",
    "openrouter": "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    "google": "google/gemini-2.5-flash",
    "github": "github/openai/gpt-4.1-mini",
    "mistral": "mistral/mistral-small-latest",
    "codestral": "codestral/codestral-latest",
    "sambanova": "sambanova/Meta-Llama-3.3-70B-Instruct",
    "huggingface": "huggingface/meta-llama/Llama-3.3-70B-Instruct",
    "cloudflare": "cloudflare/@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "ollama": "ollama/gemma2:2b",
    "fcm": "fcm/fcm",
    "litellm": "litellm/default",
    "anthropic": "anthropic/claude-haiku-4-5",
    "openai": "openai/gpt-4.1-mini",
}


def _why(e: BaseException) -> str:
    """Unwrap tenacity RetryError to the real cause (timeout, 401, 404 model not found, ...)."""
    inner = getattr(getattr(e, "last_attempt", None), "exception", lambda: None)()
    e = inner or e
    return f"{type(e).__name__}: {str(e)[:140]}"


async def _probe(spec: str, timeout: int = 45) -> dict[str, Any]:
    from inspect_ai.model import ChatMessageUser, GenerateConfig
    from inspect_ai.tool import ToolInfo, ToolParams
    from inspect_ai.util import JSONSchema
    r = resolve(spec)
    row: dict[str, Any] = {"spec": spec, "family": r.family, "text": "-", "tools": "-", "latency_s": None,
                           "served_by": None, "error": ""}
    if not r.has_key and r.provider not in ("ollama", "fcm", "litellm"):
        row["error"] = "no API key"
        return row
    # `timeout` in Inspect bounds the *retry budget*, not a single hanging request; `attempt_timeout`
    # bounds each HTTP attempt (otherwise a cold-starting endpoint can block for the SDK's 10 min).
    kw = dict(max_retries=0, timeout=timeout, max_tokens=64, temperature=0)
    if "attempt_timeout" in GenerateConfig.model_fields:
        kw["attempt_timeout"] = timeout
    cfg = GenerateConfig(**kw)
    try:
        m = get_inspect_model(r)
        t0 = time.time()
        out = await m.generate([ChatMessageUser(content="Reply with exactly: OK")], config=cfg)
        row["latency_s"] = round(time.time() - t0, 2)
        row["text"] = "ok" if "ok" in (out.completion or "").lower() else f"odd: {out.completion[:30]!r}"
        row["served_by"] = getattr(out, "model", None)
    except Exception as e:
        row["text"] = "FAIL"
        row["error"] = _why(e)
        return row
    tool = ToolInfo(name="get_time", description="Get the time in a city",
                    parameters=ToolParams(properties={"city": JSONSchema(type="string", description="city")},
                                          required=["city"]))
    try:
        out = await m.generate([ChatMessageUser(content="What time is it in Paris? Use the tool.")],
                               tools=[tool], config=cfg)
        row["tools"] = "native" if out.message.tool_calls else "json-only"
    except Exception as e:
        row["tools"] = "json-only"
        row["error"] = f"tools: {_why(e)[:100]}"
    return row


async def probe_guarded(spec: str, timeout: int) -> dict[str, Any]:
    """Hard wall-clock cap (two calls + slack) so one stuck endpoint can never block discovery."""
    try:
        return await asyncio.wait_for(_probe(spec, timeout), timeout=2 * timeout + 10)
    except (asyncio.TimeoutError, TimeoutError):
        r = resolve(spec)
        return {"spec": spec, "family": r.family, "text": "FAIL", "tools": "-", "latency_s": None,
                "served_by": None, "error": f"timed out after {2 * timeout + 10}s"}


def probe(specs: list[str], timeout: int = 45, concurrency: int = 6, progress: bool = True) -> list[dict[str, Any]]:
    async def go():
        sem = asyncio.Semaphore(concurrency)
        done = 0

        async def one(s):
            nonlocal done
            async with sem:
                r = await probe_guarded(s, timeout)
            done += 1
            if progress:
                print(f"  [{done}/{len(specs)}] {s}: text={r['text']} tools={r['tools']} "
                      f"{'' if r['latency_s'] is None else str(r['latency_s']) + 's'} {r['error'][:70]}", flush=True)
            return r
        return await asyncio.gather(*[one(s) for s in specs])
    from .agent_loop import run_sync
    return run_sync(go())
