"""Run historical EDA / temporal splitting locally; safe to run from PyCharm."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.bnpl_analysis.eda import run_eda
from src.bnpl_analysis.common import load_config
from src.bnpl_analysis.time_split import build_time_splits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["eda", "split", "all"], default="eda")
    parser.add_argument("--config", type=Path, help="Optional analysis config path")
    parser.add_argument(
        "--cleaning-run-id",
        help="Local ETL run override; avoids committing contributor-specific run IDs",
    )
    args = parser.parse_args()
    config = load_config(ROOT, args.config, args.cleaning_run_id)
    if args.stage in {"eda", "all"}:
        print(json.dumps(run_eda(ROOT, config), indent=2))
    if args.stage in {"split", "all"}:
        print(json.dumps(build_time_splits(ROOT, config), indent=2))


if __name__ == "__main__":
    main()
