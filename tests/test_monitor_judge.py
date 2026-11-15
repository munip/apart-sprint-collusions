import asyncio
import hashlib
import json
from types import SimpleNamespace

from collusion_lab.core.schema import Event, EventKind
from collusion_lab.monitor import judge


def _event():
    return Event(
        episode_id="temperature-test",
        actor="S1",
        kind=EventKind.MESSAGE,
        payload={"text": "Let us keep prices independent."},
        channel="chat:sellers",
    )


def test_llm_judge_uses_positive_temperature_for_transformers(monkeypatch, tmp_path):
    calls = []

    class FakeRoster:
        def is_scripted(self, role):
            return False

        def chain(self, role):
            return ["hf/CohereLabs/tiny-aya-fire"]

        async def generate(self, role, messages, **config):
            calls.append((role, config))
            return SimpleNamespace(
                completion=json.dumps({
                    "collusion_probability": 0.2,
                    "colluding_agents": [],
                    "rationale": "No coordination evidence.",
                }),
                metadata={"clab_spec": "hf/CohereLabs/tiny-aya-fire"},
            )

    import collusion_lab.core.providers as providers

    monkeypatch.setattr(providers, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "collusion_lab.core.agent_loop.run_sync",
        asyncio.run,
    )
    monkeypatch.setattr(judge, "_MEMO", {})

    signal = judge.llm_judge_signal(FakeRoster(), [_event()], "market")

    assert signal is not None and signal.name == "llm_judge"
    assert calls == [("monitor_judge", {"temperature": 0.1, "max_tokens": 800})]


def test_parse_normalizes_mixed_agent_identifiers():
    probability, agents, rationale = judge.parse(
        '{"collusion_probability":0.8,"colluding_agents":[1," S2 ",null,{},true],'
        '"rationale":"Coordination evidence."}'
    )

    assert probability == 0.8
    assert agents == ["1", "S2"]
    assert rationale == "Coordination evidence."


def test_cached_judge_response_normalizes_agent_identifiers(monkeypatch, tmp_path):
    class FakeRoster:
        def is_scripted(self, role):
            return False

        def chain(self, role):
            return ["hf/CohereLabs/tiny-aya-fire"]

        async def generate(self, role, messages, **config):
            raise AssertionError("cached response should be used")

    chain = "hf/CohereLabs/tiny-aya-fire"
    prompt = judge.JUDGE_PROMPT.format(
        domain="market",
        policy=judge.POLICIES["market"],
        transcript=judge.transcript([_event()]),
    )
    key = hashlib.sha256(f"{chain}|{prompt}".encode()).hexdigest()[:24]
    cache = tmp_path / ".cache" / "judge" / f"{key}.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(
        json.dumps([0.02, [1, "S2"], "No coordination evidence.", chain]),
        encoding="utf-8",
    )
    monkeypatch.setattr("collusion_lab.core.providers.REPO_ROOT", tmp_path)
    monkeypatch.setattr(judge, "_MEMO", {})

    signal = judge.llm_judge_signal(FakeRoster(), [_event()], "market")

    assert signal is not None
    assert signal.attribution == ["1", "S2"]
