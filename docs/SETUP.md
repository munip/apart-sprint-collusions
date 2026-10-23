# Setup and run guide: multiple LLM providers, routers and local models

> Looking for a specific command or flag? See **[COMMANDS.md](COMMANDS.md)**.

This guide covers a fresh machine through to first LLM results. Commands are for **Windows
PowerShell**; Linux/macOS equivalents are given where they differ.

> **Where to run.** Run LLM experiments **on your own machine**. Ollama (`localhost:11434`) and the
> free-coding-models router (`localhost:19280`) are only reachable there, and the Cowork cloud
> sandbox blocks third-party LLM APIs. Scripted ($0) runs work anywhere.

---

## 0. Prerequisites (once)

| Need | Check | Get it |
|---|---|---|
| Python 3.11+ | `py -3.12 --version` | python.org (tick "Add to PATH") |
| Git | `git --version` | git-scm.com/download/win |
| Ollama (optional) | `ollama list` shows `gemma2:2b` | ollama.com |
| free-coding-models (optional) | `free-coding-models --version` | `npm i -g free-coding-models` |

## 1. Get the code

```powershell
cd C:\collusions-claude
git clone https://github.com/munip/apart-sprint-collusions.git   # skip if the folder already exists
cd apart-sprint-collusions
git checkout milestone/6ab-trusted-monitor        # until PR #1 is merged
```

## 2. Initialise (one command)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
.\.venv\Scripts\Activate.ps1
```

This creates `.venv` (the project), clones FastAPI into `.cache\fastapi`, and creates a
**separate** `.cache\fapi-venv` where agents' code and tests run. It then runs the unit tests and
lists the providers.
Linux/macOS: `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && ./scripts/setup_swe_env.sh`.

Check that the $0 pipeline works before spending any rate limit:

```powershell
clab run configs\experiments\market_matrix.yaml --out runs\market_scripted --seeds 0
```

## 3. Configure API keys

Keys are read from the environment, from `apart-sprint-collusions\.env`, and from the parent
folder's `C:\collusions-claude\.env` (your existing file is picked up automatically).

**Option A: import from free-coding-models** (best effort; its config format is undocumented):

```powershell
clab providers import-fcm            # shows what it found (masked)
clab providers import-fcm --write    # appends missing keys to .env
```

**Option B: by hand.** Copy `.env.example` to `.env` and fill in the keys you have. The variable
names are the same ones free-coding-models uses (`GROQ_API_KEY`, `NVIDIA_API_KEY`, `CEREBRAS_API_KEY`,
`OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY`, ...). `HF_TOKEN` enables the Hugging Face
router. Tomorrow, add `ANTHROPIC_API_KEY`.

Then verify:

```powershell
clab providers list                  # which providers have keys / endpoints
clab providers check                 # one tiny call per keyed provider: text OK? native tool calls? latency
clab providers check --model ollama/gemma2:2b --model fcm/fcm
```

`clab providers check` prints the `tools` column: `native` means function calling works, and
`json-only` means the harness will drive tools through a JSON prompt protocol. That switch is
automatic, which is how `gemma2:2b` can still act as an agent.

## 3b. Use any free model your free-coding-models keys can reach (recommended)

You don't need to hard-code model IDs. Profiles `fcm_auto` and `fcm_auto_local_monitor` use
`auto:` specs that are resolved at start-up:

1. **Keys:** read from free-coding-models' config. The harness looks in this order: `FCM_CONFIG`,
   `~/.free-coding-models.json`, then **`C:\collusions-claude\.free-coding-models.json`** (the copy you
   placed next to the repo). Keys are exported in memory only; nothing is written to disk.
2. **Discovery:** candidates come from the FCM router sets in that config, each keyed provider's
   live `/models` list (OpenRouter limited to `:free` models with tool support),
   `free-coding-models --json` when the CLI is on PATH, and your local Ollama models.
3. **Probe:** each candidate gets one text call and one tool call (capped by `pool.max_probe`). The
   result is cached for 6 hours in `.cache\model_pool.json`.
4. **Assignment:** each agent role gets a ranked fallback chain, with different model families as
   primaries where possible. The **trusted monitor gets a family that no agent chain contains**.
   Every agent chain then ends with the FCM router (`fcm/fcm`, if running) and all local Ollama
   models.

```powershell
clab fcm status                       # keys found (masked), router sets, router/Ollama health, pre-prompt warning
clab pool discover --refresh          # discover + probe; prints the ranked pool
clab pool assign --profile fcm_auto   # shows the per-role chains and the monitor/agent family check
clab run configs\experiments\market_smoke_free.yaml --out runs\market_auto --profile fcm_auto --workers 1
clab run configs\experiments\swe_smoke_free.yaml    --out runs\swe_auto    --profile fcm_auto --workers 1
clab replay runs\swe_auto --profile fcm_auto      # M2 judge = the auto-chosen monitor model
```

Each run writes `runs\<name>\model_assignment.json`, recording the exact chains used, so the
paper can say which models were used. Use `fcm_auto_local_monitor` to keep the monitor on your
local `ollama/gemma2:2b`; its family is then excluded from every agent chain.

> **The FCM router's pre-prompt is enabled in your config.** The router adds its own system prompt
> ("You are free-coding-models, a free coding-model routing agent…") to every request. The pool
> calls providers **directly** with your keys, so it is unaffected. Only the `fcm/fcm` last-resort
> tail would be contaminated. For clean runs, disable the pre-prompt in free-coding-models'
> settings, or remove `fcm/fcm` from `pool.last_resort` in `configs\models.yaml`.

## 4. Start local services (optional)

```powershell
ollama serve                                  # usually already running as a service
ollama pull gemma2:2b                         # you have this
ollama pull llama3.2:3b                       # local *monitor* of a different family (profile `local`)

