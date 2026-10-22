"""The LLM agent path works end-to-end with Inspect's mockllm (no API key needed)."""
from inspect_ai.model import ModelOutput, ModelUsage, get_model

from collusion_lab.core.agent_loop import ToolSpec, run_sync, tool_loop
from collusion_lab.core.models import ModelRoster


def test_tool_loop_routes_calls_through_dispatcher():
    roster = ModelRoster("scripted", {"implementer": "mockllm/model"})
    outs = [ModelOutput.for_tool_call("mockllm/model", "send_message", {"to": "tester", "text": "hi"}),
            ModelOutput.for_tool_call("mockllm/model", "done", {})]
    for o in outs:   # explicit usage: avoids tiktoken downloads in sandboxed CI
        o.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    roster._models["mockllm/model"] = get_model("mockllm/model", custom_outputs=outs)
    seen = []

    def dispatch(name, args):
        seen.append((name, args))
        return "ok"

    tools = [ToolSpec("send_message", "msg", {"to": ("string", ""), "text": ("string", "")}, ("to", "text")),
             ToolSpec("done", "end", {})]
    run_sync(tool_loop(roster, "implementer", "sys", "go", tools, dispatch, max_turns=5))
    assert seen == [("send_message", {"to": "tester", "text": "hi"}), ("done", {})]
    assert roster.meter.calls == 2


def test_budget_cap():
    import pytest
    from collusion_lab.core.models import BudgetExceeded
    r = ModelRoster("scripted", cap_usd=0.001)
    with pytest.raises(BudgetExceeded):
        r.meter.add("x", "anthropic/claude-sonnet-4-5", 10_000, 10_000)
