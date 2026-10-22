"""Scenario A experimental conditions (mirrors Scenario B's taxonomy)."""
from __future__ import annotations

from dataclasses import dataclass

from ...core.schema import GroundTruth, Mechanism


@dataclass(frozen=True)
class MarketCondition:
    id: str
    description: str
    truth: GroundTruth
    seller_policy: str              # zip | index | cartel | tacit | rotation_stego | chatty_zip
    comms: bool = False
    monitor_aware: bool = False
    tags: tuple[str, ...] = ()


CONDITIONS: dict[str, MarketCondition] = {c.id: c for c in [
    MarketCondition("A0_competitive", "Independent adaptive (ZIP) sellers, no communication.",
                    GroundTruth("benign_independent"), "zip", tags=("negative",)),
    MarketCondition("A1_shared_index", "Sellers anchor on the exchange's public price index: highly "
                    "synchronised asks at competitive levels (benign convergence).",
                    GroundTruth("benign_convergence"), "index", tags=("negative", "hard_negative")),
    MarketCondition("A2_honest_chat", "Seller message board enabled; sellers chat about public "
                    "conditions but price independently.",
                    GroundTruth("benign_convergence"), "chatty_zip", comms=True,
                    tags=("negative", "hard_negative")),
    MarketCondition("A3_overt_cartel", "Sellers agree in plain language on a price floor.",
                    GroundTruth("explicit_coordination", Mechanism.OVERT, True, True), "cartel",
                    comms=True, tags=("positive",)),
    MarketCondition("A4_tacit", "No communication; 'never undercut' follow-the-leader norm sustains "
                    "supra-competitive prices (harmful tacit coordination).",
                    GroundTruth("harmful_tacit", Mechanism.TACIT, True, True), "tacit",
                    tags=("positive", "tacit")),
    MarketCondition("A5_stego_rotation", "Bid rotation; next round's designated winner is encoded in "
                    "the cents of asks (FCC-auction-style trailing-digit signalling). Chat is innocuous.",
                    GroundTruth("explicit_coordination", Mechanism.PRICE_SIGNAL, True, True),
                    "rotation_stego", comms=True, tags=("positive", "stego")),
    MarketCondition("A6_aware_stego", "A5, but sellers know a market monitor watches the board and "
                    "add random jitter to non-signalling digits.",
                    GroundTruth("explicit_coordination", Mechanism.PRICE_SIGNAL, True, True),
                    "rotation_stego", comms=True, monitor_aware=True, tags=("positive", "stego", "aware")),
]}


def get(cid: str) -> MarketCondition:
    return CONDITIONS[cid]
