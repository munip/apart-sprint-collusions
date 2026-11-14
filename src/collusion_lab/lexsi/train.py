"""Train plain-SFT and SafeGrad Tiny Aya monitor variants on CuratorKIT data."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _read_sft_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"CuratorKIT SFT JSONL does not exist: {path}")
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number} of {path}") from exc
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) for key in ("instruction", "input", "output")
        ):
            raise ValueError(
                f"Expected instruction/input/output strings on line {line_number} of {path}"
            )
        try:
            target = json.loads(row["output"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid target JSON on line {line_number} of {path}") from exc
        if not isinstance(target, dict) or set(target) != {
            "collusion_probability", "colluding_agents", "rationale"
        }:
            raise ValueError(
                f"Training target on line {line_number} is not in runtime M2 format"
            )
        rows.append({key: row[key] for key in ("instruction", "input", "output")})
    if not rows:
        raise ValueError(f"No training rows found in {path}")
    return rows


def train_variants(
    dataset_path: Path,
    output_dir: Path,
    *,
    model_id: str = "CohereLabs/tiny-aya-fire",
    algorithm: str = "both",
    epochs: int = 1,
    batch_size: int = 1,
    learning_rate: float = 1e-4,
    max_length: int = 512,
    safety_examples: int = 32,
    seed: int = 42,
) -> dict[str, Any]:
    """Train M2-compatible adapters/checkpoints from the curated training split."""
    if algorithm not in {"plain", "safegrad", "both"}:
        raise ValueError(f"Unsupported training algorithm: {algorithm!r}")
    if epochs < 1 or batch_size < 1 or max_length < 1 or safety_examples < 1:
        raise ValueError("epochs, batch_size, max_length, and safety_examples must be positive.")
    if learning_rate <= 0:
        raise ValueError("learning_rate must be positive.")

    dataset_path = Path(dataset_path)
    rows = _read_sft_rows(dataset_path)
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    if not os.getenv("HF_TOKEN"):
        raise RuntimeError("HF_TOKEN is required to load the gated Tiny Aya checkpoint.")

    import torch
    import safetune
    from datasets import Dataset
    from safetune.runner import harden

    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        memory_gib = properties.total_memory / (1024**3)
        print(f"GPU: {properties.name} ({memory_gib:.1f} GiB)")
        if algorithm in {"safegrad", "both"} and memory_gib < 20:
            print(
                "WARNING: SafeGrad holds a trainable model and a frozen reference model "
                "on-device. A 15-GB Colab GPU is likely to run out of memory; use a larger "
                "GPU for the SafeGrad variant or run only --algorithm plain.",
                flush=True,
            )
    else:
        print("No CUDA GPU detected; Tiny Aya training may be very slow.", flush=True)

    safetune.configure(device="auto", max_len=max_length, seed=seed)
    train_dataset = Dataset.from_list(rows)
    algorithms = ("plain", "safegrad") if algorithm == "both" else (algorithm,)
    checkpoints: dict[str, str] = {}
    safety_dataset = None

    for variant in algorithms:
        print(f"Training {variant} variant on {len(rows)} CuratorKIT train rows.", flush=True)
        trainer_kwargs = {
            "model_id": model_id,
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": learning_rate,
            "logging_steps": 1,
        }
        trainer = (
            harden.PlainSFTTrainer(**trainer_kwargs)
            if variant == "plain"
            else harden.SafeGradTrainer(**trainer_kwargs)
        )
        if variant == "safegrad":
            if safety_dataset is None:
                _, safety_dataset = harden.load_harden_data(
                    model_id, n=safety_examples, max_len=max_length
                )
            checkpoint = trainer.train(
                train_dataset,
                out_dir=str(output_dir / "safegrad"),
                safety_dataset=safety_dataset,
            )
        else:
            checkpoint = trainer.train(
                train_dataset,
                out_dir=str(output_dir / "plain"),
            )
        checkpoints[variant] = str(checkpoint)
        del trainer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    manifest = {
        "base_model": model_id,
        "task": "runtime M2 market transcript judge",
        "algorithm": algorithm,
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": learning_rate,
        "max_length": max_length,
        "safety_examples": safety_examples if "safegrad" in algorithms else 0,
        "seed": seed,
        "training_examples": len(rows),
        "curatorkit_sft_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "checkpoints": checkpoints,
        "note": (
            "Targets are scenario ground-truth labels; rationale text is templated, "
            "not evidence-grounded. Compare both variants with the base checkpoint "
            "on the same untouched test split."
        ),
    }
    manifest_path = output_dir / "training_run.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True,
                        help="CuratorKIT train-only sft_alpaca.jsonl.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="CohereLabs/tiny-aya-fire")
    parser.add_argument("--algorithm", choices=("plain", "safegrad", "both"), default="both")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--safety-examples", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = train_variants(
        args.dataset,
        args.output_dir,
        model_id=args.model,
        algorithm=args.algorithm,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        max_length=args.max_length,
        safety_examples=args.safety_examples,
        seed=args.seed,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
