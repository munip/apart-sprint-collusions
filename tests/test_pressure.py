import asyncio
from types import SimpleNamespace as NS

import pytest
from inspect_ai.model import ModelOutput, ModelUsage, get_model

from collusion_lab.core.evidence import EvidenceLog
from collusion_lab.core.models import ModelRoster
from collusion_lab.core.pressure import Pressure, parse_list


def test_parse_shorthand_and_ids():
    assert not Pressure.parse(None).active and Pressure.parse("none").suffix() == ""
    p = Pressure.parse("t120")
    assert p.wall_seconds == 120 and p.suffix() == "-pt120"
    q = Pressure.parse("d5+r10")
    assert (q.decision_seconds, q.rounds, q.suffix()) == (5, 10, "-pd5_r10")
    assert Pressure.parse({"name": "tight", "max_tool_calls": 40}).max_tool_calls == 40
    names = [x.name for x in sorted(parse_list(["none", "t600", "t120"]), key=Pressure.sort_key)]
    assert names == ["t120", "t600", "none"]
    with pytest.raises(ValueError):
        Pressure.parse("fast")
    assert "120 seconds" in p.swe_prompt() and "5 seconds" in Pressure.parse("d5").market_prompt()


def _mock(roster, outs):
    for o in outs:
        o.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    roster._models["mockllm/model"] = get_model("mockllm/model", custom_outputs=outs)


def test_swe_tool_call_budget_stops_work_and_forces_final_review(tmp_path):
    from collusion_lab.scenarios.swe.agents.llm import LLMTeam
    from collusion_lab.scenarios.swe.conditions import get
    from collusion_lab.scenarios.swe.workspace import Workspace
    log = EvidenceLog(tmp_path / "ev.jsonl")
    ws = Workspace(tmp_path, NS(id="T3"), log, "ep", max_tool_calls=2)
    ws.register(["implementer", "reviewer"])
    roster = ModelRoster("scripted", {"implementer": "mockllm/model", "reviewer": "mockllm/model"})
    msg = lambda i: ModelOutput.for_tool_call("mockllm/model", "send_message", {"to": "team", "text": f"m{i}"})
    _mock(roster, [msg(1), msg(2), msg(3),       # third call exceeds the budget
                   ModelOutput.for_tool_call("mockllm/model", "review", {"decision": "approve"}),
                   ModelOutput.for_tool_call("mockllm/model", "done", {})])
    team = LLMTeam(ws, get("C0_honest_single"), 0, roster, Pressure.parse("c2"))
    assert "2 tool calls" in team._system("implementer")
    team._turn("implementer", "work", 10)
    assert ws.calls_used == 2 and ws.deadline_hit == "tool_calls" and team.cut_turns == 1
    team._turn("tester", "skipped", 5)            # no more work turns after the budget
    team._release()                               # but the reviewer gets a final ship/no-ship turn
    assert ws.approvals["reviewer"]["decision"] == "approve" and ws.release_requested
    assert any(e.payload.get("event") == "budget_exhausted" for e in log.events())


def test_market_decision_deadline_keeps_standing_ask(tmp_path):
    from collusion_lab.scenarios.market.env import run_market_episode
    roster = ModelRoster("scripted", {"seller": "mockllm/model"})

    async def slow(*a, **k):
        await asyncio.sleep(2)
        raise AssertionError("should have timed out")
    roster.generate = slow
    rec = run_market_episode("A0_competitive", 0, tmp_path, rounds=30, roster=roster, pressure="d0.2+r3")
    assert rec["episode_id"] == "mkt-A0_competitive-s0-pd0.2_r3" and rec["rounds"] == 3
    assert rec["outcome"]["decision_timeouts"] == 15 and rec["outcome"]["timeout_rate"] == 1.0
    assert rec["pressure"]["decision_seconds"] == 0.2


def test_swe_wall_clock_deadline_cuts_a_slow_turn(tmp_path):
    import time
    from collusion_lab.scenarios.swe.agents.llm import LLMTeam
    from collusion_lab.scenarios.swe.conditions import get
    from collusion_lab.scenarios.swe.workspace import Workspace
    ws = Workspace(tmp_path, NS(id="T3"), EvidenceLog(tmp_path / "ev.jsonl"), "ep", deadline_s=1.0)
    roster = ModelRoster("scripted", {"implementer": "mockllm/model"})

    async def slow(*a, **k):
        await asyncio.sleep(5)
    roster.generate = slow
    team = LLMTeam(ws, get("C0_honest_single"), 0, roster, Pressure.parse("t1"))
    t0 = time.monotonic()
    team._turn("implementer", "work", 10)
    assert time.monotonic() - t0 < 3 and ws.deadline_hit == "time" and team.cut_turns == 1
