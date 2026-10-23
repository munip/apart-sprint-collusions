"""Dynamic free-model pool: FCM config parsing and role assignment (no network)."""
import json

from collusion_lab.core import pool as PL
from collusion_lab.core.pool import Candidate, assign
from collusion_lab.core.providers import family

FCM = {"apiKeys": {"nvidia": "nvapi-xxxxxxxxxxxx", "groq": "gsk_xxxxxxxxxxxx", "openrouter": "sk-or-xxxxxxxxxx",
                   "pollinations": "sk_xxxxxxxxxxxx"},
       "router": {"sets": {"fast-coding": {"models": [
           {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b", "priority": 5},
           {"provider": "openrouter", "model": "xingchen-agi/xing4.0-29b-a4b:free", "priority": 2}]}},
           "prePrompt": {"enabled": True, "text": "You are free-coding-models"}}}


def C(spec, tools="native", score=5.0, ok=True):
    p, m = spec.split("/", 1)
    return Candidate(spec, p, m, family(m), "test", ok=ok, tools=tools, score=score)


def test_fcm_keys_and_injection(tmp_path, monkeypatch):
    f = tmp_path / "fcm.json"
    f.write_text(json.dumps(FCM))
    monkeypatch.setenv("FCM_CONFIG", str(f))
    for k in ("NVIDIA_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "POLLINATIONS_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert set(PL.fcm_keys()) == {"nvidia", "groq", "openrouter", "pollinations"}
    applied = PL.inject_fcm_keys()
    assert applied["groq"] == "GROQ_API_KEY"
    import os
    assert os.environ["NVIDIA_API_KEY"].startswith("nvapi-")
    assert [m["model"] for m in PL.fcm_router_sets()["fast-coding"]][0].startswith("nvidia/nemotron")


def test_assign_keeps_monitor_family_out_of_agent_chains():
    pool = [C("nvidia/qwen/qwen3-coder-480b-a35b-instruct", score=9), C("groq/openai/gpt-oss-120b", score=8),
            C("groq/llama-3.3-70b-versatile", score=7), C("openrouter/deepseek/deepseek-chat-v3.1:free", score=6),
            C("nvidia/meta/llama-3.1-405b-instruct", score=5), C("ollama/gemma2:2b", tools="json-only", score=0)]
    roles = {"implementer": "auto:coder", "tester": "auto:coder", "reviewer": "auto:agent",
             "planner": "auto:agent", "seller": "auto:chat", "monitor_judge": "auto:judge"}
    out = assign(roles, pool, chain_length=3, last_resort=["ollama/gemma2:2b"])
    mon_fams = {family(s.split("/", 1)[1]) for s in out["monitor_judge"]}
    for r, chain in out.items():
        if r != "monitor_judge":
            assert not ({family(s.split("/", 1)[1]) for s in chain} & mon_fams), (r, chain)
    # diverse primaries across agent roles
    prim = [family(out[r][0].split("/", 1)[1]) for r in ("implementer", "tester", "reviewer")]
    assert len(set(prim)) == 3
    assert out["implementer"][-1] == "ollama/gemma2:2b"     # local fallback tail


def test_assign_with_pinned_monitor_excludes_its_family():
    pool = [C("groq/llama-3.3-70b-versatile"), C("groq/openai/gpt-oss-120b"), C("ollama/gemma2:2b")]
    out = assign({"implementer": "auto:coder"}, pool, last_resort=["ollama/gemma2:2b"], monitor_family="gemma")
    assert "ollama/gemma2:2b" not in out["implementer"]


def test_failed_probes_are_never_assigned():
    pool = [C("groq/openai/gpt-oss-120b", ok=False, score=-1e9), C("groq/llama-3.3-70b-versatile")]
    out = assign({"tester": "auto:coder"}, pool)
    assert out["tester"] == ["groq/llama-3.3-70b-versatile"]
