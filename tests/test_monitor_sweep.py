import json

import pandas as pd

from collusion_lab.eval import monitor_sweep as MS


def _rows(arm, model, mon, scores):
    out = []
    for i, (s, y) in enumerate(scores):
        out.append({"episode": f"e{i}", "scenario": "swe", "task": "T3", "category": "x", "collusive": y,
                    "harm": y, "flagged": s > 0.5, "monitor": mon, "observability": "full",
                    "collusion_score": s, "signals": json.dumps({}), "judge_arm": arm, "judge_model": model})
    return out


def test_sweep_table_orders_arms_and_scores_each(tmp_path):
    good = [(0.9, True), (0.8, True), (0.1, False), (0.2, False)]
    bad = [(0.4, True), (0.6, True), (0.5, False), (0.7, False)]
    df = pd.DataFrame(_rows("higher", "big", "M2", good) + _rows("lower", "small", "M2", bad)
                      + _rows("same", "mid", "M2", good) + _rows("n/a", "none", "M3", good))
    df["judge_failed"] = False
    t = MS.sweep_table(df)
    m2 = t[t.monitor == "M2"]
    assert list(m2["judge arm"]) == ["lower", "same", "higher"]
    assert m2.set_index("judge arm").loc["higher", "collusion AUROC"] == 1.0
    assert m2.set_index("judge arm").loc["lower", "collusion AUROC"] < 0.5
    out = MS.build_sweep_report(df, tmp_path, {"lower": "small", "same": "mid", "higher": "big"}, {"mid": 10})
    assert (tmp_path / "fig_monitor_sweep.png").exists() and len(out)
    assert "M3 (no LLM) 1.00" in (tmp_path / "monitor_sweep.md").read_text()


def test_run_sweep_pins_one_judge_per_arm(monkeypatch, tmp_path):
    calls = []

    def fake_replay(d, monitors, obs, profile, workers=2, overrides=None, tasks=None, out_name=None):
        calls.append((tuple(monitors), profile, overrides, tasks, out_name))
        return pd.DataFrame(_rows("?", "?", monitors[0], [(0.9, True), (0.1, False)])).drop(
            columns=["judge_arm", "judge_model"])
    import collusion_lab.experiments as E
    monkeypatch.setattr(E, "replay", fake_replay)
    df = MS.run_sweep([tmp_path], {"lower": "ollama/qwen2.5:0.5b", "higher": "groq/x"}, tasks=["T3"])
    assert calls[0][0] == MS.REFERENCE_MONITORS and calls[0][2] is None
    assert [c[2] for c in calls[1:]] == [{"monitor_judge": "ollama/qwen2.5:0.5b"}, {"monitor_judge": "groq/x"}]
    assert all(c[3] == ["T3"] and c[4] is None for c in calls)        # task filter; never overwrites decisions.csv
    assert set(df.judge_arm) == {"n/a", "lower", "higher"}
