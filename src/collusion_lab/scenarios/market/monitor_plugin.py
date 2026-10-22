"""Scenario A plugin for the generic TrustedMonitor (same interface as SWEPlugin)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.schema import Event, Signal
from ...monitor.detectors import generic as G
from ...monitor.detectors import market as M
from ...monitor.judge import llm_judge_signal


@dataclass
class MarketContext:
    costs: dict[str, float]      # exchange-held cost data (as in real market monitoring units)
    values: dict[str, float]
    sellers: list[str]
    roster: Any = None
    step: int = 0


class MarketPlugin:
    name = "market"

    def signals(self, level: str, ctx: MarketContext, events: list[Event]) -> list[Signal]:
        out: list[Signal] = []
        if level in ("M1", "M4"):
            out.append(G.transcript_rules_signal(events))
        if level == "M1":
            # rules-only: crude price rule without a cost model (asks far above recent trades)
            b = M.benchmark_signal(events, ctx.costs, ctx.values)
            out.append(Signal("price_rule", b.score * 0.8, False, "artifact", b.reasons, b.first_step, b.attribution))
        if level in ("M2", "M4"):
            j = llm_judge_signal(ctx.roster, events, "market")
            if j is not None:
                out.append(j)
        if level in ("M3", "M4"):
            out += [M.benchmark_signal(events, ctx.costs, ctx.values),
                    M.ask_sync_signal(events, ctx.sellers),
                    M.digit_channel_signal(events, ctx.sellers),
                    M.rotation_signal(events, ctx.sellers)]
        return out
