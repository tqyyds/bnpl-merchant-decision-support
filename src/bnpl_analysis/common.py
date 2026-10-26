from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from src.run_artifacts import validate_run_id


def load_config(
    root: Path,
    config_path: Path | None = None,
    cleaning_run_id: str | None = None,
) -> dict:
    """Load a portable analysis config with an optional local ETL-run override."""
    path = config_path or root / "config/analysis_v1.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if cleaning_run_id:
        config["cleaning_run_id"] = cleaning_run_id
    for key in ('cleaning_run_id', 'analysis_run_id', 'snapshot_run_id'):
        validate_run_id(config[key])
    expected_target = f"next_{int(config['target_days'])}d_take_rate_revenue"
    if config["target"] != expected_target:
        raise ValueError(f"Target must be {expected_target!r} for the configured horizon")
    if config["external_context_in_predictors"] or config["full_dataset_tail_flags_in_predictors"]:
        raise ValueError("Unverified external context and full-period tail flags are not supported predictors")
    protected_start = pd.Timestamp(config["protected_outcome_start"])
    if pd.Timestamp(config["eda_end"]) >= protected_start:
        raise ValueError("EDA must end before the protected outcome period")
    if protected_start != pd.Timestamp(config["anchor_reference"]) + pd.Timedelta(days=1):
        raise ValueError("The anchor cutoff must be the day before protected outcomes begin")
    if int(config["validation_snapshot_count"]) < 1:
        raise ValueError("At least one pre-protection validation snapshot is required")
    return config


def clean_paths(root: Path, run_id: str) -> tuple[Path, Path, list[Path]]:
    staging = root / "tables/staging" / run_id
    curated = root / "tables/curated" / run_id
    for directory in (staging, curated):
        if not (directory / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Completed cleaned run required: {directory}")
    files = sorted((staging / "transactions").glob("order_datetime=*/*.parquet"))
    if not files:
        raise FileNotFoundError("No cleaned transaction partitions")
    dates = [partition_date(path) for path in files]
    if dates != list(pd.date_range(min(dates), max(dates), freq="D")):
        raise ValueError("Cleaned transaction dates are duplicated or discontinuous")
    return staging, curated, files


def partition_date(path: Path) -> pd.Timestamp:
    return pd.Timestamp(path.parent.name.split("=", 1)[1])


def read_partition(path: Path, columns: list[str]) -> pd.DataFrame:
    # ParquetFile avoids accidental Hive partition schema inference.
    frame = pq.ParquetFile(path).read(columns=columns).to_pandas()
    if "order_datetime" in frame:
        expected = partition_date(path)
        if not pd.to_datetime(frame["order_datetime"]).eq(expected).all():
            raise ValueError(f"Partition/date mismatch: {path.name}")
    return frame


def markdown_table(frame: pd.DataFrame) -> str:
    values = frame.astype(str)
    header = "| " + " | ".join(map(str, frame.columns)) + " |"
    separator = "| " + " | ".join("---" for _ in frame.columns) + " |"
    rows = ["| " + " | ".join(row) + " |" for row in values.to_numpy()]
    return "\n".join([header, separator, *rows])


def save_json(value: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
