"""Provider registry: turns `<provider>/<model-id>` specs into Inspect models.

Supports Inspect-native providers, any OpenAI-compatible endpoint (free tiers),
routers/gateways (free-coding-models Smart Router, LiteLLM, Portkey, custom) and
local Ollama - all behind the same spec syntax. See configs/providers.yaml.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PROVIDERS_FILE = REPO_ROOT / "configs" / "providers.yaml"


@dataclass(frozen=True)
class Resolved:
    spec: str                 # as written in the profile, e.g. "groq/llama-3.3-70b-versatile"
    provider: str
    model_id: str
    kind: str                 # native | openai_compat | router
    inspect_name: str         # name passed to inspect get_model
    base_url: str | None
    api_key: str | None
    rpm: float
    tools: str                # native | json | auto
    family: str

    @property
    def has_key(self) -> bool:
        return bool(self.api_key) or self.provider == "mockllm"


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    return yaml.safe_load(PROVIDERS_FILE.read_text(encoding="utf-8"))


def _expand(s: str | None) -> str | None:
    if s is None:
        return None
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), s)


def family(model_id: str) -> str:
    m = model_id.lower()
    if re.search(r"(^|[/_:-])o[134](-|$|[/_:])", m):
        return "gpt"
    for fam, pats in registry()["families"].items():
        if any(p in m for p in pats):
            return fam
    if m.startswith("fcm") or m in ("auto", "router"):
        return "router:dynamic"
    return "unknown"


def resolve(spec: str) -> Resolved:
    spec = spec.strip()
    if "/" not in spec:
        raise ValueError(f"model spec must be <provider>/<model>, got {spec!r}")
    provider, model_id = spec.split("/", 1)
    reg = registry()["providers"]
    if provider not in reg:
        # any other Inspect-native provider string (vllm/, bedrock/, azureai/ ...) passes through
        return Resolved(spec, provider, model_id, "native", spec, None, None, 60, "native", family(model_id))
    p = reg[provider]
    kind = p.get("kind", "openai_compat")
    base_url = _expand(os.environ.get(p.get("base_url_env", ""), "") or p.get("base_url"))
    api_key = next((os.environ[k] for k in p.get("api_key_env", []) if os.environ.get(k)), None) or p.get("api_key")
    if kind == "native":
        inspect_name = spec
        if provider == "ollama":
            base_url = base_url or "http://localhost:11434/v1"
    else:
        inspect_name = f"openai-api/{provider}/{model_id}"
    return Resolved(spec, provider, model_id, kind, inspect_name, base_url, api_key,
                    float(p.get("rpm", 60)), p.get("tools", "native"),
                    "router:dynamic" if kind == "router" and model_id.startswith("fcm") else family(model_id))


def get_inspect_model(r: Resolved):
    from inspect_ai.model import get_model
    kwargs: dict[str, Any] = {}
    if r.kind != "native" or r.provider == "ollama":
        kwargs["base_url"] = r.base_url
        kwargs["api_key"] = r.api_key or "none"
    return get_model(r.inspect_name, **kwargs)


def key_status() -> list[dict[str, Any]]:
    rows = []
    for name, p in registry()["providers"].items():
        envs = p.get("api_key_env", [])
        found = next((k for k in envs if os.environ.get(k)), None)
        rows.append({"provider": name, "kind": p.get("kind"), "key": found or ("built-in" if p.get("api_key") else "-"),
                     "base_url": _expand(os.environ.get(p.get("base_url_env", ""), "") or p.get("base_url", "")),
                     "verify": bool(p.get("verify"))})
    return rows


# ---------------------------------------------------------------------------
# free-coding-models config import (best effort; its JSON schema is not documented)
# ---------------------------------------------------------------------------
FCM_ALIASES = {"google ai studio": "google", "googleai": "google", "gemini": "google", "nvidia nim": "nvidia",
               "nim": "nvidia", "github models": "github", "cloudflare workers ai": "cloudflare",
               "mistral la plateforme": "mistral", "alibaba": "dashscope", "ovhcloud": "ovh",
               "ollama cloud": "ollama_cloud", "hf": "huggingface"}


def import_fcm_keys(path: Path | None = None) -> dict[str, str]:
    """Return {ENV_VAR: key} found in ~/.free-coding-models.json (or --config-dir/config.json)."""
    path = path or Path.home() / ".free-coding-models.json"
    if not path.exists():
        alt = Path.home() / ".free-coding-models" / "config.json"
        path = alt if alt.exists() else path
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    reg = registry()["providers"]
    out: dict[str, str] = {}

    def norm(k: str) -> str:
        k = k.lower().replace("_", " ").replace("-", " ").strip()
        k = FCM_ALIASES.get(k, k)
        return k.replace(" ", "_")

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                name = norm(str(k))
                if name in reg and isinstance(v, str) and len(v) >= 8:
                    envs = reg[name].get("api_key_env", [])
                    if envs:
                        out.setdefault(envs[0], v)
                elif name in reg and isinstance(v, dict):
                    for kk in ("apiKey", "api_key", "key", "token"):
                        if isinstance(v.get(kk), str) and len(v[kk]) >= 8 and reg[name].get("api_key_env"):
                            out.setdefault(reg[name]["api_key_env"][0], v[kk])
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(data)
    return out
