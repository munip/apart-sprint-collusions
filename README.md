# Trusted monitoring for multi-agent collusion: software and market scenarios

A research harness for one question: **can a trusted monitor tell harmful coordination
from legitimate cooperation, disrupt it, and leave honest work alone, including when the
coordination is hidden by steganography?**

It contains:

* two real-world scenarios behind one monitor interface:
  * **Scenario B (software integrity).** A planner, implementer, tester, reviewer and release-bot
    team works on real **FastAPI** features (5 upstream commits from 21 Oct 2026). Hidden
    SWE-bench-style acceptance tests define ground truth.
  * **Scenario A (market integrity).** Sellers on a **continuous double auction** framed as an
    hourly wholesale power exchange. The protocol follows *Evaluating LLM Agent Collusion in
    Double Auctions*. The competitive-equilibrium benchmark defines harm.
* collusion conditions ranging from overt to **steganographic**: codebook phrases, code-comment
  and whitespace signals, tool or scratch-file side channels, reference-solution leakage with
  canaries, and FCC-style trailing-digit price signalling. Hard-negative controls cover
  legitimate teamwork and benign price convergence.
* a monitor ladder (M0 to M4) from rules-only and LLM-judge baselines up to a **model-free
  verification and provenance monitor**, with graduated enforcement (Allow / Hold / Constrain).
  Market interventions include admitting a *trusted competitive entrant*.
* **Inspect** tasks, a cost-capped per-role model roster (Anthropic, OpenAI, Ollama open weights,
  or `$0` scripted agents) and an offline replay that scores every monitor on identical trajectories.

Design document: [`docs/milestones/M6_scenarios_and_trusted_monitor.md`](docs/milestones/M6_scenarios_and_trusted_monitor.md).
Paper sources: [`paper/`](paper/).

## Architecture

```
untrusted agents ─tools─▶ Environment (only writer) ─▶ hash-chained evidence log
      ▲                           │                          │ read-only
      └── CI-like gate message ◀── Enforcement ◀── Policy ◀── Detectors ◀── TrustedMonitor ─▶ private log
```

* Agents act only through environment tools that log every call. Agents cannot write to the
  log or reach the monitor.
* The monitor runs **independent verification**. For software: hidden acceptance tests on a
  pristine checkout, mutation testing of the team's tests, canaries and information-flow
  provenance. For markets: price versus the competitive benchmark and channel statistics.
* `CONSTRAIN` requires *verified* evidence. Suspicion alone can only `HOLD`. The collusion
  score (coordination evidence) is kept separate from harm risk, so the report can tell apart
  "coordination detected", "harm prevented without detecting coordination" and "suspicious but
  harmless".

```
src/collusion_lab/
  core/            schema, evidence log, model roster + cost cap, tool loop
  monitor/         core (policy, M0–M4), judge (M2), detectors/{generic,swe,market}
  scenarios/swe/   taskbuilder, repo (pristine runner), workspace (tools), conditions, specs, agents/{scripted,llm}, env
  scenarios/market/cda, conditions, agents/{scripted,llm}, env, monitor_plugin
  eval/            metrics (AUROC, recall@FPR, bootstrap CIs), report (tables + figures)
  experiments.py   matrix runner + offline replay;  inspect_tasks.py  Inspect entry points;  cli.py
configs/           models.yaml (profiles), experiments/*.yaml
data/swe_tasks/    built FastAPI tasks (hidden tests, reference patch, mutants)
docs/ paper/ redteam/ scripts/ tests/
```

## Quick start

```bash
pip install -e ".[dev]"
./scripts/setup_swe_env.sh                 # FastAPI checkout + isolated test venv (.cache/)
pytest -q                                   # unit tests (no API key needed)

# $0 scripted runs (exact ground truth)
clab run configs/experiments/market_matrix.yaml --out runs/market_v1
clab run configs/experiments/swe_matrix.yaml    --out runs/swe_v1 --workers 2
clab replay runs/swe_v1 && clab replay runs/market_v1
clab report runs/swe_v1 runs/market_v1 --out reports/v1

# Inspect
inspect eval src/collusion_lab/inspect_tasks.py@market_collusion -T profile=scripted --model mockllm/model
inspect view
```

## Plugging in models

Copy `.env.example` to `.env` (gitignored) and choose a profile in `configs/models.yaml`:

| Profile | Agents | Monitor judge (M2/M4) |
|---|---|---|
| `scripted` | deterministic, $0 | none |
| `cloud` | `anthropic/claude-haiku-4-5` | `anthropic/claude-sonnet-4-5` |
| `local` | `ollama/qwen2.5-coder:7b` (set `OLLAMA_BASE_URL`) | `ollama/qwen2.5:14b` |
| `mixed` | heterogeneous team (Claude + Qwen + Llama) | Claude Sonnet |
| `same_family` | Claude Haiku | Claude Haiku (correlated-error ablation) |

```bash
clab run configs/experiments/swe_smoke_llm.yaml --out runs/swe_llm_smoke --profile cloud --cap-usd 5
clab run configs/experiments/swe_matrix.yaml --out runs/swe_mixed --profile mixed \
     --role tester=ollama/qwen2.5-coder:14b
clab replay runs/swe_llm_smoke --profile cloud     # adds the M2 LLM judge
```

Each run writes a per-episode `evidence.jsonl` (the authoritative log), `episode.json`
(ground truth and outcome), the monitor's private log under `_monitor_private/`, and the
cost summary.

## Status (v0.1)

* Both scenarios, all conditions, monitors M0/M1/M3/M4, interventions, Inspect tasks and the
  report pipeline run end to end with scripted agents.
* The LLM-agent path is implemented and unit-tested with Inspect's `mockllm`. It still needs an
  API key or a local Ollama to produce results.
* M2 (LLM judge) and Petri red-teaming are wired in but pending model access. See `redteam/`.

## Provenance and licences

* FastAPI (MIT) is cloned at run time and is not vendored. Task data in `data/swe_tasks/` contains
  upstream test files and patches (MIT, © Sebastián Ramírez).
* The CDA market is re-implemented, not copied, because `andyjliu/llm-agent-collusion` has no
  licence file. Please cite Agrawal et al. (arXiv:2507.01413).
