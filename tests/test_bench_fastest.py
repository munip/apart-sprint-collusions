import json
import time

from collusion_lab.core import bench as B
from collusion_lab.core import pool as P


def test_pick_fastest_requires_reliability():
    rows = [{"spec": "a/fast-but-rambles", "median_s": 0.5, "fail_rate": 0.0, "json_ok": 0.33, "tool_ok": 1.0, "score": 20.5},
            {"spec": "b/fast-but-429", "median_s": 0.4, "fail_rate": 0.5, "json_ok": 1.0, "tool_ok": 1.0, "score": 0.8},
            {"spec": "c/steady", "median_s": 3.0, "fail_rate": 0.0, "json_ok": 1.0, "tool_ok": 1.0, "score": 3.0},
            {"spec": "d/slow", "median_s": 9.0, "fail_rate": 0.0, "json_ok": 1.0, "tool_ok": 1.0, "score": 9.0}]
    assert B.pick_fastest(rows)["spec"] == "c/steady"
    assert B.pick_fastest(rows[:2]) is None


def test_bench_scores_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "BENCH_FILE", tmp_path / "b.json")
    monkeypatch.setattr(B, "get_inspect_model", lambda r: r.spec)

    async def fake_call(model, kind, timeout):
        if model == "groq/flaky":
            return (None, False, "RateLimitError") if kind == "tool" else (0.2, True, "")
        return (1.0 if model == "groq/quick" else 4.0), True, ""
    monkeypatch.setattr(B, "_call", fake_call)
    rows = B.bench(["groq/slow", "groq/quick", "groq/flaky"], n=4)
    assert [r["spec"] for r in rows][0] == "groq/quick"
    assert B.pick_fastest(rows)["spec"] == "groq/quick"
    assert B.cached()[0]["spec"] == "groq/quick"


def test_auto_fastest_pins_every_agent_to_one_model_and_judge_to_another_family(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "BENCH_FILE", tmp_path / "b.json")
    (tmp_path / "b.json").write_text(json.dumps({"created": time.time(), "results": [
        {"spec": "cerebras/qwen-3.8-27b", "family": "qwen", "median_s": 1.2, "fail_rate": 0.0, "json_ok": 1.0,
         "tool_ok": 1.0, "score": 1.2}]}))
    pool = [P.Candidate("cerebras/qwen-3.8-27b", "cerebras", "qwen-3.8-27b", "qwen", "x", ok=True, tools="native", score=5),
            P.Candidate("groq/openai/gpt-oss-120b", "groq", "openai/gpt-oss-120b", "gpt", "x", ok=True, tools="native", score=4)]
    monkeypatch.setattr(P, "discover", lambda *a, **k: pool)
    out = P.expand_auto({"default": "auto:fastest", "monitor_judge": "auto:judge", "qa_peer": "auto:judge"}, {})
    assert out["implementer"] == out["seller"] == ["cerebras/qwen-3.8-27b"]
    assert out["monitor_judge"] == out["qa_peer"] == ["groq/openai/gpt-oss-120b"]
