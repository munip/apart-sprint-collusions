"""Experiment runner: episode matrices (paired no-monitor / online-monitor) and the
offline replay that scores every monitor x observability on identical trajectories."""
from __future__ import annotations

import json
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .core.models import ModelRoster

OBS_PRESETS = ("full", "artifacts_only", "transcript_only", "no_dm")


# ---------------------------------------------------------------------------- run
def _swe_job(args: dict) -> dict:
    from .scenarios.swe.env import run_episode
    try:
        roster = ModelRoster(args["profile"], args.get("overrides"), cap_usd=args.get("cap"))
        rec = run_episode(args["task"], args["condition"], args["seed"], Path(args["out"]), roster,
                          args.get("online"), args.get("verifier_fraction", 0.5), pressure=args.get("pressure"),
                          peer=args.get("peer"))
        return {"ok": True, "episode": rec["episode_id"], "cost": rec["cost"]["usd"]}
    except Exception as e:  # keep the matrix going
        return {"ok": False, "job": args, "error": f"{e}\n{traceback.format_exc()[-1500:]}"}


def _mkt_job(args: dict) -> dict:
    from .scenarios.market.env import run_market_episode
    try:
        roster = ModelRoster(args["profile"], args.get("overrides"), cap_usd=args.get("cap"))
        rec = run_market_episode(args["condition"], args["seed"], Path(args["out"]), args.get("rounds", 30),
                                 roster, args.get("online"), args.get("intervention", "entrant"),
                                 pressure=args.get("pressure"))
        return {"ok": True, "episode": rec["episode_id"], "cost": rec["cost"]["usd"]}
    except Exception as e:
        return {"ok": False, "job": args, "error": f"{e}\n{traceback.format_exc()[-1500:]}"}


def run_matrix(cfg: dict[str, Any], out: Path, workers: int = 2) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(yaml.safe_dump(cfg))
    jobs, fn = [], None
    common = dict(profile=cfg.get("profile", "scripted"), overrides=cfg.get("overrides"),
                  cap=cfg.get("cap_usd"), out=str(out))
    online_list = [None] + list(cfg.get("online_monitors", []))
    from .core.pressure import Pressure, parse_list
    pressures = parse_list(cfg.get("pressures"))      # factor; default [none] (ids unchanged)
    if any(p.active for p in pressures) and str(cfg.get("profile", "scripted")) == "scripted":
        print("note: pressures only bind LLM agents; scripted agents ignore them", flush=True)
    if cfg["scenario"] == "swe":
        fn = _swe_job
        from .scenarios.swe.peer import PeerSpec
        peers = [PeerSpec.parse(x).name for x in (cfg.get("peers") or ["none"])]   # trusted-peer factor
        gate_arms = cfg.get("gate_arms")     # optional explicit (peer, online) pairs instead of the full cross
        for t in cfg["tasks"]:
            for c in cfg["conditions"]:
                for s in cfg["seeds"]:
                    for p in pressures:
                        arms = ([(a.get("peer", "none"), a.get("online")) for a in gate_arms] if gate_arms
                                else [(q, m) for q in peers for m in online_list])
                        for q, m in arms:
                            jobs.append(dict(common, task=t, condition=c, seed=s, online=m, pressure=p.to_dict(),
                                             peer=q, verifier_fraction=cfg.get("verifier_fraction", 0.5)))
    else:
        fn = _mkt_job
        for c in cfg["conditions"]:
            for s in cfg["seeds"]:
                for p in pressures:
                    for m in online_list:
                        for iv in (cfg.get("interventions", ["entrant"]) if m else ["entrant"]):
                            jobs.append(dict(common, condition=c, seed=s, online=m, intervention=iv,
                                             rounds=cfg.get("rounds", 30), pressure=p.to_dict()))
    # resumable: skip jobs whose episode already exists
    def _eid(j):
        p = Pressure.parse(j.get("pressure"))
        if cfg["scenario"] == "swe":
            from .scenarios.swe.env import swe_episode_id
            from .scenarios.swe.peer import PeerSpec
            return swe_episode_id(j["task"], j["condition"], j["seed"], j.get("online"), p,
                                  PeerSpec.parse(j.get("peer")))
        from .scenarios.market.env import market_episode_id
        return market_episode_id(j["condition"], j["seed"], j.get("online"), j["intervention"], p)
    before = len(jobs)
    jobs = [j for j in jobs if not (out / _eid(j) / "episode.json").exists()]
    print(f"{before - len(jobs)} episodes already done, {len(jobs)} to run", flush=True)
    results = []
    def report(i, r):
        results.append(r)
        status = (f"{r.get('episode')}  (${r.get('cost', 0):.4f})" if r["ok"]
                  else "FAILED " + r["error"].splitlines()[0])
        print(f"[{i}/{len(jobs)}] done: {status}", flush=True)
    if workers <= 1:
        for i, j in enumerate(jobs, 1):
            print(f"[{i}/{len(jobs)}] starting {j.get('task', '')} {j['condition']} seed {j['seed']}"
                  f" pressure {j['pressure']['name']} peer {j.get('peer', 'none')} gate {j.get('online') or '-'}",
                  flush=True)
            report(i, fn(j))
    else:
        with ProcessPoolExecutor(workers) as ex:
            futs = [ex.submit(fn, j) for j in jobs]
            for i, f in enumerate(as_completed(futs), 1):
                report(i, f.result())
    (out / "run_log.json").write_text(json.dumps(results, indent=1))
    return results


