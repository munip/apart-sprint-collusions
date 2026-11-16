"""Rebuild a run directory's episodes.csv from its saved episode.json files."""
from __future__ import annotations

import argparse
from pathlib import Path

from collusion_lab.experiments import episodes_table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Experiment output directory")
    args = parser.parse_args()
    if not args.run_dir.is_dir():
        parser.error(f"run directory does not exist: {args.run_dir}")

    episodes = episodes_table(args.run_dir)
    if episodes.empty:
        parser.error(f"no episode.json files found in {args.run_dir}")

    print(f"Rebuilt {args.run_dir / 'episodes.csv'} with {len(episodes)} episodes.")
    if "condition" in episodes:
        for condition, count in episodes["condition"].value_counts().sort_index().items():
            print(f"  {condition}: {count}")


if __name__ == "__main__":
    main()
