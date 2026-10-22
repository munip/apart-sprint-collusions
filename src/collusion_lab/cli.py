"""clab — command line entry point.

  clab build-tasks                         # (re)build FastAPI task set from upstream commits
  clab run configs/experiments/swe_matrix.yaml --out runs/swe_v1 [--profile cloud] [--workers 2]
  clab replay runs/swe_v1 [--profile cloud]   # score all monitors x observability offline
  clab report runs/swe_v1 runs/market_v1 --out reports/v1
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from dotenv import load_dotenv


def _overrides(items: list[str] | None) -> dict[str, str]:
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k] = v
    return out


def main(argv: list[str] | None = None) -> None:
    load_dotenv()  # ANTHROPIC_API_KEY / OPENAI_API_KEY / OLLAMA_BASE_URL from .env (never committed)
    ap = argparse.ArgumentParser(prog="clab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-tasks")
    r = sub.add_parser("run")
    r.add_argument("config")
    r.add_argument("--out", required=True)
    r.add_argument("--profile")
    r.add_argument("--role", action="append", help="role=model override, repeatable")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--seeds", type=int, nargs="*")
    r.add_argument("--cap-usd", type=float)
    rp = sub.add_parser("replay")
    rp.add_argument("run_dir")
    rp.add_argument("--profile", help="profile providing monitor_judge for M2/M4 (default: no LLM judge)")
    rp.add_argument("--monitors", nargs="*", default=["M0", "M1", "M2", "M3", "M4"])
    rp.add_argument("--observability", nargs="*")
    rp.add_argument("--workers", type=int, default=2)
    rep = sub.add_parser("report")
    rep.add_argument("run_dirs", nargs="+")
    rep.add_argument("--out", required=True)
    rep.add_argument("--fpr", type=float, default=0.1)
    a = ap.parse_args(argv)

    if a.cmd == "build-tasks":
        from .scenarios.swe.taskbuilder import main as build
        build()
    elif a.cmd == "run":
        from .experiments import episodes_table, run_matrix
        cfg = yaml.safe_load(Path(a.config).read_text())
        if a.profile:
            cfg["profile"] = a.profile
        if a.role:
            cfg["overrides"] = {**cfg.get("overrides", {}), **_overrides(a.role)}
        if a.seeds:
            cfg["seeds"] = a.seeds
        if a.cap_usd is not None:
            cfg["cap_usd"] = a.cap_usd
        run_matrix(cfg, Path(a.out), a.workers)
        episodes_table(Path(a.out))
    elif a.cmd == "replay":
        from .experiments import OBS_PRESETS, episodes_table, replay
        df = replay(Path(a.run_dir), a.monitors, a.observability or OBS_PRESETS, a.profile, a.workers)
        episodes_table(Path(a.run_dir))
        print(f"{len(df)} decisions -> {a.run_dir}/decisions.csv")
    elif a.cmd == "report":
        from .eval.report import build_report
        tables = build_report([Path(d) for d in a.run_dirs], Path(a.out), a.fpr)
        print((Path(a.out) / "tables.md").read_text()[:6000])


if __name__ == "__main__":
    main()
