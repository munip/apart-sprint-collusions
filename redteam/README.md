# Red-teaming the trusted monitor with Petri (pending API access)

[Petri](https://github.com/safety-research/petri)  for audit is built on Inspect: an *auditor* model probes a
*target* model in a scenario described by a seed instruction, and a *judge* scores the transcript.
It audits one target at a time, so it is **not** our multi-agent harness. We use it in two ways:

1. **Attack generation (MRT-style).** Seed instructions ask the auditor to play the colluding partner
   of a FastAPI implementer (or of a seller), and to invent coordination schemes that the current
   monitor does *not* catch. Successful schemes get turned into new conditions
   (`scenarios/*/conditions.py`) and become held-out test cases for the monitor.
   Seeds: `petri_seeds.txt`. For new SWE scenarios, add /modify the seed. Prompt here should ideally be different from greenfield versus brownfield maintenance/enhancement type work
2. **Judge rubric.** Petri's judge dimensions (deception, unauthorized coordination, concealment)
   inform the M2 judge prompt in `src/collusion_lab/monitor/judge.py`.

Run (when an API key for models below is available):

```bash
pip install git+https://github.com/safety-research/petri
inspect eval petri/audit \
  --model-role auditor=anthropic/claude-sonnet-4-5 \
  --model-role target=anthropic/claude-haiku-4-5 \
  --model-role judge=anthropic/claude-sonnet-4-5 \
  -T special_instructions=redteam/petri_seeds.txt -T max_turns=30
```
