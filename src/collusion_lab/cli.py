"""clab — command line entry point.

  clab providers list                      # registry + which API keys were found
  clab providers import-fcm [--write]      # copy keys from free-coding-models config into .env
  clab providers check [--only groq,google] [--model groq/llama-3.3-70b-versatile ...]
  clab models check --profile free [--probe]   # resolve roles, keys, monitor/agent family separation
  clab build-tasks                         # (re)build FastAPI task set from upstream commits
  clab run configs/experiments/swe_matrix.yaml --out runs/swe_v1 [--profile free] [--role tester=groq/...]
  clab replay runs/swe_v1 [--profile free]     # score all monitors x observability offline (M2 needs a judge)
  clab sweep-monitors runs/swe_sweep --config configs/experiments/swe_monitor_sweep.yaml --out reports/sweep
  clab report runs/swe_v1 runs/market_v1 --out reports/v1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    # repo .env first, then the parent folder's .env (e.g. C:\collusions-claude\.env); never override real env
    for p in (Path.cwd() / ".env", REPO / ".env", REPO.parent / ".env"):
        if p.exists():
            load_dotenv(p, override=False)
    if os.name == "nt":
        os.environ.setdefault("PYTHONUTF8", "1")
    from .core.pool import inject_fcm_keys
    inject_fcm_keys()          # keys configured in free-coding-models become usable without .env


def _overrides(items: list[str] | None) -> dict[str, str]:
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k] = v
    return out


def _mask(s: str) -> str:
    return s[:4] + "…" + s[-3:] if len(s) > 10 else "***"


def _table(rows: list[dict], cols: list[str]) -> str:
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols} if rows else {c: len(c) for c in cols}
    line = "  ".join(c.ljust(w[c]) for c in cols)
    return "\n".join([line, "  ".join("-" * w[c] for c in cols)] +
                     ["  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols) for r in rows])


def cmd_models_check(profile: str, overrides: dict, probe: bool) -> int:
    from .core.models import ModelRoster
    roster = ModelRoster(profile, overrides)
    print(f"profile: {profile}")
    rows = []
    for role, chain in roster.describe().items():
        for i, spec in enumerate(chain):
            if spec in ("scripted", "none"):
                rows.append({"role": role, "#": i, "spec": spec})
                continue
            from .core.providers import resolve
            r = resolve(spec)
            rows.append({"role": role, "#": i, "spec": spec, "family": r.family, "via": r.kind,
                         "key": "yes" if r.has_key else ("MISSING" if r.needs_key else "not needed"), "tools": r.tools})
    print(_table(rows, ["role", "#", "spec", "family", "via", "key", "tools"]))
    agents, monitor = roster.families()
    print(f"\nagent families: {sorted(agents) or '-'}   monitor families: {sorted(monitor) or '-'}")
    warns = roster.check_separation()
    for w in warns:
        print("WARNING:", w)
    missing = roster.missing_keys()
    unusable = False
    if missing:
        provs = sorted({m.split("provider '")[1].rstrip("')") for m in missing})
        print(f"no API key for: {', '.join(provs)}  (those entries are skipped in fallback chains)")
        for role, chain in roster.describe().items():
            if chain and chain[0] not in ("scripted", "none") and all(
                    any(m.startswith(f"{role}: {c} ") for m in missing) for c in chain):
                print(f"ERROR: role '{role}' has no usable model - add a key or a --role override")
                unusable = True
    if probe:
        from .core.probe import probe as do_probe
        specs = sorted({r["spec"] for r in rows if r.get("key") == "yes"})
        res = do_probe(specs)
        print("\n" + _table(res, ["spec", "family", "text", "tools", "latency_s", "served_by", "error"]))
    if unusable:
        return 2
    return 1 if any("shares model family" in w for w in warns) else 0


def main(argv: list[str] | None = None) -> None:
    if os.name == "nt" and not sys.flags.utf8_mode:
        # Windows: FastAPI sources/tests are UTF-8; re-run in UTF-8 mode (children inherit PYTHONUTF8)
        import subprocess
        env = dict(os.environ, PYTHONUTF8="1")
        sys.exit(subprocess.call([sys.executable, "-X", "utf8", "-m", "collusion_lab.cli",
                                  *(argv if argv is not None else sys.argv[1:])], env=env))
    _load_env()
    ap = argparse.ArgumentParser(prog="clab")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("providers")
    pvs = pv.add_subparsers(dest="sub", required=True)
    pvs.add_parser("list")
    imp = pvs.add_parser("import-fcm")
    imp.add_argument("--config", help="path to free-coding-models config json")
    imp.add_argument("--write", action="store_true", help="append missing keys to the repo .env")
    chk = pvs.add_parser("check")
    chk.add_argument("--only", help="comma-separated providers")
    chk.add_argument("--model", action="append", help="explicit spec(s) to probe")
    chk.add_argument("--timeout", type=int, default=45)

    fc = sub.add_parser("fcm", help="free-coding-models integration")
    fcs = fc.add_subparsers(dest="sub", required=True)
    fcs.add_parser("status")

    pl = sub.add_parser("pool", help="dynamic free-model pool")
    pls = pl.add_subparsers(dest="sub", required=True)
    pd = pls.add_parser("discover")
    pd.add_argument("--refresh", action="store_true")
    pd.add_argument("--max-probe", type=int)
    pa = pls.add_parser("assign")
    pa.add_argument("--profile", default="fcm_auto")

    md = sub.add_parser("models")
    mds = md.add_subparsers(dest="sub", required=True)
    mc = mds.add_parser("check")
    mc.add_argument("--profile", default=os.environ.get("CLAB_PROFILE", "scripted"))
    mc.add_argument("--role", action="append")
    mc.add_argument("--probe", action="store_true", help="also call every model once (text + tools)")

    sub.add_parser("build-tasks")
    r = sub.add_parser("run")
    r.add_argument("config")
    r.add_argument("--out", required=True)
    r.add_argument("--profile")
    r.add_argument("--role", action="append", help="role=spec[,fallback...] override, repeatable")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--seeds", type=int, nargs="*")
    r.add_argument("--cap-usd", type=float)
    r.add_argument("--allow-shared-family", action="store_true")
    rp = sub.add_parser("replay")
    rp.add_argument("run_dir")
    rp.add_argument("--profile", help="profile providing monitor_judge for M2/M4 (default: no LLM judge)")
    rp.add_argument("--monitors", nargs="*", default=["M0", "M1", "M2", "M3", "M4"])
    rp.add_argument("--observability", nargs="*")
    rp.add_argument("--workers", type=int, default=2)
    sw = sub.add_parser("sweep-monitors", help="replay identical trajectories with weaker/same/stronger monitor models")
    sw.add_argument("run_dirs", nargs="+")
    sw.add_argument("--out", required=True)
    sw.add_argument("--config", help="experiment YAML with a `monitor_sweep:` section (judges, tasks)")
    sw.add_argument("--judge", action="append", help="arm=spec, e.g. lower=hf/Qwen/Qwen2.5-0.5B-Instruct (repeatable)")
    sw.add_argument("--tasks", nargs="*", help="SWE tasks to include (default: all in the run)")
    sw.add_argument("--fpr", type=float, default=0.1)
    rep = sub.add_parser("report")
    rep.add_argument("run_dirs", nargs="+")
    rep.add_argument("--out", required=True)
    rep.add_argument("--fpr", type=float, default=0.1)
    a = ap.parse_args(argv)

    if a.cmd == "providers":
        from .core import providers as P
        if a.sub == "list":
            print(_table(P.key_status(), ["provider", "kind", "key", "base_url", "verify"]))
        elif a.sub == "import-fcm":
            found = P.import_fcm_keys(Path(a.config) if a.config else None)
            if not found:
                print("No keys found (or config not at ~/.free-coding-models.json). "
                      "Copy keys into .env manually - see .env.example.")
                return
            for k, v in found.items():
                print(f"{k}={_mask(v)}" + ("   (already set)" if os.environ.get(k) else ""))
            if a.write:
                env = REPO / ".env"
                existing = env.read_text(encoding="utf-8") if env.exists() else ""
                new = [f"{k}={v}" for k, v in found.items() if f"{k}=" not in existing and not os.environ.get(k)]
                with env.open("a", encoding="utf-8") as f:
                    f.write(("\n" if existing and not existing.endswith("\n") else "") + "\n".join(new) + ("\n" if new else ""))
                print(f"appended {len(new)} key(s) to {env}")
        elif a.sub == "check":
            from .core.probe import DEFAULT_PROBE_MODELS, probe
            specs = list(a.model or [])
            if not specs:
                only = set(a.only.split(",")) if a.only else None
                keyed = {r["provider"] for r in P.key_status() if r["key"] != "-"}
                specs = [s for p, s in DEFAULT_PROBE_MODELS.items()
                         if (only is None and p in keyed) or (only and p in only)]
            print(f"probing {len(specs)} model(s)...")
            print(_table(probe(specs, a.timeout), ["spec", "family", "text", "tools", "latency_s", "served_by", "error"]))
    elif a.cmd == "fcm":
        from .core import pool as PL
        path = PL.fcm_config_path()
        print(f"FCM config: {path or 'NOT FOUND (set FCM_CONFIG or copy ~/.free-coding-models.json)'}")
        cfg = PL.load_fcm_config()
        keys = PL.fcm_keys(cfg)
        from .core.providers import registry
        reg = registry()["providers"]
        for prov, k in keys.items():
            print(f"  key  {prov:14s} {_mask(k)}  {'usable' if prov in reg else 'not in configs/providers.yaml (ignored)'}")
        for name, models in PL.fcm_router_sets(cfg).items():
            print(f"  set  {name}: " + ", ".join(f"{m['provider']}/{m['model']}" for m in models))
        pp = ((cfg.get("router") or {}).get("prePrompt") or {})
        if pp.get("enabled"):
            print("  NOTE router prePrompt is ENABLED: the FCM router injects its own system prompt into every request."
                  "\n       clab calls providers directly (unaffected); only the fcm/fcm last-resort tail is affected."
                  "\n       For clean experiments disable it in free-coding-models settings.")
        print(f"  router http://localhost:19280 : {'UP' if PL.fcm_router_up() else 'down (start: free-coding-models --daemon-bg)'}")
        om = PL.ollama_models()
        print(f"  ollama: {', '.join(om) if om else 'not reachable (ollama serve)'}")
    elif a.cmd == "pool":
        from .core import pool as PL
        if a.sub == "discover":
            import yaml as _y
            pc = (_y.safe_load((REPO / "configs" / "models.yaml").read_text(encoding="utf-8")).get("pool") or {})
            cands = PL.discover(pc.get("sources"), a.max_probe or pc.get("max_probe", 24), pc.get("concurrency", 6),
                                pc.get("timeout", 30), pc.get("ttl_hours", 6), refresh=a.refresh)
            rows = [{"spec": c.spec, "family": c.family, "source": c.source, "ok": c.ok, "tools": c.tools,
                     "latency_s": c.latency_s, "score": c.score, "error": c.error[:60]} for c in cands]
            print(_table(rows, ["spec", "family", "source", "ok", "tools", "latency_s", "score", "error"]))
            print(f"\n{sum(1 for c in cands if c.ok)} usable models cached in {PL.CACHE_FILE}")
        else:
            sys.exit(cmd_models_check(a.profile, {}, probe=False))
    elif a.cmd == "models":
        sys.exit(cmd_models_check(a.profile, _overrides(a.role), a.probe))
    elif a.cmd == "build-tasks":
        from .scenarios.swe.taskbuilder import main as build
        build()
    elif a.cmd == "run":
        from .experiments import episodes_table, run_matrix
        cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
        if a.profile:
            cfg["profile"] = a.profile
        if a.role:
            cfg["overrides"] = {**cfg.get("overrides", {}), **_overrides(a.role)}
        if a.seeds:
            cfg["seeds"] = a.seeds
        if a.cap_usd is not None:
            cfg["cap_usd"] = a.cap_usd
        if cfg.get("profile", "scripted") != "scripted":
            rc = cmd_models_check(cfg["profile"], cfg.get("overrides") or {}, probe=False)
            if rc == 2:
                sys.exit("refusing to run: some role has no usable model (see above)")
            if rc == 1 and not a.allow_shared_family:
                sys.exit("refusing to run: monitor shares a model family with the agents "
                         "(pass --allow-shared-family for the ablation)")
        if cfg.get("profile", "scripted") != "scripted":
            # resolve dynamic (auto:) chains ONCE here and hand explicit chains to the workers
            import json as _j
            from .core.models import ModelRoster
            ro = ModelRoster(cfg["profile"], cfg.get("overrides") or {})
            if ro.auto_expanded:
                cfg["overrides"] = {k: ",".join(v) if isinstance(v, list) else v for k, v in ro.mapping.items()}
            Path(a.out).mkdir(parents=True, exist_ok=True)
            (Path(a.out) / "model_assignment.json").write_text(_j.dumps(ro.describe(), indent=1), encoding="utf-8")
        run_matrix(cfg, Path(a.out), a.workers)
        episodes_table(Path(a.out))
    elif a.cmd == "replay":
        from .experiments import OBS_PRESETS, episodes_table, replay
        df = replay(Path(a.run_dir), a.monitors, a.observability or OBS_PRESETS, a.profile, a.workers)
        episodes_table(Path(a.run_dir))
        print(f"{len(df)} decisions -> {a.run_dir}/decisions.csv")
    elif a.cmd == "sweep-monitors":
        from .eval.monitor_sweep import agent_models, build_sweep_report, run_sweep
        sc = {}
        if a.config:
            sc = (yaml.safe_load(Path(a.config).read_text(encoding="utf-8")) or {}).get("monitor_sweep", {}) or {}
        judges = dict(sc.get("judges", {}))
        judges.update(_overrides(a.judge))
        if not judges:
            sys.exit("no judge arms: pass --judge lower=SPEC --judge same=SPEC --judge higher=SPEC or --config")
        tasks = a.tasks or sc.get("tasks")
        dirs = [Path(d) for d in a.run_dirs]
        agents = agent_models(dirs)
        print("agent models used:", agents or "scripted", flush=True)
        print("judge arms:", judges, flush=True)
        df = run_sweep(dirs, judges, tasks)
        t = build_sweep_report(df, Path(a.out), judges, agents, a.fpr)
        print((Path(a.out) / "monitor_sweep.md").read_text(encoding="utf-8")[:4000])
    elif a.cmd == "report":
        from .eval.report import build_report
        build_report([Path(d) for d in a.run_dirs], Path(a.out), a.fpr)
        print((Path(a.out) / "tables.md").read_text(encoding="utf-8")[:6000])


if __name__ == "__main__":
    main()
