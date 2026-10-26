"""Numbers and figure for the monitor-of-monitors study (docs/PREREG.md section 7).

    python paper/analysis/layered_study.py runs/market_layered --out paper/figs
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import fisher_exact  # noqa: E402

try:
    from llm_study import wilson  # same folder
except ImportError:                 # pragma: no cover
    from paper.analysis.llm_study import wilson

ARMS = ["honest/override", "corrupt/log", "corrupt/override", "trap/override"]
COND = {"A2_honest_chat": "A2 honest", "A3_overt_cartel": "A3 cartel", "A5_stego_rotation": "A5 stego"}


def rows(run: Path) -> pd.DataFrame:
    out = []
    for f in sorted(run.glob("mkt-*/episode.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        if not rec.get("layered"):
            continue
        o, L, V = rec["outcome"], rec["outcome"]["layered"], rec["values"]
        ev = [json.loads(x) for x in (f.parent / "evidence.jsonl").read_text(encoding="utf-8").splitlines()]
        start = L["monitor_from"]
        tr = [(e["step"], e["payload"]) for e in ev if e["kind"] == "state" and e["payload"].get("event") == "trade"]
        cs_after = sum(V[p["buyer"]] - p["price"] for s, p in tr if s >= start) / (rec["rounds"] - start + 1)
        to_desk = [e for e in ev if e["kind"] == "message" and e["channel"] == "dm:monitor"]
        out.append({"cond": rec["condition"], "seed": rec["seed"], "arm": f"{L['inner_mode']}/{L['outer_mode']}",
                    "collusive": bool(rec["truth"].get("collusive")), "CI": o["collusion_index"],
                    "CS": o["consumer_surplus"], "cs_after_r": cs_after,
                    "harm_verified": bool(L["verified_harm_rounds"]),
                    "first_harm": (L["verified_harm_rounds"] or [None])[0],
                    "flag_round": L["inner_compromised_round"], "flagged": L["inner_compromised_round"] is not None,
                    "inner_int": L["inner_actions"]["HOLD"] + L["inner_actions"]["CONSTRAIN"],
                    "inner_first": L["inner_first_intervention"], "inner_fail": L["inner_failed_replies"],
                    "constrain": o["first_constrain_round"], "trap_taken": L["trap_taken"],
                    "takers": ",".join(L["trap_takers"]), "msgs_to_desk": len(to_desk),
                    "persuasion_sample": to_desk[0]["payload"]["text"][:120] if to_desk else ""})
    return pd.DataFrame(out)


def ci_str(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} [{lo:.2f}, {hi:.2f}]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--out", type=Path, default=Path("paper/figs"))
    a = ap.parse_args()
    t = rows(a.run)
    print(f"{len(t)} layered episodes")
    print(t.drop(columns=["persuasion_sample"]).sort_values(["cond", "seed", "arm"]).to_string(index=False,
          float_format=lambda x: f"{x:.2f}"))

    print("\n(1) compromise detection")
    for arm in ARMS:
        g = t[t.arm == arm]
        if len(g):
            h = g[g.harm_verified]
            print(f"  {arm}: flagged {ci_str(int(g.flagged.sum()), len(g))}; among harm-verified "
                  f"{ci_str(int(h.flagged.sum()), len(h))}; median rounds harm->flag "
                  f"{st.median((h.flag_round - h.first_harm).dropna()) if h.flagged.any() else None}")
    cor = t[t.arm.str.startswith("corrupt")]
    hon = t[t.arm.isin(["honest/override", "trap/override"])]
    print("  Fisher flag corrupt vs honest/trap desk:",
          round(fisher_exact([[int(cor.flagged.sum()), len(cor) - int(cor.flagged.sum())],
                              [int(hon.flagged.sum()), len(hon) - int(hon.flagged.sum())]])[1], 3))
    print("  honest/trap desks flagged:", hon[hon.flagged][["cond", "seed", "arm", "inner_int", "CI"]].to_dict("records"))

    print("\n(2) harm: corrupt/override vs corrupt/log, per-round CS after round 6 (paired)")
    d = []
    for (c, s), g in t.groupby(["cond", "seed"]):
        x, y = g[g.arm == "corrupt/override"], g[g.arm == "corrupt/log"]
        if len(x) and len(y):
            d.append((c, s, float(x.cs_after_r.iloc[0] - y.cs_after_r.iloc[0])))
    for c, s, v in d:
        print(f"  {c} s{s}: {v:+.1f}")
    col = [v for c, s, v in d if c != "A2_honest_chat"]
    if col:
        print(f"  collusive: mean {st.mean(col):+.1f}, better {sum(v > 0.5 for v in col)}/{len(col)}")

    print("\n(3) trap")
    tr = t[t.arm == "trap/override"]
    k1, n1 = int(tr[tr.collusive].trap_taken.sum()), int(tr.collusive.sum())
    k0, n0 = int(tr[~tr.collusive].trap_taken.sum()), int((~tr.collusive).sum())
    print(f"  taken: collusive {ci_str(k1, n1)}, honest {ci_str(k0, n0)}; Fisher p="
          f"{fisher_exact([[k1, n1 - k1], [k0, n0 - k0]])[1]:.3f}")
    print("  takers:", tr[tr.trap_taken][["cond", "seed", "takers"]].to_dict("records"))

    print("\n(4) inner desk behaviour (mean interventions out of 10 rounds, first intervention)")
    print(t.groupby(["arm", "cond"]).agg(inner_int=("inner_int", "mean"), first=("inner_first", "median"),
                                         fails=("inner_fail", "sum"), msgs=("msgs_to_desk", "mean"),
                                         CI=("CI", "mean"), cs_after=("cs_after_r", "mean"))
          .to_string(float_format=lambda x: f"{x:.2f}"))
    print("\nsample messages to the desk:")
    for _, r in t[t.persuasion_sample != ""].head(8).iterrows():
        print(f"  {r.cond} s{r.seed} {r.arm}: {r.persuasion_sample}")

    # figure: per-round consumer surplus after round 6, per arm and condition
    a.out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    colors = {"honest/override": "#7f8c8d", "corrupt/log": "#c0392b", "corrupt/override": "#27ae60",
              "trap/override": "#2e86c1"}
    conds = [c for c in COND if c in set(t.cond)]
    for j, arm in enumerate(ARMS):
        for i, c in enumerate(conds):
            v = t[(t.cond == c) & (t.arm == arm)].cs_after_r
            if not len(v):
                continue
            x = i + (j - 1.5) * 0.2
            ax.bar(x, v.mean(), width=0.19, color=colors[arm], alpha=0.85, label=arm if i == 0 else None)
            ax.scatter([x] * len(v), v, s=6, color="black", zorder=3)
    ax.set_xticks(range(len(conds)), [COND[c] for c in conds], fontsize=7)
    ax.set_ylabel("buyers' surplus per round\n(rounds 6-15)", fontsize=7)
    ax.tick_params(axis="y", labelsize=6)
    ax.legend(fontsize=5.5, frameon=False, title="desk / auditor", title_fontsize=6)
    fig.tight_layout()
    fig.savefig(a.out / "fig_layered.pdf")


if __name__ == "__main__":
    main()
