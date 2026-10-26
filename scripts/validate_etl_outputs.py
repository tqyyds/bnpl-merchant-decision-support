"""Independent acceptance checks for a completed BNPL ETL run."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import hashlib
import json
import sys

import pandas as pd
import pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.run_artifacts import etl_manifest_path


def sha256(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest().upper()


def validate(repo_root: Path, run_id: str) -> dict:
    staging = repo_root / "tables" / "staging" / run_id
    curated = repo_root / "tables" / "curated" / run_id
    report_path = etl_manifest_path(repo_root, run_id)
    if not (staging / "_SUCCESS").exists() or not (curated / "_SUCCESS").exists():
        raise AssertionError("Missing ETL _SUCCESS marker")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    transaction_files = sorted((staging / "transactions").rglob("*.parquet"))
    assert len(transaction_files) == 606
    transaction_rows = sum(pq.ParquetFile(path).metadata.num_rows for path in transaction_files)
    assert transaction_rows == 14_195_505
    schemas = {str(pq.read_schema(path)) for path in transaction_files}
    assert len(schemas) == 1

    merchants = pd.read_parquet(curated / "merchant_features.parquet")
    assert len(merchants) == 4_422 and merchants["merchant_abn"].is_unique
    assert int(merchants["candidate_eligible"].sum()) == 4_026
    assert int(merchants["merchant_master_status"].eq("missing").sum()) == 396
    assert int(merchants.loc[merchants["merchant_master_status"].eq("missing"), "transaction_count"].sum()) == 580_830
    assert int(merchants["transaction_count"].sum()) == transaction_rows
    assert int(merchants["consumer_fraud_signal_orders"].sum()) == 80_348
    assert int(merchants["merchant_fraud_signal_orders"].sum()) == 4_059
    assert int(merchants["any_fraud_signal_orders"].sum()) == 84_002

    consumers = pd.read_parquet(staging / "consumers.parquet")
    if 'consumer_privacy' in report['policy']:
        assert not {'name', 'address', 'gender'}.intersection(consumers.columns)
    assert len(consumers) == 499_999 and consumers["consumer_id"].is_unique
    assert consumers["geo_match_status"].value_counts().to_dict() == {
        "matched_poa": 416_334,
        "postcode_absent_nationally": 83_035,
        "state_postcode_mismatch": 484,
        "poa_feature_unavailable": 146,
    }
    assert consumers["seifa_match_status"].value_counts().to_dict() == {
        "matched": 413_641,
        "not_geo_matched": 83_665,
        "poa_score_unavailable": 2_693,
    }
    no_poa_assignment = consumers["geo_match_status"].isin(
        ["postcode_absent_nationally", "state_postcode_mismatch"]
    )
    no_poa_features = consumers["geo_match_status"].ne("matched_poa")
    assert consumers.loc[no_poa_assignment, "poa_code_2021"].isna().all()
    assert consumers.loc[no_poa_features, "population_persons"].isna().all()

    consumer_fraud = pd.read_parquet(staging / "fraud" / "consumer_daily.parquet")
    merchant_fraud = pd.read_parquet(staging / "fraud" / "merchant_daily.parquet")
    assert len(consumer_fraud) == 34_765
    assert not consumer_fraud.duplicated(["user_id", "order_datetime"]).any()
    assert len(merchant_fraud) == 114
    assert not merchant_fraud.duplicated(["merchant_abn", "order_datetime"]).any()

    crosswalk = pd.read_parquet(staging / "merchant_category_crosswalk.parquet")
    assert crosswalk["merchant_category_raw"].nunique() == 971
    assert crosswalk["merchant_category"].nunique() == 25

    inventory = report["output_inventory"]
    registered = {entry["path"]: entry for entry in inventory}
    actual_files = sorted([*staging.rglob("*.parquet"), *curated.rglob("*.parquet")])
    assert len(actual_files) == len(registered) == 613
    for path in actual_files:
        relative = str(path.relative_to(repo_root)).replace("\\", "/")
        entry = registered[relative]
        assert path.stat().st_size == entry["bytes"]
        assert sha256(path) == entry["sha256"]

    return {
        "transaction_rows": transaction_rows,
        "transaction_partitions": len(transaction_files),
        "merchant_rows": len(merchants),
        "candidate_eligible_merchants": int(merchants["candidate_eligible"].sum()),
        "unknown_merchants": int(merchants["merchant_master_status"].eq("missing").sum()),
        "consumer_rows": len(consumers),
        "geo_match_status": consumers["geo_match_status"].value_counts().to_dict(),
        "seifa_match_status": consumers["seifa_match_status"].value_counts().to_dict(),
        "consumer_fraud_rows": len(consumer_fraud),
        "merchant_fraud_rows": len(merchant_fraud),
        "output_files_hashed": len(actual_files),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", default="v1_2")
    args = parser.parse_args()
    result = validate(args.repo_root.resolve(), args.run_id)
    print(json.dumps(result, indent=2))
    print("PASS: independent ETL output validation")


if __name__ == "__main__":
    main()
