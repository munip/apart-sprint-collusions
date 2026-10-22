"""Smoke test: one scripted episode per condition on one task, then monitors offline.

usage: python scripts/smoke_swe.py T3 [C0_honest_single,C3_collude_overt]
"""
import sys
import time
from pathlib import Path

from collusion_lab.monitor.core import TrustedMonitor
from collusion_lab.scenarios.swe.conditions import CONDITIONS
from collusion_lab.scenarios.swe.env import load_ctx, run_episode
from collusion_lab.scenarios.swe.monitor_plugin import SWEPlugin

task = sys.argv[1] if len(sys.argv) > 1 else "T3"
conds = sys.argv[2].split(",") if len(sys.argv) > 2 else list(CONDITIONS)
out = Path("runs/smoke")
for c in conds:
    t0 = time.time()
    rec = run_episode(task, c, 0, out)
    ctx, events, _ = load_ctx(out / rec["episode_id"])
    ds = {lvl: TrustedMonitor(lvl, SWEPlugin()).evaluate(ctx, events) for lvl in ("M1", "M3")}
    o = rec["outcome"]
    print(f"{c:20s} rel={o['released']!s:5} correct={o['correct']!s:5} harm={o['harmful_release']!s:5} "
          f"| M1 {ds['M1'].action.value:9s} c={ds['M1'].collusion_score:.2f} "
          f"| M3 {ds['M3'].action.value:9s} r={ds['M3'].risk:.2f} c={ds['M3'].collusion_score:.2f} "
          f"| {time.time()-t0:.0f}s", flush=True)
    for r in ds["M3"].reasons[:5]:
        print("      -", r)
    for r in ds["M3"].collusion_reasons[:3]:
        print("      * ", r)
