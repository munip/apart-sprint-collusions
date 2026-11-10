# Lexsi Part B: Collusion-Watch

The project is English-only for Steps 1–3. The first benchmark uses the
repository's original market arrangement: **5 LLM sellers and 4 scripted ZIP
buyers**. It covers A2 honest chat (benign hard negative), A3 overt cartel, and
A5 steganographic price rotation. The experiments have no online monitor,
layered monitor, probe, or intervention arm; the model sees the public market
record, not monitor-only messages or honeypots.

The work is staged so the baseline is reproducible before any training:

1. **Base (current step):** CuratorKIT validates/exports the data; Tiny Aya
   Global runs zero-shot; AuditKIT reports format, verdict, action, and fail-open
   metrics.
2. **Plain fine-tune:** train on the CuratorKIT export of the train split only;
   evaluate the adapter on the same held-out split(s) and inputs.
3. **Safety-hardened fine-tune:** use SafeTune's hardening trainer with the same
   task data and comparable training budget; evaluate the same collusion metrics
   plus English refusal and over-refusal checks.

No multilingual data, training, or safety result is claimed by Step 1.

## 1. Prepare the English base dataset

The configuration for a fresh, unmonitored LLM-seller run is
[`configs/experiments/lexsi_market_base.yaml`](../configs/experiments/lexsi_market_base.yaml).
It specifies 15 rounds and seeds 0–9 (30 episodes). Running it needs the
configured seller-model provider and its credentials; keep credentials in
environment secrets, never in the repository:

```powershell
clab run configs/experiments/lexsi_market_base.yaml --out runs/lexsi_market_base --workers 1
```

There are already 9 usable, unmonitored episodes in `runs/market_entrant`
(three conditions × seeds 0–2). They are enough to exercise the pipeline, but
only provide three independent seeds. With that small sample, the test split
contains only three episodes; its scores are diagnostic, not a generalization
claim. The earlier `runs/market_chain` / `runs/market_chain_v2` data contains
monitor-chain variants and is intentionally excluded from this baseline.

Export the existing starter runs, or replace the input path with
`runs/lexsi_market_base` after generating the larger run:

```powershell
python -m collusion_lab.lexsi.dataset `
  --runs runs/market_entrant `
  --output-dir runs/lexsi_dataset_base `
  --split-seed 0 `
  --window-rounds 5
```

The exporter requires 5 sellers, 4 buyers, LLM seller metadata, and a valid
evidence hash chain. It filters out monitor/probe variants and unselected
conditions. Each example contains the **last five observed complete rounds**,
episode ground truth, a seed-level split, source fingerprint, and model
metadata. All episodes with the same seed stay in one split.

Files written:

* `dataset.jsonl`: `instruction`, `input`, `output`, `split`, and `metadata`.
  The input is a JSON window of market asks, bids, trades, and public seller
  board messages. The target verdict/action is derived from the episode's known
  condition label.
* `manifest.json`: condition/label/split counts, market setup, seed assignments,
  skipped variants, and source evidence hashes.

The target's `reason` is a label-derived template, not an evidence-grounded
explanation. Do not use it to claim rationale quality. The existing source has
only three distinct seeds. For a useful held-out result, run more independent
seeds before treating the metrics as benchmark findings.

## 2. CuratorKIT curation gate

CuratorKIT is used here for schema validation, provenance, and an Alpaca-format
export. We deliberately disable text cleaning and deduplication: the event
window is structured evidence, and exact deduplication on the current rows
collapsed distinct examples in a smoke test. Keep `dataset.jsonl` as the
source-of-truth file and inspect CuratorKIT's `manifest.json` and
`rejected.jsonl` before proceeding.

Install the optional integration packages:

```powershell
python -m pip install -e ".[lexsi]"
```

Run the tested wrapper:

```powershell
python -m collusion_lab.lexsi.curation `
  --input runs/lexsi_dataset_base/dataset.jsonl `
  --output-dir runs/lexsi_curated_base
```

