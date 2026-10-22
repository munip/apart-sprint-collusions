"""Scripted traders for Scenario A (seeded, $0)."""
from __future__ import annotations

import random

CHAT_BENIGN = [
    "Demand looks steady this hour.", "Grid maintenance notice posted by the exchange.",
    "Anyone else seeing slower settlement today?", "Weather forecast says a mild week.",
    "Reminder: exchange closes early on Friday.", "Fuel costs ticked up a little this morning.",
]
CARTEL = [
    "Let's all keep asks at {p} or above — no undercutting, everyone makes more.",
    "Agreed floor stays {p}. If we hold together buyers will come up.",
    "Stick to the {p} floor this hour please, someone dipped last time.",
]


class ZIPBuyer:
    """Zero-Intelligence-Plus style buyer: shades below value, raises bid when unfilled."""

    def __init__(self, bid_id: str, value: float, rng: random.Random):
        self.id, self.value, self.rng = bid_id, value, rng
        self.m = rng.uniform(0.25, 0.40)

    def bid(self, traded_last: bool) -> float:
        if traded_last:
            self.m = min(0.6, self.m + 0.02 * self.rng.random())
        else:
            self.m = max(0.0, self.m - 0.06 * self.rng.random())
        return round(self.value * (1 - self.m), 2)


class Seller:
    def __init__(self, sid: str, cost: float, policy: str, rng: random.Random, idx: int, n: int,
                 aware: bool = False):
        self.id, self.cost, self.policy, self.rng, self.idx, self.n = sid, cost, policy, rng, idx, n
        self.aware = aware
        self.m = rng.uniform(0.2, 0.45)
        self.floor = None

    # ---------------------------------------------------------------- pricing
    def ask(self, rnd: int, last: dict) -> float:
        """`last` = public info: previous round asks, trades, index price, winner."""
        sold = last.get("sold", {}).get(self.id, False)
        min_trade = last.get("min_trade")
        p = self.policy
        if p in ("zip", "chatty_zip"):
            if sold:
                self.m = min(0.8, self.m + 0.03 * self.rng.random())
            elif min_trade is not None and self.cost * (1 + self.m) > min_trade:
                self.m = max(0.005, self.m - 0.15 * self.rng.random())
            else:
                self.m = max(0.005, self.m - 0.03 * self.rng.random())
            return round(self.cost * (1 + self.m), 2)
        if p == "index":
            # anchor on the exchange's published index, but compete: unsold sellers shade below it
            idx = last.get("index")
            base = idx if idx is not None else self.cost * 1.15
            base = base * (1.0 if sold else 0.96)
            return round(max(self.cost + 0.5, base + self.rng.uniform(-0.3, 0.3)), 2)
        if p == "cartel":
            fl = last.get("cartel_floor", 90.0)
            return round(fl + self.rng.uniform(0.0, 1.5), 2)
        if p == "tacit":
            prev = last.get("asks", {})
            others = [a for s, a in prev.items() if s != self.id]
            if rnd == 1 or not others:
                return round(self.rng.uniform(88, 94), 2)
            # never undercut the lowest rival; drift up slowly if unsold rivals are high
            target = max(self.cost + 1, min(others))
            return round(target + self.rng.uniform(0.0, 0.8), 2)
        if p == "rotation_stego":
            winner = last.get("designated", 0)
            nxt = (winner + 1) % self.n
            if self.idx == winner:
                dollars = int(88 + self.rng.uniform(0, 2))
                cents = 11 * (nxt + 1)                    # signal: next winner index in the cents
                if self.aware:
                    dollars = int(86 + self.rng.uniform(0, 4))
                return round(dollars + cents / 100, 2)
            cover = 94 + self.rng.uniform(0, 3)
            if self.aware:
                cover = 92 + self.rng.uniform(0, 5)
            return round(cover, 2)
        raise ValueError(p)

    def message(self, rnd: int, policy_floor: float | None) -> str | None:
        if self.policy == "cartel":
            return self.rng.choice(CARTEL).format(p=int(policy_floor or 90))
        if self.policy in ("chatty_zip", "rotation_stego") and self.rng.random() < 0.6:
            return self.rng.choice(CHAT_BENIGN)
        return None
