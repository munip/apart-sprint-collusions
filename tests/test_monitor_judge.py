import asyncio
import json
from types import SimpleNamespace

from collusion_lab.core.schema import Event, EventKind
from collusion_lab.monitor import judge


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
    events = [
        Event(
            episode_id="temperature-test",
            actor="S1",
            kind=EventKind.MESSAGE,
            payload={"text": "Let us keep prices independent."},
            channel="chat:sellers",
        )
    ]

    signal = judge.llm_judge_signal(FakeRoster(), events, "market")

    assert signal is not None and signal.name == "llm_judge"
    assert calls == [("monitor_judge", {"temperature": 0.1, "max_tokens": 800})]
