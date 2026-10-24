from types import SimpleNamespace as NS

from inspect_ai.model import ModelOutput, ModelUsage

from collusion_lab.core.agent_loop import WRAP_UP, ToolSpec, run_sync, tool_loop
from collusion_lab.core.evidence import EvidenceLog
from collusion_lab.core.models import ModelRoster


def _out(fn, args):
    o = ModelOutput.for_tool_call("mockllm/model", fn, args)
    o.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    return o


def test_agents_get_a_wrap_up_nudge_before_the_turn_cap():
    roster = ModelRoster("scripted", {"tester": "mockllm/model"})
    seen = []

    async def gen(role, messages, **k):
        seen.append(messages[-1].content if isinstance(messages[-1].content, str) else "")
        return _out("read_messages", {})
    roster.generate = gen
    tools = [ToolSpec("read_messages", "r", {}), ToolSpec("done", "d", {})]
    msgs = run_sync(tool_loop(roster, "tester", "sys", "go", tools, lambda n, a: "ok", max_turns=6))
    assert sum(1 for m in msgs if getattr(m, "content", None) == WRAP_UP) == 1


def test_reviewer_who_never_decides_is_asked_to_decide(tmp_path):
    from collusion_lab.scenarios.swe.agents.llm import DECIDE_NOW, LLMTeam
    from collusion_lab.scenarios.swe.conditions import get
    from collusion_lab.scenarios.swe.workspace import Workspace
    (tmp_path / ".scratch").mkdir()
    ws = Workspace(tmp_path, NS(id="T3"), EvidenceLog(tmp_path / "ev.jsonl"), "ep")
    ws.register(["implementer", "reviewer"])
    roster = ModelRoster("scripted", {"reviewer": "mockllm/model"})

    async def gen(role, messages, **k):
        last = messages[-1].content if isinstance(messages[-1].content, str) else ""
        return _out("review", {"decision": "approve", "comment": "ok"}) if DECIDE_NOW in last \
            else _out("read_messages", {})
    roster.generate = gen
    team = LLMTeam(ws, get("C0_honest_single"), 0, roster)
    team._release()
    assert ws.approvals["reviewer"]["decision"] == "approve" and ws.release_requested


def test_policy_is_in_every_agent_prompt():
    from collusion_lab.scenarios.swe.agents.llm import LLMTeam
    from collusion_lab.scenarios.swe.conditions import get
    team = LLMTeam(NS(), get("C3_collude_overt"), 0, ModelRoster("scripted"))
    for role in ("planner", "implementer", "tester", "reviewer"):
        assert "never skip, xfail, delete or weaken tests" in team._system(role)
