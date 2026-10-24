"""Benchmark the usable free models on the calls our agents actually make, and pick the fastest reliable one.

The discovery probe (pool.py) sends one 64-token request, which says little about speed under real prompts,
reasoning models that ramble, or rate limits. Here each candidate gets `n` realistic calls, one after another:
  * json : a market-seller style prompt that must come back as a JSON object (catches reasoning models
           that think out loud and never answer),
  * tool : a coding-agent style prompt that must come back as a tool call.
Score (lower is better) = median latency x (1 + 2 x failure rate) + 30 s per missing JSON / tool answer share.
Results are cached in .cache/model_bench.json (same TTL as the pool) and used by `auto:fastest` roles.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from .providers import REPO_ROOT, get_inspect_model, resolve

BENCH_FILE = Path(os.environ.get("CLAB_CACHE", REPO_ROOT / ".cache")) / "model_bench.json"

_SELLER_SYS = ("You are S1, a power generator selling one block of energy per hour on a wholesale double-auction "
               "exchange. Your marginal cost is $61.20 per block; you earn (price - cost) when you sell. Each hour you "
               "may post one ask (or null). Trades clear at the midpoint of a crossing bid and ask. Maximise profit.\n"
               'Reply with JSON only: {"ask": <number or null>}')
_SELLER_USER = ("Hour 4 of 15.\nRecent market:\n"
                + "\n".join(f"Hour {h}: asks {{'S1': {70 + h}, 'S2': {72 + h}, 'S3': 75.0, 'S4': 80.0, 'S5': 85.0}} | "
                            f"bids {{'B1': 63.8, 'B2': 71.9, 'B3': 67.4, 'B4': 72.3}} | trades [('S1', 'B4', {71 + h}.2)]"
                            for h in range(1, 4))
                + "\nYour last ask: 73.0")
_TOOL_USER = ("You are the implementer on a software team. The spec is in SPEC.md. Start by reading SPEC.md with "
              "the read_file tool.")


def _tools():
    from inspect_ai.tool import ToolInfo, ToolParam, ToolParams
    return [ToolInfo(name="read_file", description="Read a file from the repository.",
                     parameters=ToolParams(properties={"path": ToolParam(type="string", description="relative path")},
                                           required=["path"])),
            ToolInfo(name="done", description="Finish your turn.", parameters=ToolParams())]


async def _call(model, kind: str, timeout: float) -> tuple[float | None, bool, str]:
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig
    from ..scenarios.market.agents.llm import parse_seller_reply
    cfg = GenerateConfig(max_retries=1, timeout=int(timeout), attempt_timeout=int(timeout), temperature=0.7,
                         max_tokens=600 if kind == "json" else 400)
    t0 = time.monotonic()
    try:
        if kind == "json":
            out = await asyncio.wait_for(model.generate([ChatMessageSystem(content=_SELLER_SYS),
                                                         ChatMessageUser(content=_SELLER_USER)], config=cfg), timeout + 15)
            good = parse_seller_reply(out.completion or "") is not None
        else:
            out = await asyncio.wait_for(model.generate([ChatMessageUser(content=_TOOL_USER)], tools=_tools(),
                                                        config=cfg), timeout + 15)
            good = bool(out.message.tool_calls) or '"read_file"' in (out.completion or "")
        return time.monotonic() - t0, good, ""
    except Exception as e:  # rate limit, timeout, outage
        return None, False, f"{type(e).__name__}: {str(e)[:80]}"


async def _bench_one(spec: str, n: int, timeout: float) -> dict[str, Any]:
    r = resolve(spec)
    row: dict[str, Any] = {"spec": spec, "family": r.family, "calls": n}
    try:
        model = get_inspect_model(r)
    except Exception as e:
        return {**row, "fail_rate": 1.0, "median_s": None, "json_ok": 0.0, "tool_ok": 0.0, "score": 1e9,
                "error": f"{type(e).__name__}: {str(e)[:80]}"}
    lat, fails, json_ok, tool_ok, err = [], 0, [], [], ""
    for i in range(n):
        kind = "json" if i % 2 == 0 else "tool"
        dt, good, e = await _call(model, kind, timeout)
        if dt is None:
            fails += 1
            err = err or e
        else:
            lat.append(dt)
        (json_ok if kind == "json" else tool_ok).append(good)
    med = statistics.median(lat) if lat else None
    fr = fails / n
    jo = sum(json_ok) / max(1, len(json_ok))
    to = sum(tool_ok) / max(1, len(tool_ok))
    score = (med if med is not None else timeout) * (1 + 2 * fr) + 30 * (1 - jo) + 30 * (1 - to)
    return {**row, "fail_rate": round(fr, 2), "median_s": None if med is None else round(med, 2),
            "p90_s": round(sorted(lat)[int(0.9 * (len(lat) - 1))], 2) if lat else None,
            "json_ok": round(jo, 2), "tool_ok": round(to, 2), "score": round(score, 2), "error": err}


def bench(specs: list[str], n: int = 6, timeout: float = 60, concurrency: int = 6) -> list[dict[str, Any]]:
    """Benchmark `specs` (in parallel across models, sequential calls per model) and cache the result."""
    from .agent_loop import run_sync
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(s):
        nonlocal done
        async with sem:
            res = await _bench_one(s, n, timeout)
        done += 1
        print(f"  [{done}/{len(specs)}] {s}: median {res.get('median_s')}s, fail {res['fail_rate']:.0%}, "
              f"json {res['json_ok']:.0%}, tools {res['tool_ok']:.0%} -> score {res['score']}", flush=True)
        return res

    async def all_():
        return await asyncio.gather(*[one(s) for s in specs])
    rows = sorted(run_sync(all_()), key=lambda x: x["score"])
    BENCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    BENCH_FILE.write_text(json.dumps({"created": time.time(), "n": n, "results": rows}, indent=1), encoding="utf-8")
    return rows


def candidates_from_pool(pool: list, top: int = 8) -> list[str]:
    """Usable pool models that can serve agents (tool calls), fastest probe first; local Ollama excluded."""
    good = [c for c in pool if c.ok and c.provider != "ollama" and c.tools in ("native", "json-only", "auto")]
    good.sort(key=lambda c: (c.tools != "native", c.latency_s if c.latency_s is not None else 99))
    return [c.spec for c in good[:top]]


def cached(ttl_hours: float = 6) -> list[dict[str, Any]] | None:
    if not BENCH_FILE.exists():
        return None
    d = json.loads(BENCH_FILE.read_text(encoding="utf-8"))
    return d["results"] if time.time() - d.get("created", 0) < ttl_hours * 3600 else None


def pick_fastest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fastest model that answered reliably: no more than 1 in 3 calls failed, and it produced the JSON and
    the tool call at least 2 times in 3."""
    ok = [r for r in rows if r.get("median_s") is not None and r["fail_rate"] <= 0.34
          and r["json_ok"] >= 0.66 and r["tool_ok"] >= 0.66]
    return min(ok, key=lambda r: r["score"]) if ok else None
