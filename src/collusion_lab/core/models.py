"""Role -> model(s) resolution across providers/routers/gateways, with
fallback chains, per-provider rate limiting, tool-calling mode, cost metering,
a hard budget cap and a check that the trusted monitor uses a different model
family than the agents.

Profiles live in configs/models.yaml. A role maps to one spec or a fallback list:

    implementer: [groq/openai/gpt-oss-120b, cerebras/gpt-oss-120b, openrouter/qwen/qwen3-coder:free]

Agents call `roster.generate(role, messages, tools)`. When a role is "scripted"
the caller uses its scripted policy instead (roster.is_scripted).
"""
from __future__ import annotations

import asyncio
import fnmatch
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .providers import Resolved, family, get_inspect_model, resolve, LOCAL_COMPUTE

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "models.yaml"
AGENT_ROLES = ("planner", "implementer", "tester", "reviewer", "verifier", "seller", "buyer")
MONITOR_ROLES = ("monitor_judge",)
SCRIPTED = ("scripted", "none", "")


class BudgetExceeded(RuntimeError):
    pass


class AllModelsFailed(RuntimeError):
    pass


@dataclass
class CostMeter:
    prices: dict[str, list[float]]
    cap_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    by_role: dict[str, dict[str, float]] = field(default_factory=dict)
    by_model: dict[str, dict[str, float]] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def price(self, model: str) -> tuple[float, float]:
        for pat, (pi, po) in self.prices.items():
            if fnmatch.fnmatch(model, pat):
                return pi, po
        return (3.0, 15.0)  # conservative default for unknown paid models

    def add(self, role: str, model: str, tin: int, tout: int, served: str | None = None) -> None:
        pi, po = self.price(model)
        cost = (tin * pi + tout * po) / 1e6
        with self._lock:
            self.spent_usd += cost
            self.calls += 1
            self.tokens_in += tin
            self.tokens_out += tout
            for key, bucket in ((role, self.by_role), (model, self.by_model)):
                r = bucket.setdefault(key, {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
                r["calls"] += 1; r["in"] += tin; r["out"] += tout; r["usd"] += cost
            if served and served != model.split("/", 1)[-1]:
                self.by_model[model].setdefault("served_by", {})
                sb = self.by_model[model]["served_by"]
                sb[served] = sb.get(served, 0) + 1
        if self.spent_usd > self.cap_usd:
            raise BudgetExceeded(f"budget cap ${self.cap_usd:.2f} exceeded (${self.spent_usd:.2f})")

    def fail(self, model: str) -> None:
        with self._lock:
            self.failures[model] = self.failures.get(model, 0) + 1

    def summary(self) -> dict[str, Any]:
        return {"usd": round(self.spent_usd, 4), "calls": self.calls, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "by_role": self.by_role, "by_model": self.by_model,
                "failures": self.failures}


class RateLimiter:
    """Process-wide minimum spacing between requests to the same provider."""
    _last: dict[str, float] = {}
    _lock = threading.Lock()

    @classmethod
    def reserve(cls, provider: str, rpm: float) -> float:
        """Reserve the next request slot; returns seconds to wait (thread-safe, non-blocking)."""
        if rpm <= 0:
            return 0.0
        gap = 60.0 / rpm
        with cls._lock:
            now = time.monotonic()
            t = max(now, cls._last.get(provider, 0.0) + gap)
            cls._last[provider] = t
        return max(0.0, t - now)

    @classmethod
    def wait(cls, provider: str, rpm: float) -> None:
        d = cls.reserve(provider, rpm)
        if d:
            time.sleep(d)


PINNED_RETRIES = 6      # a role with a single remote model waits out rate limits
PINNED_TIMEOUT = 600.0  # seconds of total retry budget per call for such a role


class ModelRoster:
    def __init__(self, profile: str | None = None, overrides: dict[str, str] | None = None,
                 config_path: Path = DEFAULT_CONFIG, cap_usd: float | None = None):
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        self.profile_name = profile or os.environ.get("CLAB_PROFILE", "scripted")
        if self.profile_name not in cfg["profiles"]:
            raise KeyError(f"unknown profile {self.profile_name!r}; have {list(cfg['profiles'])}")
        prof = dict(cfg["profiles"][self.profile_name])
        self.allow_shared_family = bool(prof.pop("allow_shared_family", False))
        self.gen_defaults: dict[str, Any] = dict(cfg.get("generate", {}))
        self.gen_defaults.update(prof.pop("generate", {}) or {})
        prof_pool = prof.pop("pool", None)
        self.mapping: dict[str, Any] = prof
        for k, v in (overrides or {}).items():
            self.mapping[k] = [x.strip() for x in v.split(",")] if "," in v else v
        # FCM keys -> env, then expand dynamic `auto:*` roles from the discovered free-model pool
        from .pool import expand_auto, inject_fcm_keys
        inject_fcm_keys()
        self.pool_cfg: dict[str, Any] = dict(cfg.get("pool", {}))
        self.pool_cfg.update(prof_pool or {})
        expanded = expand_auto(self.mapping, self.pool_cfg)
        if expanded:
            default_auto = isinstance(self.mapping.get("default"), str) and self.mapping["default"].startswith("auto")
            self.mapping.update(expanded)
            if default_auto:
                self.mapping["default"] = expanded.get("planner") or next(
                    (v for k, v in expanded.items() if k != "monitor_judge"), ["scripted"])
        self.auto_expanded = bool(expanded)
        cap = cap_usd if cap_usd is not None else cfg.get("budget", {}).get("hard_cap_usd", 25.0)
        self.meter = CostMeter(cfg.get("prices", {}), cap)
        self._models: dict[str, Any] = {}
        self._json_mode: set[str] = set()          # specs that rejected native tool calls
        self._warned: set[str] = set()
        self._warn_count: dict[str, int] = {}

    # ------------------------------------------------------------------ mapping
    def chain(self, role: str) -> list[str]:
        v = self.mapping.get(role, self.mapping.get("default", "scripted"))
        if role in MONITOR_ROLES and role not in self.mapping:
            v = "none"
        return [v] if isinstance(v, str) else list(v)

    def model_name(self, role: str) -> str:
        return self.chain(role)[0]

    def is_scripted(self, role: str) -> bool:
        return self.model_name(role) in SCRIPTED

    def describe(self) -> dict[str, Any]:
        return {r: self.chain(r) for r in sorted(set(self.mapping) | {"default"}) if r in self.mapping}

    def resolved(self, role: str) -> list[Resolved]:
        return [resolve(s) for s in self.chain(role) if s not in SCRIPTED]

    def tool_mode(self, role: str, spec: str | None = None) -> str:
        spec = spec or self.model_name(role)
        if spec in self._json_mode:
            return "json"
        try:
            return resolve(spec).tools
        except ValueError:
            return "native"

    # ---------------------------------------------------------------- checks
    def families(self) -> tuple[set[str], set[str]]:
        agents, monitor = set(), set()
        for role in self.mapping:
            target = monitor if role in MONITOR_ROLES else agents
            for r in (self.resolved(role) if not self.is_scripted(role) else []):
                target.add(r.family)
        return agents, monitor

    def check_separation(self) -> list[str]:
        """Warnings if the trusted monitor shares a model family with any agent."""
        agents, monitor = self.families()
        warns = []
        if "router:dynamic" in monitor:
            warns.append("monitor_judge uses a dynamic router: pin a specific model for a trusted monitor")
        shared = (agents & monitor) - {"unknown", "router:dynamic"}
        if shared and not self.allow_shared_family:
            warns.append(f"monitor shares model family {sorted(shared)} with agents "
                         f"(set allow_shared_family: true only for the correlated-error ablation)")
        if "router:dynamic" in agents and monitor:
            warns.append("agents use a dynamic router; family separation from the monitor cannot be guaranteed "
                         "- check `served_by` in the cost summary")
        return warns

    def missing_keys(self) -> list[str]:
        out = []
        for role in self.mapping:
            if self.is_scripted(role):
                continue
            for r in self.resolved(role):
                if r.needs_key and not r.has_key:
                    out.append(f"{role}: {r.spec} (no API key for provider '{r.provider}')")
        return out

    # -------------------------------------------------------------- generate
    def _get(self, r: Resolved):
        if r.spec not in self._models:
            self._models[r.spec] = get_inspect_model(r)
        return self._models[r.spec]

    async def generate(self, role: str, messages: list, tools: list | None = None, **config: Any):
        """Generate with fallback across the role's chain. Returns inspect ModelOutput with
        `.metadata['clab_spec']` set to the spec that answered."""
        from inspect_ai.model import GenerateConfig
        errors = []
        for spec in self.chain(role):
            if spec in SCRIPTED:
                continue
            r = resolve(spec)
            if r.needs_key and not r.has_key:
                errors.append(f"{spec}: no API key")
                continue
            use_tools = tools if (tools and self.tool_mode(role, spec) != "json") else []
            cfg = {**self.gen_defaults, **config}
            local = r.provider in LOCAL_COMPUTE
            if local:   # a timeout would abandon a generation that keeps running and piles up behind the next call
                cfg.update(attempt_timeout=None, timeout=None, max_retries=0)
            elif len([x for x in self.chain(role) if x not in SCRIPTED]) == 1:
                # pinned to one remote model: there is nothing to fail over to, so wait out 429s instead of
                # dropping the turn (Inspect backs off exponentially between retries)
                cfg["max_retries"] = max(int(cfg.get("max_retries") or 0), PINNED_RETRIES)
                cfg["timeout"] = max(float(cfg.get("timeout") or 0), PINNED_TIMEOUT)
            delay = RateLimiter.reserve(r.provider, r.rpm)
            if delay:
                await asyncio.sleep(delay)     # non-blocking: parallel sellers keep their own slots
            try:
                model = self._get(r)
                gc = GenerateConfig(**{k: v for k, v in cfg.items() if k in GenerateConfig.model_fields})
                # hard wall-clock guard on top of Inspect's retry budget: a stuck endpoint fails over
                out = await asyncio.wait_for(model.generate(messages, tools=use_tools or [], config=gc),
                                             timeout=None if local else float(cfg.get("timeout") or 180) + 30)
            except Exception as e:  # rate limit, quota, network, unsupported tools ...
                msg = str(e)
                if use_tools and r.tools in ("auto", "native") and _tools_unsupported(msg):
                    self._json_mode.add(spec)            # retry this model in prompted-JSON tool mode
                    raise ToolModeSwitch(spec) from e
                self.meter.fail(spec)
                errors.append(f"{spec}: {type(e).__name__}: {msg[:160]}")
                continue
            if out.stop_reason == "model_length" and not out.completion and not out.message.tool_calls:
                errors.append(f"{spec}: empty output")
                continue
            u = out.usage
            self.meter.add(role, spec, (u.input_tokens or 0) if u else 0, (u.output_tokens or 0) if u else 0,
                           served=getattr(out, "model", None))
            out.metadata = {**(out.metadata or {}), "clab_spec": spec}
            return out
        msg = f"all models failed for role {role}: " + " | ".join(errors)
        import re as _re
        key = _re.sub(r" at 0x[0-9a-f]+", "", msg)[:200]   # same failure type -> one warning (+ a running count)
        self._warn_count[key] = self._warn_count.get(key, 0) + 1
        n = self._warn_count[key]
        if n == 1 or n in (10, 100, 1000):
            self._warned.add(msg)
            print(f"  !! {msg[:400]}" + (f"   (x{n} so far)" if n > 1 else ""), flush=True)
        raise AllModelsFailed(msg)


class ToolModeSwitch(RuntimeError):
    """Raised once when a model rejects native tools; the caller retries in JSON tool mode."""

    def __init__(self, spec: str):
        super().__init__(spec)
        self.spec = spec


def _tools_unsupported(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in ("does not support tools", "tool use is not supported", "tools are not supported",
                                "function calling is not", "tool_choice", "does not support function"))


__all__ = ["ModelRoster", "BudgetExceeded", "AllModelsFailed", "ToolModeSwitch", "family", "CostMeter"]