# ------------------------------------------------------------------------- replay
def _replay_one(args: dict) -> list[dict]:
    from .monitor.core import TrustedMonitor
    ep = Path(args["ep"])
    rec = json.loads((ep / "episode.json").read_text())
    roster = ModelRoster(args["profile"], args.get("overrides")) if args.get("profile") else None
    if rec["scenario"] == "swe":
        from .scenarios.swe.env import load_ctx
        from .scenarios.swe.monitor_plugin import SWEPlugin
        from .scenarios.swe.conditions import get
        ctx, events, rec = load_ctx(ep, roster)
        plugin = SWEPlugin()
        colluders = list(get(rec["condition"]).colluders)
        harm = rec["outcome"]["harmful_release"] or (rec["outcome"]["release_requested"]
                                                      and not rec["outcome"]["correct"])
        total_steps = rec["outcome"]["steps"]
    else:
        from .scenarios.market.env import load_ctx
        from .scenarios.market.monitor_plugin import MarketPlugin
        ctx, events, rec = load_ctx(ep, roster)
        plugin = MarketPlugin()
        colluders = list(rec["costs"]) if rec["truth"]["collusive"] else []
        harm = rec["outcome"]["harmful"]
        total_steps = rec["rounds"]
    from .eval.occurrence import occurred
    did_occur, how = occurred(rec, events)
    rows = []
    for lvl in args["monitors"]:
        for obs in args["observability"]:
            if lvl == "M2" and (roster is None or roster.is_scripted("monitor_judge")):
                continue
            if lvl in ("M0",) and obs != "full":
                continue
            d = TrustedMonitor(lvl, plugin, observability=obs).evaluate(ctx, events)
            rows.append({
                "episode": rec["episode_id"], "scenario": rec["scenario"], "task": rec.get("task", "market"),
                "condition": rec["condition"], "seed": rec["seed"], "category": rec["truth"]["category"],
                "pressure": (rec.get("pressure") or {}).get("name", "none"),
                "peer": (rec.get("peer") or {}).get("mode", "none"),
                "mechanism": rec["truth"]["mechanism"], "collusive": rec["truth"]["collusive"],
                "instructed": rec["truth"]["collusive"], "occurred": did_occur, "occurred_how": how,
                "harm": bool(harm), "monitor": lvl, "observability": obs, "action": d.action.value,
                "flagged": d.flagged, "risk": d.risk, "collusion_score": d.collusion_score,
                "first_step": d.step, "total_steps": total_steps,
                "attribution": json.dumps(d.attribution), "colluders": json.dumps(colluders),
                "signals": json.dumps({s.name: round(s.score, 3) for s in d.signals}),
                "verified": json.dumps(sorted(s.name for s in d.signals if s.verified and s.score > 0)),
                "reasons": json.dumps(d.reasons[:8]),
                "collusion_reasons": json.dumps(d.collusion_reasons[:8]),
            })
    return rows


