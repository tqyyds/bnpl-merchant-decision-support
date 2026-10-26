from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.bnpl_analysis.common import load_config
from src.bnpl_analysis.feature_qa import run_feature_qa

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    result = run_feature_qa(ROOT, load_config(ROOT,args.config))
    print(f"PASS: {result['predictor_count']} predictors, {result['development_rows']:,} development rows; no test values read")
