import pytest
from inspect_ai.model import ModelOutput, ModelUsage, get_model

from collusion_lab.core.agent_loop import run_sync
from collusion_lab.core.models import AllModelsFailed, ModelRoster
from collusion_lab.core.providers import resolve


def test_local_hf_models_need_no_key():
    r = resolve("hf/Qwen/Qwen2.5-1.5B-Instruct")
    assert not r.has_key and not r.needs_key
    assert resolve("ollama/gemma2:2b").needs_key is False


def test_hf_model_is_actually_called(monkeypatch):
    from inspect_ai.model import ChatMessageUser
    roster = ModelRoster("scripted", {"seller": "hf/Qwen/Qwen2.5-1.5B-Instruct"})
    out = ModelOutput.from_content("mockllm/model", '{"ask": 70}')
    out.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    mock = get_model("mockllm/model", custom_outputs=[out])
    monkeypatch.setattr(roster, "_get", lambda r: mock)
    res = run_sync(roster.generate("seller", [ChatMessageUser(content="hi")]))
    assert res.completion == '{"ask": 70}' and roster.meter.calls == 1


def test_failures_are_printed_once(monkeypatch, capsys):
    from inspect_ai.model import ChatMessageUser
    roster = ModelRoster("scripted", {"seller": "groq/no-such-model"})
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("collusion_lab.core.providers.os.environ", {})
    for _ in range(3):
        with pytest.raises(AllModelsFailed):
            run_sync(roster.generate("seller", [ChatMessageUser(content="hi")]))
    assert capsys.readouterr().out.count("!! all models failed") == 1


def test_local_models_get_no_http_timeouts(monkeypatch):
    from inspect_ai.model import ChatMessageUser
    roster = ModelRoster("scripted", {"seller": "hf/Qwen/Qwen2.5-1.5B-Instruct"})
    seen = {}

    class Fake:
        async def generate(self, messages, tools=None, config=None):
            seen["cfg"] = config
            o = ModelOutput.from_content("mockllm/model", "{}")
            o.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
            return o
    monkeypatch.setattr(roster, "_get", lambda r: Fake())
    run_sync(roster.generate("seller", [ChatMessageUser(content="hi")], max_tokens=600))
    c = seen["cfg"]
    assert c.attempt_timeout is None and c.timeout is None and c.max_retries == 0 and c.max_tokens == 600


def test_single_remote_model_retries_patiently(monkeypatch):
    from inspect_ai.model import ChatMessageUser
    monkeypatch.setenv("GROQ_API_KEY", "x")
    seen = []

    class Fake:
        async def generate(self, messages, tools=None, config=None):
            seen.append(config)
            o = ModelOutput.from_content("mockllm/model", "{}")
            o.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
            return o
    for chain, patient in (("groq/qwen/qwen3.8-27b", True), ("groq/qwen/qwen3.8-27b,groq/openai/gpt-oss-20b", False)):
        roster = ModelRoster("scripted", {"seller": chain})
        monkeypatch.setattr(roster, "_get", lambda r: Fake())
        run_sync(roster.generate("seller", [ChatMessageUser(content="hi")]))
        assert (seen[-1].max_retries >= 6 and seen[-1].timeout >= 600) == patient
