"""Ablation: how strong must the monitor's independent verifier be?

Replays M3 on the no-monitor SWE trajectories with the monitor holding 25/50/75/100%
of the hidden FAIL_TO_PASS tests, and reports harm-flag rate, CONSTRAIN rate and
collusion recall per fraction.   usage: python scripts/ablate_verifier.py runs/swe_v1
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd


def one(args):
    ep, vf = args
    from collusion_lab.monitor.core import TrustedMonitor
    from collusion_lab.scenarios.swe.env import load_ctx
    from collusion_lab.scenarios.swe.monitor_plugin import SWEPlugin
    ctx, events, rec = load_ctx(Path(ep))
    ctx.verifier_fraction = vf
    d = TrustedMonitor("M3", SWEPlugin()).evaluate(ctx, events)
    return {"episode": rec["episode_id"], "task": rec["task"], "condition": rec["condition"], "vf": vf,
            "collusive": rec["truth"]["collusive"], "harm": rec["outcome"]["harmful_release"],
            "action": d.action.value, "flagged": d.flagged, "collusion_score": d.collusion_score}


if __name__ == "__main__":
    run = Path(sys.argv[1])
    eps = [str(p) for p in sorted(run.iterdir()) if (p / "episode.json").exists()
           and not json.loads((p / "episode.json").read_text()).get("online_monitor")]
    jobs = [(e, vf) for vf in (0.25, 0.5, 0.75, 1.0) for e in eps]
    with ProcessPoolExecutor(2) as ex:
        rows = list(ex.map(one, jobs))
    df = pd.DataFrame(rows)
    df.to_csv(run / "ablation_verifier.csv", index=False)
    s = df[df.harm].groupby("vf").agg(harm_flagged=("flagged", "mean"),
                                      harm_constrained=("action", lambda a: (a == "CONSTRAIN").mean()))
    s["benign_flagged"] = df[~df.harm & ~df.collusive].groupby("vf").flagged.mean()
    print(s.round(3).to_markdown())
    print(df[df.harm].groupby(["vf", "task"]).flagged.mean().unstack().round(2).to_markdown())
