import json

from inspect_ai.model import ModelOutput, ModelUsage

from collusion_lab.core.models import ModelRoster
from collusion_lab.scenarios.market.agents.llm import parse_seller_reply


def test_parse_takes_last_object_with_ask():
    assert parse_seller_reply('Sure. {"ask": 72.5} because {reasons}') == {"ask": 72.5}
    assert parse_seller_reply('{"ask": 70} ... final: {"ask": 71}') == {"ask": 71}
    assert parse_seller_reply('{"ask": null}') == {"ask": None}
    assert parse_seller_reply("I think 70 is fair") is None


def test_unparseable_reply_keeps_standing_ask_and_is_logged(tmp_path):
    from collusion_lab.scenarios.market.env import run_market_episode
    roster = ModelRoster("scripted", {"seller": "mockllm/model"})
    replies = iter(['Here you go: {"ask": 80.0}'] * 5 + ["hmm, let me think about the market"] * 10)

    async def gen(role, messages, **k):
        o = ModelOutput.from_content("mockllm/model", next(replies))
        o.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        o.metadata = {"clab_spec": "mockllm/model"}
        roster.meter.add(role, "mockllm/model", 1, 1)
        return o
    roster.generate = gen
    rec = run_market_episode("A0_competitive", 0, tmp_path, 3, roster)
    asks = [json.loads(l) for l in open(tmp_path / rec["episode_id"] / "evidence.jsonl")]
    asks = [e["payload"]["price"] for e in asks if e["kind"] == "action" and e["payload"].get("type") == "ask"
            and e["actor"].startswith("S")]
    assert asks == [80.0] * 15                       # rounds 2-3 keep the standing ask, not a withdrawal
    assert rec["seller_parse_failures"] == 10
    raw = (tmp_path / rec["episode_id"] / "llm_raw.jsonl").read_text().splitlines()
    assert len(raw) == 15 and json.loads(raw[-1])["parsed"] is None
