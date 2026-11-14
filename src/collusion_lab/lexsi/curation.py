"""CuratorKIT validation/export for the Collusion-Watch dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def curate_dataset(
    source_path: Path,
    output_dir: Path,
    *,
    split: str = "train",
) -> dict[str, Any]:
    """Curate one dataset split and keep the CuratorKIT source/provenance."""
    from curatorkit import Curator, CuratorConfig

    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Dataset JSONL does not exist: {source_path}")
    if not split:
        raise ValueError("A non-empty dataset split is required.")
    source_rows = []
    for line_number, line in enumerate(
        source_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number} of {source_path}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Expected a JSON object on line {line_number} of {source_path}")
        if not isinstance(row.get("split"), str):
            raise ValueError(f"Missing split on line {line_number} of {source_path}")
        source_rows.append(row)
    if not source_rows:
        raise ValueError(f"Dataset JSONL is empty: {source_path}")
    selected_rows = [row for row in source_rows if row["split"] == split]
    if not selected_rows:
        raise ValueError(f"No dataset rows found for split {split!r} in {source_path}")

    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_copy = output_dir / f"source_{split}.jsonl"
    with source_copy.open("w", encoding="utf-8", newline="\n") as stream:
        for row in selected_rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    curator_dir = output_dir / "curator"
    curator_dir.mkdir()

    result = Curator(CuratorConfig(
        dataset=str(source_copy),
        format="auto",
        dedup="none",
        clean=False,
        export_formats=["alpaca"],
        output_dir=str(curator_dir),
    )).run()
    passed_count = len(result.passed)
    rejected_count = len(result.rejected)
    if passed_count != len(selected_rows) or rejected_count:
        reasons: dict[str, int] = {}
        for sample in result.rejected:
            reasons[sample.rejection_reason] = reasons.get(sample.rejection_reason, 0) + 1
        raise RuntimeError(
            "CuratorKIT did not preserve all source rows: "
            f"input={len(selected_rows)}, passed={passed_count}, rejected={rejected_count}, "
            f"reasons={reasons}"
        )

    manifest_path = curator_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"CuratorKIT did not create its manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    training_manifest = {
        "source_dataset": str(source_path),
        "source_sha256": source_hash,
        "selected_split": split,
        "source_examples": len(source_rows),
        "selected_examples": len(selected_rows),
        "excluded_examples": len(source_rows) - len(selected_rows),
        "selected_episode_ids": [
            row.get("metadata", {}).get("episode_id") for row in selected_rows
        ],
        "curatorkit_manifest": str(manifest_path),
    }
    training_manifest_path = output_dir / "training_manifest.json"
    training_manifest_path.write_text(
        json.dumps(training_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "input_examples": len(source_rows),
        "selected_examples": len(selected_rows),
        "passed_examples": passed_count,
        "rejected_examples": rejected_count,
        "curatorkit_manifest": str(manifest_path),
        "curatorkit_manifest_data": manifest,
        "output_dir": str(output_dir),
        "source_copy": str(source_copy),
        "training_manifest": str(training_manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Source dataset JSONL.")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Directory for CuratorKIT artifacts and Alpaca export.")
    parser.add_argument("--split", default="train",
                        help="Dataset split to curate (default: train; never curation-mixes splits).")
    args = parser.parse_args()
    print(json.dumps(curate_dataset(args.input, args.output_dir, split=args.split), indent=2))


if __name__ == "__main__":
    main()