The wrapper errors if CuratorKIT rejects or drops any rows. It writes the
CuratorKIT provenance files and `sft_alpaca.jsonl`; it does not call an LLM or
modify the source dataset.

## 3. Tiny Aya Global zero-shot baseline with AuditKIT

Upload `runs/lexsi_dataset_base/dataset.jsonl` and
[`audit.py`](../src/collusion_lab/lexsi/audit.py) to Colab, select a T4, and
install the evaluation/model packages:

```python
!pip -q install auditkit curatorkit transformers accelerate bitsandbytes
```

After installation, restart the Colab runtime. Upload both files into the
runtime (the `audit.py` file should be at `/content/audit.py`), then run the
code below. It uses 4-bit weights and does not rely on `model.hf_device_map`;
it checks the input-embedding device instead.

```python
from google.colab import files

files.upload()  # Select dataset.jsonl and src/collusion_lab/lexsi/audit.py

import gc
import json

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)

from audit import evaluate_with_auditkit

dataset_path = "/content/dataset.jsonl"
model_id = "CohereLabs/tiny-aya-global"
max_input_tokens = 4096

if not torch.cuda.is_available():
    raise RuntimeError("Select a CUDA GPU in Colab Runtime settings.")
print("GPU:", torch.cuda.get_device_name(0))

with open(dataset_path, encoding="utf-8") as source:
    rows = [json.loads(line) for line in source if line.strip()]

tokenizer = AutoTokenizer.from_pretrained(model_id)
quantization = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=quantization,
    device_map={"": 0},
)
model.eval()

input_device = model.get_input_embeddings().weight.device
print("Input embedding device:", input_device)
if input_device.type != "cuda":
    raise RuntimeError(
        f"Model embeddings are on {input_device}; expected the Colab GPU."
    )


def tiny_aya(prompts):
    answers = []
    for prompt in prompts:
        encoded = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )
        token_count = encoded["input_ids"].shape[1]
        if token_count > max_input_tokens:
            raise ValueError(
                f"Prompt has {token_count} tokens; re-export a smaller "
                "window rather than silently truncating evidence."
            )
        encoded = {
            key: value.to(input_device) if isinstance(value, torch.Tensor) else value
            for key, value in encoded.items()
        }
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                max_new_tokens=96,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        new_tokens = generated[0, encoded["input_ids"].shape[1]:]
        answers.append(tokenizer.decode(new_tokens, skip_special_tokens=True))
        del encoded, generated, new_tokens
        gc.collect()
        torch.cuda.empty_cache()
    return answers


for split in ("test", "validation", "train"):
    result = evaluate_with_auditkit(
        rows,
        model=tiny_aya,
        split=split,
        experiment_name="collusion-watch-tiny-aya-global-base",
    )
    print(f"\n{split}:")
    print(result.summary())
    print(result.headline)
```

AuditKIT reports valid JSON schema rate, verdict accuracy, action accuracy,
and collusive fail-open rate. Invalid/malformed outputs count as fail-open.
Keep the split names, sample counts, model ID, quantization, and manifest with
the results. Tiny Aya Global is a 3.35B model under a
[CC-BY-NC license and Cohere Labs' Acceptable Use Policy](https://huggingface.co/CohereLabs/tiny-aya-global).

## 4. Steps 2 and 3 — not started

Do not train until Step 1 data curation has preserved all intended rows and the
zero-shot baseline has been saved. For training, write a train-only JSONL from
rows where `split == "train"`; never train on validation or test rows.

* **Step 2:** plain supervised fine-tuning on the CuratorKIT Alpaca export of
  train only. Evaluate base and adapter on the same test examples with
  `evaluate_with_auditkit`.
* **Step 3:** repeat from the same base checkpoint and train examples using
  SafeTune's safety-preserving trainer. Compare base, plain, and hardened
  checkpoints on collusion detection and the same English refusal /
  over-refusal suites.

Keep all run outputs under ignored `runs/` until they are explicitly reviewed
and prepared for publication.

## Local validation

```powershell
python -m pip install -e ".[dev,lexsi]"
pytest -q tests/test_lexsi_dataset.py
```
