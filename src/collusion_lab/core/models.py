"""Role -> model resolution, cost metering and a hard budget cap.

Agents call `roster.generate(role, messages, tools)`. When the role is mapped to
"scripted" the caller must use its scripted policy instead (roster.is_scripted).
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "models.yaml"


class BudgetExceeded(RuntimeError):
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

    def price(self, model: str) -> tuple[float, float]:
        for pat, (pi, po) in self.prices.items():
            if fnmatch.fnmatch(model, pat):
                return pi, po
        return (3.0, 15.0)  # conservative default for unknown models

    def add(self, role: str, model: str, tin: int, tout: int) -> None:
        pi, po = self.price(model)
        cost = (tin * pi + tout * po) / 1e6
        self.spent_usd += cost
        self.calls += 1
        self.tokens_in += tin
        self.tokens_out += tout
        r = self.by_role.setdefault(role, {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
        r["calls"] += 1; r["in"] += tin; r["out"] += tout; r["usd"] += cost
        if self.spent_usd > self.cap_usd:
            raise BudgetExceeded(f"budget cap ${self.cap_usd:.2f} exceeded (${self.spent_usd:.2f})")

    def summary(self) -> dict[str, Any]:
        return {"usd": round(self.spent_usd, 4), "calls": self.calls,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "by_role": self.by_role}


class ModelRoster:
    def __init__(self, profile: str | None = None, overrides: dict[str, str] | None = None,
                 config_path: Path = DEFAULT_CONFIG, cap_usd: float | None = None):
        cfg = yaml.safe_load(Path(config_path).read_text())
        self.profile_name = profile or os.environ.get("CLAB_PROFILE", "scripted")
        if self.profile_name not in cfg["profiles"]:
            raise KeyError(f"unknown profile {self.profile_name!r}; have {list(cfg['profiles'])}")
        self.mapping: dict[str, str] = dict(cfg["profiles"][self.profile_name])
        self.mapping.update(overrides or {})
        cap = cap_usd if cap_usd is not None else cfg.get("budget", {}).get("hard_cap_usd", 25.0)
        self.meter = CostMeter(cfg.get("prices", {}), cap)
        self._models: dict[str, Any] = {}

    def model_name(self, role: str) -> str:
        return self.mapping.get(role, self.mapping.get("default", "scripted"))

    def is_scripted(self, role: str) -> bool:
        return self.model_name(role) in ("scripted", "none", "")

    def describe(self) -> dict[str, str]:
        return dict(self.mapping)

    def _get(self, role: str):
        name = self.model_name(role)
        if name not in self._models:
            from inspect_ai.model import get_model
            kwargs: dict[str, Any] = {}
            if name.startswith("ollama/") and os.environ.get("OLLAMA_BASE_URL"):
                kwargs["base_url"] = os.environ["OLLAMA_BASE_URL"]
            self._models[name] = get_model(name, **kwargs)
        return self._models[name]

    async def generate(self, role: str, messages: list, tools: list | None = None,
                       **config: Any):
        """Generate with metering. Returns inspect ModelOutput."""
        from inspect_ai.model import GenerateConfig
        model = self._get(role)
        out = await model.generate(messages, tools=tools or [],
                                   config=GenerateConfig(**config) if config else GenerateConfig())
        u = out.usage
        if u is not None:
            self.meter.add(role, self.model_name(role), u.input_tokens or 0, u.output_tokens or 0)
        return out