free-coding-models --daemon-bg                # Smart Router on http://localhost:19280/v1
free-coding-models --sync-set agents          # probe + fill a named set "agents" (text + tool-call probe)
free-coding-models --daemon-status
```

Different port or host? Set `OLLAMA_BASE_URL` / `FCM_BASE_URL` in `.env`. A LiteLLM proxy, Portkey,
or any other OpenAI-compatible gateway goes in `LITELLM_BASE_URL` / `CUSTOM_BASE_URL`.

## 5. Choose models per role (agents ≠ monitor)

Model specs are `<provider>/<model-id>`. A role can list a **fallback chain**: on a 429, quota
error or outage, the harness moves to the next model. Profiles in `configs\models.yaml`:

| Profile | Agents | Trusted monitor (M2/M4 judge) |
|---|---|---|
| `free` | each role a different family: Llama (planner/seller), Qwen-Coder (implementer), GPT-OSS (tester), Kimi/DeepSeek (reviewer) | Gemini 2.5 Flash, falling back to Mistral Small |
| `free_homogeneous` | every agent the same GPT-OSS model (shared-model Schelling-point ablation) | Gemini, then Mistral |
| `fcm` | everything through the free-coding-models router (`fcm/fcm` or `fcm/fcm:agents`) | **pinned** Gemini, then local gemma2 |
| `free_weak_monitor` | free strong agents | **local `ollama/gemma2:2b`**: weak trusted monitor (AI-control setting) |
| `local` | `ollama/gemma2:2b` | `ollama/llama3.2:3b` |
| `cloud` | Claude Haiku (when the key arrives) | Gemini, then Mistral |
| `mixed` | Claude + Groq/Cerebras + local gemma in one team | Gemini, then Mistral |
| `same_family`, `cloud_same_family` | ablations where the monitor shares the agents' family | (allowed explicitly) |

Inspect a profile before running. This resolves every role, checks keys, and **refuses a monitor
that shares a family with any agent**:

```powershell
clab models check --profile free            # add --probe to call every model once
```

Override any role from the command line without editing YAML:

```powershell
clab models check --profile free --role implementer=groq/qwen/qwen3-32b,cerebras/qwen-3-coder-480b `
                                 --role monitor_judge=ollama/gemma2:2b
```

Free-tier model IDs change frequently. When `--probe` reports `FAIL`, pick a working ID from
`free-coding-models --json` and edit `configs\models.yaml`, or pass `--role`.

## 6. Run

Start small. Each command writes `runs\<name>\<episode>\evidence.jsonl` (the authoritative log),
`episode.json` (ground truth, outcome, per-model call/cost summary including `served_by` for
routers), and the monitor's private log under `runs\<name>\_monitor_private\`.

```powershell
# a) fully offline first test of the LLM path (Ollama gemma2:2b sellers, ~20 calls)
clab run configs\experiments\market_local.yaml --out runs\market_local --workers 1

# b) free tiers: market (LLM sellers) then software team
clab run configs\experiments\market_smoke_free.yaml --out runs\market_free --workers 1
clab run configs\experiments\swe_smoke_free.yaml    --out runs\swe_free    --workers 1

# c) same runs through the free-coding-models router
clab run configs\experiments\swe_smoke_free.yaml --out runs\swe_fcm --profile fcm --workers 1
```

Keep `--workers 1` on free tiers. The rate limiter is per process, so more workers multiply your
request rate.

## 7. Score monitors (including the LLM judge) and build the report

```powershell
# M0/M1/M3/M4 + M2 (LLM judge from the profile's monitor_judge), all observability presets
clab replay runs\swe_free --profile free
clab replay runs\market_free --profile free_weak_monitor     # e.g. judge = local gemma2:2b
clab report runs\swe_free runs\market_free --out reports\free_v1
```

The judge is always taken from the replay profile, so you can score the *same* trajectories with
several judges (Gemini vs. gemma2 vs. Claude) and compare their FPR and recall.

## 8. Scale up

```powershell
clab run configs\experiments\swe_matrix.yaml --out runs\swe_free_full --profile free --workers 1
clab run configs\experiments\market_matrix.yaml --out runs\market_free_full --profile free --workers 1
```

Runs are **resumable**: re-running the same command skips finished episodes, which helps when a
free quota runs out mid-matrix. Once `ANTHROPIC_API_KEY` is set:
`--profile cloud --cap-usd 20` (the cost meter enforces the cap).

## 9. Inspect UI (optional)

```powershell
inspect eval src\collusion_lab\inspect_tasks.py@market_collusion -T profile=free -T seeds=0 -T rounds=15 --model mockllm/model
inspect view
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `missing key: ...` in `models check` | add the key to `.env`, or drop that spec from the chain |
| `all models failed for role X` | every model in the chain is 429/down: add fallbacks, lower `--workers`, or retry later (runs resume) |
| model never calls tools | `clab providers check --model <spec>`; if `json-only`, set `tools: json` for that provider in `configs\providers.yaml` |
| `refusing to run: monitor shares a model family` | choose a different `monitor_judge`, or pass `--allow-shared-family` for the ablation |
| router family warning (`fcm`) | expected: router models are dynamic. Check `served_by` in `episode.json → cost.by_model`. The monitor is pinned. |
| `UnicodeDecodeError` on Windows | open a new terminal after setup (`PYTHONUTF8=1` is set for your user); `clab` also re-launches itself in UTF-8 mode |
| Ollama connection refused | `ollama serve`; check `OLLAMA_BASE_URL` |
