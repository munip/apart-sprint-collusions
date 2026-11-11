import argparse
import gc
import json
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Tiny Aya AuditKIT baseline.")
    parser.add_argument("--dataset", type=Path, required=True, help="Collusion-Watch dataset JSONL.")
    parser.add_argument("--split", choices=("test", "validation", "train"), default="test")
    parser.add_argument("--model", default="CohereLabs/tiny-aya-global")
    parser.add_argument("--max-input-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=96)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    import torch
    from dotenv import load_dotenv
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from collusion_lab.lexsi.audit import evaluate_with_auditkit

    load_dotenv()
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        raise RuntimeError(
            "HF_TOKEN is not set. Add it to the environment or a local .env file."
        )
    if not args.dataset.is_file():
        raise FileNotFoundError(f"Dataset JSONL does not exist: {args.dataset}")

    with args.dataset.open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]

    use_gpu = torch.cuda.is_available()
    if use_gpu:
        print("GPU:", torch.cuda.get_device_name(0))
    else:
        print("Running on CPU; inference may be slow.")

    tokenizer = AutoTokenizer.from_pretrained(args.model, token=hf_token)
    if use_gpu:
        from transformers import BitsAndBytesConfig

        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.model,
            quantization_config=quantization,
            device_map={"": 0},
            token=hf_token,
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True,
            token=hf_token,
        )
    model.eval()
    input_device = model.get_input_embeddings().weight.device
    print("Input device:", input_device)

    def tiny_aya(prompts: list[str]) -> list[str]:
        answers = []
        for prompt in prompts:
            encoded = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            )
            token_count = encoded["input_ids"].shape[1]
            if token_count > args.max_input_tokens:
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
                    max_new_tokens=args.max_new_tokens,
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

    result = evaluate_with_auditkit(
        rows,
        model=tiny_aya,
        split=args.split,
        experiment_name=f"collusion-watch-{args.model.replace('/', '-')}-{args.split}",
    )
    print(result.summary())
    print(result.headline)


if __name__ == "__main__":
    main()
