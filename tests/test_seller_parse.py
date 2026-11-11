import json

from inspect_ai.model import ModelOutput, ModelUsage

from collusion_lab.core.models import ModelRoster
from collusion_lab.scenarios.market.agents.llm import parse_seller_reply


def test_parse_takes_last_object_with_ask():
    assert parse_seller_reply('Sure. {"ask": 72.5} because {reasons}') == {"ask": 72.5}
    assert parse_seller_reply('{"ask": 70} ... final: {"ask": 71}') == {"ask": 71}
    assert parse_seller_reply('{"ask": null}') == {"ask": None}
    assert parse_seller_reply("I think 70 is fair") is None


def test_rambling_reply_is_finalized_or_keeps_standing_ask(tmp_path):
    from collusion_lab.scenarios.market.agents.llm import FINALIZE
    from collusion_lab.scenarios.market.env import run_market_episode
    roster = ModelRoster("scripted", {"seller": "mockllm/model"})
    main = iter(['Here you go: {"ask": 80.0}'] * 5 + ["Let me think about the market at length..."] * 10)
    final = iter(['{"ask": 81}'] * 5 + ["still thinking"] * 5)          # round 2 recovers, round 3 does not

    async def gen(role, messages, **k):
        text = next(final) if messages[-1].content == FINALIZE else next(main)
        o = ModelOutput.from_content("mockllm/model", text)
        o.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        o.metadata = {"clab_spec": "mockllm/model"}
        roster.meter.add(role, "mockllm/model", 1, 1)
        return o
    roster.generate = gen
    rec = run_market_episode("A0_competitive", 0, tmp_path, 3, roster)
    ev = [json.loads(l) for l in open(tmp_path / rec["episode_id"] / "evidence.jsonl")]
    asks = [e["payload"]["price"] for e in ev if e["kind"] == "action" and e["payload"].get("type") == "ask"
            and e["actor"].startswith("S")]
    assert asks == [80.0] * 5 + [81.0] * 10          # round 3 keeps the standing ask, not a withdrawal
    assert rec["seller_parse_failures"] == 5
    raw = [json.loads(l) for l in (tmp_path / rec["episode_id"] / "llm_raw.jsonl").read_text().splitlines()]
    assert len(raw) == 15 and sum(r["finalized"] for r in raw) == 10 and raw[-1]["parsed"] is None


def test_a5_prompt_states_the_current_designated_seller():
    from types import SimpleNamespace

    from collusion_lab.core.agent_loop import run_sync
    from collusion_lab.scenarios.market.agents.llm import LLMSeller
    from collusion_lab.scenarios.market.conditions import get

    captured = []

    class CaptureRoster:
        async def generate(self, role, messages, **kwargs):
            captured.extend(messages)
            return ModelOutput.from_content("mockllm/model", '{"ask": 95.00}')

    seller = LLMSeller("S2", 62.0, get("A5_stego_rotation"), CaptureRoster(), 0)
    market = SimpleNamespace(history=[], asks={}, costs={f"S{i}": 60.0 + i for i in range(1, 6)})
    run_sync(seller.aact(1, 15, market, {"designated": 2}, {}))

    prompt = "\n".join(message.content for message in captured)
    assert "S3 is the designated seller" in prompt
    assert "you are not designated" in prompt
    assert "encodes the next seller" in prompt


def test_a3_llm_sellers_receive_the_seeded_opening_proposal(tmp_path):
    from collusion_lab.core.models import ModelRoster
    from collusion_lab.scenarios.market.env import run_market_episode

    prompts = []
    roster = ModelRoster("scripted", {"seller": "mockllm/model"})

    async def generate(role, messages, **kwargs):
        prompts.append(messages[-1].content)
        return ModelOutput.from_content("mockllm/model", '{"ask": 90, "message_to_sellers": "Agreed."}')

    roster.generate = generate
    record = run_market_episode("A3_overt_cartel", 0, tmp_path, rounds=1, roster=roster)

    assert len(prompts) == 5
    assert all("Scenario kickoff" in prompt and "$90.00" in prompt for prompt in prompts)
    evidence = (tmp_path / record["episode_id"] / "evidence.jsonl").read_text(encoding="utf-8")
    assert '"seeded": true' in evidence
