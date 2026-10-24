"""Numbers for the market probes (docs/PREREG.md section 8).

    python paper/analysis/probes_study.py runs/market_probes
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

import pandas as pd
from scipy.stats import fisher_exact

try:
    from llm_study import wilson
except ImportError:                 # pragma: no cover
    from paper.analysis.llm_study import wilson


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    a = ap.parse_args()
    rows, stings = [], []
    for f in sorted(a.run.glob("mkt-*/episode.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        o, V = rec["outcome"], rec["values"]
        kind = (rec.get("probe") or {}).get("kind", "none")
        ev = [json.loads(x) for x in (f.parent / "evidence.jsonl").read_text(encoding="utf-8").splitlines()]
        inc = [e["payload"] for e in ev if e["kind"] == "state" and e["payload"].get("event") == "trade"
               and e["payload"]["seller"] in rec["costs"] and e["step"] >= 5]
        p = st.mean(x["price"] for x in inc) if inc else None
        ce = sum(o["ce"][:2]) / 2
        rows.append({"cond": rec["condition"], "seed": rec["seed"], "probe": kind,
                     "CI_incumbents": (p - ce) / (o["jpm"][0] - ce) if p else None,
                     "CS": o["consumer_surplus"], "trades": o["trades"]})
        if kind == "sting":
            pr = o["probe"]
            for s in pr["stings"]:
                stings.append({"cond": rec["condition"], "seed": rec["seed"], **s})
            rows[-1].update(natural=f"{pr['natural_followed']}/{pr['natural_n']}")
    t = pd.DataFrame(rows)
    print(t.sort_values(["cond", "seed", "probe"]).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("\nreference vs none (paired):")
    for c, g in t.groupby("cond"):
        d = []
        for s, h in g.groupby("seed"):
            x, y = h[h.probe == "reference"], h[h.probe == "none"]
            if len(x) and len(y):
                d.append((float(x.CS.iloc[0] - y.CS.iloc[0]),
                          float((x.CI_incumbents.iloc[0] or 0) - (y.CI_incumbents.iloc[0] or 0))))
        if d:
            print(f"  {c}: dCS {[round(v[0]) for v in d]} mean {st.mean(v[0] for v in d):+.0f}; "
                  f"dCI {[round(v[1], 2) for v in d]}")
    s = pd.DataFrame(stings)
    if len(s):
        print("\nsting followed (per sting hour):")
        for c, g in s.groupby("cond"):
            k, n = int(g.followed.sum()), len(g)
            lo, hi = wilson(k, n)
            print(f"  {c}: {k}/{n} [{lo:.2f}, {hi:.2f}]")
        a5 = s[s.cond == "A5_stego_rotation"]
        ctl = s[s.cond != "A5_stego_rotation"]
        if len(a5) and len(ctl):
            p = fisher_exact([[int(a5.followed.sum()), len(a5) - int(a5.followed.sum())],
                              [int(ctl.followed.sum()), len(ctl) - int(ctl.followed.sum())]])[1]
            print(f"  Fisher A5 vs controls: p={p:.3f}")


if __name__ == "__main__":
    main()
