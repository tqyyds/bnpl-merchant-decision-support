"""Fit and compare development baselines without opening protected test files."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.bnpl_analysis.baselines import run_baselines


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, help='Baseline config with explicit snapshot and baseline run IDs')
    args = parser.parse_args()
    result = run_baselines(ROOT, args.config)
    print(json.dumps({
        "status": result["status"],
        "selection": result["selection"],
        "development_protocol": result["development_protocol"],
    }, indent=2))
