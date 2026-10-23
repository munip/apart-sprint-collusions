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

## Plugging in models (providers, routers, gateways, local)

**Step-by-step guide: [`docs/SETUP.md`](docs/SETUP.md).**

* Model spec: `<provider>/<model-id>`, e.g. `groq/openai/gpt-oss-120b`, `openrouter/qwen/qwen3-coder:free`,
  `ollama/gemma2:2b`, `fcm/fcm:agents` (free-coding-models Smart Router), `litellm/<alias>`.
  There are 25+ providers in [`configs/providers.yaml`](configs/providers.yaml): Inspect-native ones,
  any OpenAI-compatible free tier, routers and gateways.
* Every role can name a **fallback chain**. 429s and outages move to the next model, and a
  per-provider rate limiter applies.
* Models without function calling (e.g. `gemma2:2b`) switch automatically to a prompted JSON
  tool protocol.
* The **trusted monitor must use a different model family than every agent**. `clab models check`
  and `clab run` enforce this, except in explicit ablation profiles.

| Profile | Agents | Monitor judge |
|---|---|---|
| `scripted` | deterministic, $0 | – |
| `free` | Llama / Qwen-Coder / GPT-OSS / Kimi / DeepSeek, one family per role | Gemini Flash, falling back to Mistral |
| `free_homogeneous` | one shared model for all agents | Gemini, then Mistral |
| `fcm` | free-coding-models router | pinned Gemini, then local gemma2 |
| `free_weak_monitor` | free strong agents | local `ollama/gemma2:2b` |
| `local` | `ollama/gemma2:2b` | `ollama/llama3.2:3b` |
| `cloud` / `mixed` | Claude Haiku / mixed paid+free+local | Gemini, then Mistral |

```bash
clab providers import-fcm --write      # reuse free-coding-models keys
clab providers check                   # text + tool-calling probe per provider
clab models check --profile free --probe
clab run configs/experiments/swe_smoke_free.yaml --out runs/swe_free --workers 1
clab replay runs/swe_free --profile free   # adds the M2 LLM judge
```

## Status (v0.1)

* Both scenarios, all conditions, monitors M0/M1/M3/M4, interventions, Inspect tasks and the
  report pipeline run end to end with scripted agents.
* The multi-provider LLM path (fallback chains, JSON tool mode, family-separation check) is
  implemented and unit-tested with Inspect's `mockllm` and fake clients. Real LLM results are pending.
* M2 (LLM judge) and Petri red-teaming are wired in but pending model access. See `redteam/`.

## Provenance and licences

* FastAPI (MIT) is cloned at run time and is not vendored. Task data in `data/swe_tasks/` contains
  upstream test files and patches (MIT, © Sebastián Ramírez).
* The CDA market is re-implemented, not copied, because `andyjliu/llm-agent-collusion` has no
  licence file. Please cite Agrawal et al. (arXiv:2507.01413).
