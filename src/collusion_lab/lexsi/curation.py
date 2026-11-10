"""CuratorKIT validation/export for the Collusion-Watch dataset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def curate_dataset(source_path: Path, output_dir: Path) -> dict[str, Any]:
    """Validate and export a local JSONL dataset without changing rows or labels."""
    from curatorkit import Curator, CuratorConfig

    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Dataset JSONL does not exist: {source_path}")
    expected_count = sum(
        1 for line in source_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if expected_count == 0:
        raise ValueError(f"Dataset JSONL is empty: {source_path}")
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output: {output_dir}")

    result = Curator(CuratorConfig(
        dataset=str(source_path),
        format="auto",
        dedup="none",
        clean=False,
        export_formats=["alpaca"],
        output_dir=str(output_dir),
    )).run()
    passed_count = len(result.passed)
    rejected_count = len(result.rejected)
    if passed_count != expected_count or rejected_count:
        reasons: dict[str, int] = {}
        for sample in result.rejected:
            reasons[sample.rejection_reason] = reasons.get(sample.rejection_reason, 0) + 1
        raise RuntimeError(
            "CuratorKIT did not preserve all source rows: "
            f"input={expected_count}, passed={passed_count}, rejected={rejected_count}, "
            f"reasons={reasons}"
        )

    manifest_path = Path(output_dir) / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"CuratorKIT did not create its manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "input_examples": expected_count,
        "passed_examples": passed_count,
        "rejected_examples": rejected_count,
        "curatorkit_manifest": str(manifest_path),
        "curatorkit_manifest_data": manifest,
        "output_dir": str(output_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Source dataset JSONL.")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Directory for CuratorKIT artifacts and Alpaca export.")
    args = parser.parse_args()
    print(json.dumps(curate_dataset(args.input, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
