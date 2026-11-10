import gc
import json
import os

import torch
from dotenv import load_dotenv
from transformers import AutoModelForCausalLM, AutoTokenizer

from collusion_lab.lexsi.audit import evaluate_with_auditkit

load_dotenv()
hf_token = os.getenv("HF_TOKEN")
if not hf_token:
    raise RuntimeError(
        "HF_TOKEN is not set. Add it to .env or your environment before running."
    )
dataset_path = r"runs\lexsi_dataset_market_base_pilot\dataset.jsonl"
# dataset_path = "runs/lexsi_dataset_base/dataset.jsonl"
model_id = "CohereLabs/tiny-aya-global"
max_input_tokens = 4096

use_gpu = torch.cuda.is_available()
if use_gpu:
    print("GPU:", torch.cuda.get_device_name(0))
else:
    print("Running on CPU; inference may be slow.")

with open(dataset_path, encoding="utf-8") as source:
    rows = [json.loads(line) for line in source if line.strip()]

tokenizer = AutoTokenizer.from_pretrained(model_id, token=hf_token)

if use_gpu:
    # Install bitsandbytes in this environment for 4-bit GPU loading.
    from transformers import BitsAndBytesConfig

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
        token=hf_token,
    )
    input_device = model.get_input_embeddings().weight.device
else:
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.float32,
        low_cpu_mem_usage=True,
        token=hf_token,
    )
    model.eval()
    input_device = torch.device("cpu")

model.eval()
print("Input device:", input_device)


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
                f"Prompt has {token_count} tokens; reduce the exported "
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
        if use_gpu:
            gc.collect()
            torch.cuda.empty_cache()
    return answers


# for split in ("test", "validation", "train"):
#     result = evaluate_with_auditkit(
#         rows,
#         model=tiny_aya,
#         split=split,
#         experiment_name="collusion-watch-tiny-aya-global-local",
#     )
#     print(f"\n{split}:")
#     print(result.summary())
#     print(result.headline)

for split in ("test","validation", "train"):
    result = evaluate_with_auditkit(
        rows,
        model=tiny_aya,
        split=split,
        experiment_name=f"collusion-watch-tiny-aya-global-local-{split}",
    )
    print(f"\n{split}:")
    print(result.summary())
    print(result.headline)