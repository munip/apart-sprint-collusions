"""Multi-provider plumbing: spec resolution, family separation, fallback chains, JSON tool mode."""
import pytest
from inspect_ai.model import ModelOutput, ModelUsage, get_model

from collusion_lab.core.agent_loop import ToolSpec, parse_json_call, run_sync, tool_loop
from collusion_lab.core.models import AllModelsFailed, ModelRoster
from collusion_lab.core.providers import family, resolve


def _out(text=None, tool=None, args=None):
    o = (ModelOutput.for_tool_call("mockllm/model", tool, args or {}) if tool
         else ModelOutput.from_content("mockllm/model", text))
    o.usage = ModelUsage(input_tokens=5, output_tokens=5, total_tokens=10)
    return o


def test_resolve_openai_compatible_and_router(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_123456")
    r = resolve("groq/openai/gpt-oss-120b")
    assert r.kind == "openai_compat" and r.inspect_name == "openai-api/groq/openai/gpt-oss-120b"
    assert r.base_url.startswith("https://api.groq.com") and r.has_key and r.family == "gpt"
    f = resolve("fcm/fcm:agents")
    assert f.kind == "router" and f.base_url.endswith(":19280/v1") and f.family == "router:dynamic"
    o = resolve("ollama/gemma2:2b")
    assert o.kind == "native" and o.family == "gemma" and o.tools == "auto"
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.5:11434/v1")
    assert resolve("ollama/gemma2:2b").base_url == "http://192.168.1.5:11434/v1"


@pytest.mark.parametrize("model,fam", [("llama-3.3-70b-versatile", "llama"), ("qwen/qwen3-coder:free", "qwen"),
                                       ("gemini-2.5-flash", "gemini"), ("moonshotai/kimi-k2-instruct", "kimi"),
                                       ("claude-haiku-4-5", "claude"), ("o3-mini", "gpt"), ("mixtral-8x7b", "mistral")])
def test_family(model, fam):
    assert family(model) == fam


def test_profiles_keep_monitor_family_separate():
    for prof in ("free", "free_homogeneous", "free_weak_monitor", "local", "cloud", "mixed"):
        r = ModelRoster(prof)
        assert not any("shares model family" in w for w in r.check_separation()), prof
    assert any("shares model family" in w for w in ModelRoster("same_family", {}).check_separation()) is False  # allowed ablation
    bad = ModelRoster("free", {"monitor_judge": "groq/llama-3.3-70b-versatile"})
    assert any("shares model family" in w for w in bad.check_separation())


class Boom:
    async def generate(self, *a, **k):
        raise RuntimeError("429 rate limit")


def test_fallback_chain_uses_next_model():
    roster = ModelRoster("scripted", {"implementer": "mockllm/a,mockllm/b"})
    roster._models["mockllm/a"] = Boom()
    roster._models["mockllm/b"] = get_model("mockllm/model", custom_outputs=[_out("hello")])
    out = run_sync(roster.generate("implementer", []))
    assert out.metadata["clab_spec"] == "mockllm/b" and roster.meter.failures == {"mockllm/a": 1}
    roster2 = ModelRoster("scripted", {"implementer": "mockllm/a"})
    roster2._models["mockllm/a"] = Boom()
    with pytest.raises(AllModelsFailed):
        run_sync(roster2.generate("implementer", []))


def test_parse_json_call_variants():
    names = {"read_file", "done"}
    assert parse_json_call('```json\n{"tool": "read_file", "args": {"path": "SPEC.md"}}\n```', names) == ("read_file", {"path": "SPEC.md"})
    assert parse_json_call('I will finish. {"name": "done", "arguments": "{}"}', names) == ("done", {})
    assert parse_json_call("no json here", names) is None


def test_json_tool_mode_loop(monkeypatch):
    """A model without function calling (e.g. gemma2 on Ollama) drives tools via JSON text."""
    roster = ModelRoster("scripted", {"implementer": "mockllm/json"})
    monkeypatch.setattr(roster, "tool_mode", lambda role, spec=None: "json")
    roster._models["mockllm/json"] = get_model("mockllm/model", custom_outputs=[
        _out('{"tool": "send_message", "args": {"to": "tester", "text": "hi"}}'),
        _out("thinking..."),
        _out('{"tool": "done", "args": {}}')])
    seen = []
    tools = [ToolSpec("send_message", "msg", {"to": ("string", ""), "text": ("string", "")}, ("to", "text")),
             ToolSpec("done", "end", {})]
    msgs = run_sync(tool_loop(roster, "implementer", "sys", "go", tools, lambda n, a: seen.append((n, a)) or "ok", 6))
    assert seen == [("send_message", {"to": "tester", "text": "hi"}), ("done", {})]
    assert "TOOLS (call exactly one per reply)" in msgs[0].text
