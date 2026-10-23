"""Dynamic model pool: use *whatever free model is available* for the API keys you
configured in free-coding-models (FCM), then fall back to the FCM router, local
Ollama and any other keyed provider.

Startup pipeline (`clab pool discover`, or automatically for profiles using `auto:` specs):

  1. keys     - read FCM's config (~/.free-coding-models.json or a copy next to the repo):
                `apiKeys: {provider: key}`; export them as the env vars our registry uses
                (no need to duplicate keys in .env).
  2. discover - candidates from (a) FCM router sets in that config, (b) each keyed provider's
                live `/models` catalogue (OpenRouter: `:free` / zero-price only),
                (c) `free-coding-models --json` if the CLI is on PATH, (d) local Ollama tags.
  3. probe    - one tiny text call + one tool-call probe per candidate (concurrently, capped);
                results cached in .cache/model_pool.json (TTL).
  4. assign   - per role: a ranked fallback chain; agent roles get different families where
                possible; the trusted monitor gets a model from a family that NO agent chain
                uses; tails: FCM router (fcm/fcm) and local Ollama models.

Agents call models *directly at the provider* (with the FCM keys) so the served model is known
and pinned; the FCM router is only a last resort (it injects its own pre-prompt and picks models
dynamically, which matters for an experiment).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .providers import REPO_ROOT, family, registry, resolve

CACHE_FILE = Path(os.environ.get("CLAB_CACHE", REPO_ROOT / ".cache")) / "model_pool.json"

# FCM provider keys -> our registry names (identity when equal)
FCM_TO_REGISTRY = {"googleai": "google", "google-ai-studio": "google", "gemini": "google", "nim": "nvidia",
                   "github-models": "github", "hf": "huggingface", "ovhcloud": "ovh", "alibaba": "dashscope",
                   "ollama-cloud": "ollama_cloud", "cloudflare-workers-ai": "cloudflare", "mistral-codestral": "codestral"}
NON_CHAT = re.compile(r"embed|whisper|tts|speech|audio|transcri|guard|moderation|rerank|safety|clip|"
                      r"flux|stable-diffusion|sdxl|image-gen|dall-e|ocr|reward|retriever|parse|nv-embed|bge|e5-", re.I)
CODER = re.compile(r"coder|code|devstral|codestral|swe|qwen3|gpt-oss|kimi|deepseek|glm|nemotron", re.I)


# --------------------------------------------------------------------------- FCM config
def fcm_config_path() -> Path | None:
    cands = [os.environ.get("FCM_CONFIG", ""), str(Path.home() / ".free-coding-models.json"),
             str(REPO_ROOT.parent / ".free-coding-models.json"), str(REPO_ROOT / ".free-coding-models.json"),
             str(Path.home() / ".free-coding-models" / "config.json")]
    for c in cands:
        if c and Path(c).exists():
            return Path(c)
    return None


def load_fcm_config() -> dict[str, Any]:
    p = fcm_config_path()
    return json.loads(p.read_text(encoding="utf-8")) if p else {}


def fcm_keys(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """{registry_provider: key} from FCM `apiKeys` (strings or {key|apiKey|token} objects)."""
    cfg = cfg if cfg is not None else load_fcm_config()
    out = {}
    for prov, v in (cfg.get("apiKeys") or {}).items():
        key = v if isinstance(v, str) else next((v.get(k) for k in ("key", "apiKey", "api_key", "token")
                                                 if isinstance(v, dict) and v.get(k)), None)
        if key:
            out[FCM_TO_REGISTRY.get(prov.lower(), prov.lower())] = key
    return out


def inject_fcm_keys(verbose: bool = False) -> dict[str, str]:
    """Export FCM keys as the env vars our registry reads (never overrides existing env)."""
    reg = registry()["providers"]
    applied = {}
    for prov, key in fcm_keys().items():
        envs = reg.get(prov, {}).get("api_key_env", [])
        if envs and not any(os.environ.get(e) for e in envs):
            os.environ[envs[0]] = key
            applied[prov] = envs[0]
    if verbose and applied:
        print("FCM keys applied:", ", ".join(f"{p}->{e}" for p, e in applied.items()))
    return applied


def fcm_router_sets(cfg: dict[str, Any] | None = None) -> dict[str, list[dict]]:
    cfg = cfg if cfg is not None else load_fcm_config()
    return {n: s.get("models", []) for n, s in ((cfg.get("router") or {}).get("sets") or {}).items()}


# --------------------------------------------------------------------------- discovery
@dataclass
class Candidate:
    spec: str
    provider: str
    model: str
    family: str
    source: str
    fcm_priority: int | None = None
    ok: bool | None = None
    tools: str = "?"
    latency_s: float | None = None
    error: str = ""
    score: float = 0.0
    size_b: float | None = None


def _http_json(url: str, key: str | None, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _size(model: str) -> float | None:
    m = re.findall(r"(\d+(?:\.\d+)?)\s*b(?![a-z])", model.lower())
    return max(float(x) for x in m) if m else None


def provider_catalog(provider: str) -> list[str]:
    r = resolve(f"{provider}/x")
    if not r.base_url or not r.has_key:
        return []
    try:
        data = _http_json(r.base_url.rstrip("/") + "/models", r.api_key)
    except Exception:
        return []
    items = data.get("data", data) if isinstance(data, dict) else data
    ids = []
    for it in items if isinstance(items, list) else []:
        mid = it.get("id") if isinstance(it, dict) else (it if isinstance(it, str) else None)
        if not mid or NON_CHAT.search(mid):
            continue
        if provider == "openrouter":   # free only
            pr = (it.get("pricing") or {}) if isinstance(it, dict) else {}
            if not (mid.endswith(":free") or (str(pr.get("prompt")) in ("0", "0.0") and str(pr.get("completion")) in ("0", "0.0"))):
                continue
            if isinstance(it, dict) and it.get("supported_parameters") and "tools" not in it["supported_parameters"]:
                continue
        ids.append(mid)
    return ids


def fcm_cli_models() -> list[tuple[str, str, str]]:
    """(provider, model, tier) from `free-coding-models --json` (best effort, schema not documented)."""
    exe = shutil.which("free-coding-models")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--json"], capture_output=True, text=True, timeout=120,
                             encoding="utf-8", errors="replace").stdout
        data = json.loads(out[out.index("["):]) if "[" in out else []
    except Exception:
        return []
    res = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        prov = next((d[k] for k in ("providerKey", "provider", "origin", "source") if isinstance(d.get(k), str)), None)
        mid = next((d[k] for k in ("modelId", "model", "id") if isinstance(d.get(k), str)), None)
        status = str(d.get("status", d.get("up", "up"))).lower()
        if prov and mid and status not in ("down", "false", "error", "auth"):
            res.append((FCM_TO_REGISTRY.get(prov.lower(), prov.lower()), mid, str(d.get("tier", ""))))
    return res


def ollama_models() -> list[str]:
    base = resolve("ollama/x").base_url or "http://localhost:11434/v1"
    root = re.sub(r"/v1/?$", "", base)
    try:
        return [m["name"] for m in _http_json(root + "/api/tags", None, timeout=4).get("models", [])]
    except Exception:
        return []


def fcm_router_up() -> bool:
    base = resolve("fcm/fcm").base_url or "http://localhost:19280/v1"
    try:
        return _http_json(re.sub(r"/v1/?$", "", base) + "/health", None, timeout=3) is not None
    except Exception:
        return False


def gather_candidates(sources: list[str]) -> list[Candidate]:
    reg = registry()["providers"]
    # only providers for which a real key is configured (FCM config or env), not built-in placeholders
    keyed = [p for p, cfg in reg.items() if p not in ("ollama", "fcm", "litellm", "custom", "mockllm")
             and any(os.environ.get(e) for e in cfg.get("api_key_env", []))]
    seen: dict[str, Candidate] = {}

    def add(provider: str, model: str, source: str, prio: int | None = None):
        if provider not in reg or (provider not in ("ollama",) and provider not in keyed):
            return
        spec = f"{provider}/{model}"
        if spec not in seen:
            seen[spec] = Candidate(spec, provider, model, family(model), source, prio, size_b=_size(model))
        elif prio is not None and seen[spec].fcm_priority is None:
            seen[spec].fcm_priority = prio
    if "fcm_sets" in sources:
        for sname, models in fcm_router_sets().items():
            for m in models:
                add(FCM_TO_REGISTRY.get(m["provider"].lower(), m["provider"].lower()), m["model"],
                    f"fcm-set:{sname}", m.get("priority"))
    if "fcm_cli" in sources:
        for p, m, _tier in fcm_cli_models():
            add(p, m, "fcm-cli")
    if "provider_catalogs" in sources:
        for p in keyed:
            for m in provider_catalog(p):
                add(p, m, "catalog")
    if "ollama" in sources:
        for m in ollama_models():
            add("ollama", m, "ollama")
    return list(seen.values())


# --------------------------------------------------------------------------- probe + rank
def prerank(c: Candidate) -> float:
    s = 0.0
    if c.fcm_priority is not None:
        s += 3 - 0.2 * c.fcm_priority
    if c.size_b:
        s += min(3.0, math.log10(max(c.size_b, 1)) * 1.2)
    if CODER.search(c.model):
        s += 1.0
    if c.provider == "ollama":
        s -= 2.0                    # local small models are a fallback tier
    return s


async def _probe_all(cands: list[Candidate], concurrency: int, timeout: int) -> None:
    from .probe import probe_guarded
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(c: Candidate):
        nonlocal done
        async with sem:
            r = await probe_guarded(c.spec, timeout)
        c.ok = r["text"] == "ok" or str(r["text"]).startswith("odd")
        c.tools, c.latency_s, c.error = r["tools"], r["latency_s"], r["error"]
        done += 1
        print(f"  [{done}/{len(cands)}] {c.spec}: {'OK' if c.ok else 'FAIL'} tools={c.tools} "
              f"{'' if c.latency_s is None else str(c.latency_s) + 's'} {c.error[:70]}", flush=True)
    await asyncio.gather(*[one(c) for c in cands])


def score(c: Candidate) -> float:
    if not c.ok:
        return -1e9
    s = prerank(c)
    s += 2.0 if c.tools == "native" else 0.0
    if c.latency_s is not None:
        s -= min(2.0, c.latency_s / 10)
    return round(s, 3)


def discover(sources: list[str] | None = None, max_probe: int = 24, concurrency: int = 6,
             timeout: int = 30, ttl_hours: float = 6, refresh: bool = False, verbose: bool = True) -> list[Candidate]:
    inject_fcm_keys(verbose)
    if not refresh and CACHE_FILE.exists():
        d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - d.get("created", 0) < ttl_hours * 3600 and any(c.get("ok") for c in d["candidates"]):
            return [Candidate(**c) for c in d["candidates"]]
    sources = sources or ["fcm_sets", "fcm_cli", "provider_catalogs", "ollama"]
    cands = gather_candidates(sources)
    if verbose:
        by = {}
        for c in cands:
            by[c.provider] = by.get(c.provider, 0) + 1
        print(f"discovered {len(cands)} candidate models: {by}")
    cands.sort(key=prerank, reverse=True)
    # keep FCM-set models and local models always; cap the rest per provider for probe budget
    picked, per_prov = [], {}
    for c in cands:
        cap = max(4, max_probe // max(1, len({x.provider for x in cands})))
        if c.source.startswith("fcm-set") or c.provider == "ollama" or per_prov.get(c.provider, 0) < cap:
            picked.append(c)
            per_prov[c.provider] = per_prov.get(c.provider, 0) + 1
        if len(picked) >= max_probe + 8:
            break
    if verbose:
        print(f"probing {len(picked)} models (text + tool call)...")
    from .agent_loop import run_sync
    run_sync(_probe_all(picked, concurrency, timeout))
    for c in picked:
        c.score = score(c)
    picked.sort(key=lambda c: c.score, reverse=True)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({"created": time.time(), "candidates": [asdict(c) for c in picked]}, indent=1),
                          encoding="utf-8")
    return picked


# --------------------------------------------------------------------------- assign
AGENT_ORDER = ["implementer", "tester", "reviewer", "verifier", "planner", "seller"]


def assign(roles: dict[str, str], pool: list[Candidate], chain_length: int = 4, diverse: bool = True,
           last_resort: list[str] | None = None, monitor_family: str | None = None) -> dict[str, list[str]]:
    """roles: {role: 'auto:<kind>'} (kind: coder | agent | chat | judge). Returns explicit chains."""
    good = [c for c in pool if c.ok]
    if not good and not last_resort:
        raise RuntimeError("model pool is empty: no free model answered (check keys / `clab fcm status`)")
    last_resort = last_resort or []
    agents = [r for r in roles if r != "monitor_judge"]
    out: dict[str, list[str]] = {}

    # monitor first: best text-capable model whose family is not the best agent family;
    # that family is then excluded from every agent chain. (If the monitor is pinned explicitly,
    # `monitor_family` is passed in and excluded the same way.)
    if "monitor_judge" in roles:
        top_agent_fam = next((c.family for c in good if c.provider != "ollama"), None)
        fams = []
        for c in good:
            if c.family not in fams and c.family not in ("unknown", "router:dynamic"):
                fams.append(c.family)
        choice = next((f for f in fams if f != top_agent_fam), None) or next(iter(fams), None)
        monitor_family = choice
        mchain = [c.spec for c in good if c.family == choice][:chain_length]
        out["monitor_judge"] = mchain or ["none"]

    agent_pool = [c for c in good if c.family != monitor_family]
    used_fams: set[str] = set()
    for role in sorted(agents, key=lambda r: AGENT_ORDER.index(r) if r in AGENT_ORDER else 99):
        kind = roles[role].split(":", 1)[1] if ":" in roles[role] else "agent"
        need_tools = role != "seller" and kind != "chat"
        ranked = sorted(agent_pool, key=lambda c: c.score + (1.0 if kind == "coder" and CODER.search(c.model) else 0)
                        - (3.0 if need_tools and c.tools != "native" else 0), reverse=True)
        primary = next((c for c in ranked if not diverse or c.family not in used_fams), ranked[0] if ranked else None)
        chain = ([primary.spec] if primary else []) + [c.spec for c in ranked if primary is None or c.spec != primary.spec]
        chain = chain[:chain_length]
        if primary:
            used_fams.add(primary.family)
        tail = [s for s in last_resort if s not in chain and resolve(s).family != monitor_family]
        out[role] = chain + tail
    return out


def expand_auto(mapping: dict[str, Any], pool_cfg: dict[str, Any], verbose: bool = False) -> dict[str, list[str]]:
    """Replace `auto:*` role entries with discovered chains (uses the cached pool when fresh)."""
    auto_roles = {r: (v if isinstance(v, str) else v[0]) for r, v in mapping.items()
                  if (isinstance(v, str) and v.startswith("auto")) or (isinstance(v, list) and v and str(v[0]).startswith("auto"))}
    if not auto_roles:
        return {}
    roles = dict(auto_roles)
    if "default" in roles:
        d = roles.pop("default")
        for r in ("planner", "implementer", "tester", "reviewer", "verifier", "seller"):
            if r not in mapping:
                roles[r] = d
    pool = discover(pool_cfg.get("sources"), pool_cfg.get("max_probe", 24), pool_cfg.get("concurrency", 6),
                    pool_cfg.get("timeout", 30), pool_cfg.get("ttl_hours", 6), False, verbose)
    last = list(pool_cfg.get("last_resort", []))
    if "fcm/fcm" in last and not fcm_router_up():
        last.remove("fcm/fcm")
    if "ollama" in last:
        i = last.index("ollama")
        last[i:i + 1] = [f"ollama/{m}" for m in ollama_models()]
    mon_fam = None
    mj = mapping.get("monitor_judge")
    if mj and "monitor_judge" not in auto_roles:
        first = mj if isinstance(mj, str) else mj[0]
        if first not in ("none", "scripted"):
            mon_fam = resolve(first).family
    return assign(roles, pool, pool_cfg.get("chain_length", 4), pool_cfg.get("diverse_roles", True), last, mon_fam)
