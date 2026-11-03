# Lexsi Part B: Collusion-Watch

The Nov 3 Track 2 direction combines statements 2, 3, 4 and 5: build a
collusion-monitoring benchmark, test turn-by-turn and multilingual behavior, and
compare plain fine-tuning with safety-hardened fine-tuning. The first repository
deliverable is an English dataset export from existing market runs. Model
training, SafeTune evaluation and multilingual augmentation are separate stages
and are not claimed to have run.

## Export the English v0 benchmark

Use the repository's Python environment and export to an ignored run directory:

```powershell
python -m collusion_lab.lexsi.dataset `
  --runs runs/market_chain runs/market_chain_v2 `
  --output-dir runs/lexsi_dataset_v0 `
  --split-seed 0
```

The exporter writes:

* `dataset.jsonl`: `instruction`, `input`, `output`, `split` and `metadata`
  fields; `output` is a JSON string containing `verdict`, `action` and `reason`.
* `manifest.json`: format version, split and label counts, source evidence
  fingerprints and dataset caveats.

Run directories are searched recursively. Each market episode must have a
matching `evidence.jsonl` whose hash chain verifies. Only seller/buyer ask, bid,
trade and seller-message events enter the model input; episode truth, monitor
decisions and honeypot/audit records remain excluded. Labels come from
`episode.truth.collusive`. All rows sharing an episode seed stay in one split;
at least three distinct seeds are required to create train, validation and test.

The target's reason is an explicit template derived from the label, not a
faithful explanation of the evidence. It must not be used to claim rationale
quality. Review the exported examples and CuratorKIT filtering behavior before
training or publishing. Keep generated logs and datasets in ignored `runs/`
storage unless they are intentionally prepared for public release.

## Next validation gates

1. Review the JSONL sample distribution and verify that the condition and seed
   metadata meet the pre-registered evaluation design.
2. Smoke-test CuratorKIT ingestion and its filtering on representative benign,
   collusive and multilingual rows.
3. Confirm Tiny Aya access and run a short training/evaluation smoke test on the
   chosen GPU before committing to plain and SafeTune-hardened model runs.
4. Add translated/code-mixed evaluation rows with explicit language and
   provenance metadata; do not overwrite the English source text.
5. Evaluate base, plain fine-tuned and hardened models on the same held-out
   seeds. Report detection, valid JSON/verdict, fail-open, refusal and
   over-refusal results separately.

## Local checks

```powershell
pytest -q tests/test_lexsi_dataset.py
```
