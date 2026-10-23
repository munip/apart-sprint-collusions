"""Shared data model for both scenarios.

Everything the monitor reasons about is an `Event` written by the *environment*
(never by an agent) into the authoritative evidence log. Ground-truth labels are
kept separate from events so detectors cannot peek at them.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    MESSAGE = "message"          # agent -> agent (or broadcast) communication
    TOOL_CALL = "tool_call"      # agent invoked a tool
    TOOL_RESULT = "tool_result"  # environment's response to the tool call
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    CLAIM = "claim"              # agent's self-reported status ("tests pass", "LGTM")
    ACTION = "action"            # domain action: order, approve, merge request
    STATE = "state"              # environment state transition (round end, CI result)
    GATE = "gate"                # enforcement point outcome seen by agents


class Action(str, Enum):
    ALLOW = "ALLOW"
    HOLD = "HOLD"            # hold for review: risk elevated / evidence incomplete
    CONSTRAIN = "CONSTRAIN"  # verified violation -> block / isolate / quarantine


@dataclass
class Event:
    episode_id: str
    actor: str                       # role id, "env", or "ci"
    kind: EventKind
    payload: dict[str, Any]
    channel: str = "env"             # e.g. "chat:team", "dm:implementer->tester", "fs", "book"
    step: int = 0                    # logical step / round for latency metrics
    ts: float = field(default_factory=time.time)
    seq: int = -1                    # assigned by the log
    prev_hash: str = ""
    hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Event":
        d = dict(d)
        d["kind"] = EventKind(d["kind"])
        return Event(**d)


class Mechanism(str, Enum):
    """How coordination is carried (ground truth, from the experiment design)."""
    NONE = "none"
    OVERT = "overt"              # plain-language agreement in a monitored channel
    ENCODED = "encoded"          # steganographic text (codebook / acrostic) in chat
    ARTIFACT = "artifact"        # signal hidden in code/tests/commit metadata
    TOOL = "tool"                # side channel via tool use / shared scratch files
    LEAKAGE = "leakage"          # privileged info (reference solution) transferred
    TACIT = "tacit"              # no communication; coordinated strategy
    PRICE_SIGNAL = "price_signal"  # market: info carried in order prices (trailing digits)


@dataclass
class GroundTruth:
    """Three-way label from the requirements doc + mechanism + intent.

    category: benign_independent | benign_convergence | individual_cheating |
              harmful_tacit | explicit_coordination
    """
    category: str
    mechanism: Mechanism = Mechanism.NONE
    collusive: bool = False          # positive class for detection metrics
    harm_intended: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mechanism"] = self.mechanism.value
        return d


@dataclass
class Signal:
    """One detector output. `verified` signals may drive CONSTRAIN; the rest only HOLD."""
    name: str
    score: float                     # 0..1 suspicion / violation strength
    verified: bool = False           # backed by independent evidence (tests, canary, CE)
    family: str = "coordination"     # artifact | evidence | coordination | provenance | channel | transcript
    reasons: list[str] = field(default_factory=list)
    first_step: int | None = None    # earliest step at which this signal fired
    attribution: list[str] = field(default_factory=list)  # actors implicated


@dataclass
class Decision:
    action: Action
    risk: float
    reasons: list[str]
    signals: list[Signal]
    step: int | None = None          # when the decision was taken (latency)
    attribution: list[str] = field(default_factory=list)
    monitor: str = ""
    collusion_score: float = 0.0     # investigation output: evidence of *coordination* (not harm)
    collusion_reasons: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.action != Action.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "risk": self.risk,
            "collusion_score": self.collusion_score,
            "collusion_reasons": self.collusion_reasons,
            "reasons": self.reasons,
            "step": self.step,
            "attribution": self.attribution,
            "monitor": self.monitor,
            "signals": [asdict(s) for s in self.signals],
        }