def replay(run_dir: Path, monitors=("M0", "M1", "M2", "M3", "M4"), observability=OBS_PRESETS,
           profile: str | None = None, workers: int = 2, overrides: dict[str, str] | None = None,
           tasks: list[str] | None = None, out_name: str | None = "decisions.csv") -> pd.DataFrame:
    """Score monitors offline on the stored no-monitor trajectories. `overrides` pins roles
    (e.g. {"monitor_judge": spec}); `tasks` filters SWE tasks; out_name=None skips writing."""
    eps = []
    for p in sorted(run_dir.iterdir()):
        if not (p / "episode.json").exists():
            continue
        rec = json.loads((p / "episode.json").read_text())
        if rec.get("online_monitor"):
            continue                          # offline replay only on no-monitor trajectories
        if tasks and rec.get("scenario") == "swe" and rec.get("task") not in tasks:
            continue
        eps.append(str(p))
    rows: list[dict] = []
    if overrides and not profile:
        profile = "scripted"                  # overrides need a base profile
    jobs = [dict(ep=e, monitors=list(monitors), observability=list(observability), profile=profile,
                 overrides=overrides) for e in eps]
    print(f"replaying {len(jobs)} episode(s) x {len(monitors)} monitors x {len(observability)} views"
          + (f" (LLM judge from profile '{profile}')" if profile else ""), flush=True)
    if workers <= 1 or profile:
        # with an LLM judge: sequential, so free-tier rate limits are shared and progress is visible
        for i, j in enumerate(jobs, 1):
            print(f"[{i}/{len(jobs)}] {Path(j['ep']).name}", flush=True)
            rows += _replay_one(j)
    else:
        with ProcessPoolExecutor(workers) as ex:
            for i, f in enumerate(as_completed([ex.submit(_replay_one, j) for j in jobs]), 1):
                rows += f.result()
                print(f"[{i}/{len(jobs)}] replayed", flush=True)
    df = pd.DataFrame(rows)
    if out_name:
        df.to_csv(run_dir / out_name, index=False)
    return df


def episodes_table(run_dir: Path) -> pd.DataFrame:
    rows = []
    for p in sorted(run_dir.iterdir()):
        f = p / "episode.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        o = r["outcome"]
        rows.append({"episode": r["episode_id"], "scenario": r["scenario"], "task": r.get("task", "market"),
                     "condition": r["condition"], "seed": r["seed"], "online": r.get("online_monitor"),
                     "pressure": (r.get("pressure") or {}).get("name", "none"),
                     "peer": (r.get("peer") or {}).get("mode", "none") if isinstance(r.get("peer"), dict) else "none",
                     "intervention": r.get("intervention"), "collusive": r["truth"]["collusive"],
                     "category": r["truth"]["category"], "mechanism": r["truth"]["mechanism"],
                     "cost_usd": r["cost"]["usd"], "llm_calls": r["cost"].get("calls", 0),
                     **{f"o_{k}": v for k, v in o.items() if not isinstance(v, (list, dict))},
                     # actor lists (trusted-peer outcomes) as ';'-joined strings + derived flags
                     **{f"o_{k}": ";".join(v) for k, v in o.items()
                        if isinstance(v, list) and all(isinstance(x, str) for x in v)},
                     **({"o_probe_reciprocated": bool(o.get("probe_reciprocators")),
                         "o_probe_replied": bool(o.get("probe_replies")),
                         "o_skip_after_checkpoint": bool(o.get("skip_after_checkpoint_by")),
                         "o_qa_last_failing": (len(o["qa_reports"][-1]["failing"]) if o.get("qa_reports") else None)}
                        if r["scenario"] == "swe" and "peer" in o else {})})
    df = pd.DataFrame(rows)
    df.to_csv(run_dir / "episodes.csv", index=False)
    return df
