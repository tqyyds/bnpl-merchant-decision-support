from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.bnpl_analysis.baselines import (
    fraud_predictors,
    load_development_data,
    ndcg_at_k,
    ranking_metrics,
    ridge_pipeline,
)


def test_ndcg_is_one_for_ideal_ranking_and_lower_when_reversed():
    actual = np.array([10.0, 4.0, 1.0])
    assert ndcg_at_k(actual, actual, 3) == pytest.approx(1.0)
    assert ndcg_at_k(actual, -actual, 3) < 1.0


def test_ranking_metrics_reconcile_top_k_revenue():
    frame = pd.DataFrame({
        "cutoff": pd.to_datetime(["2022-01-01"] * 3),
        "target_revenue": [100.0, 50.0, 1.0],
        "prediction": [0.0, 2.0, 1.0],
    })
    result = ranking_metrics(frame, "prediction", 2).iloc[0]
    assert result["top_100_realised_revenue_aud"] == 51.0
    assert result["oracle_top_100_revenue_aud"] == 150.0
    assert result["oracle_capture_at_100"] == pytest.approx(51 / 150)


def test_train_fitted_ridge_handles_unknown_validation_category():
    train = pd.DataFrame({"numeric": [1.0, np.nan, 3.0], "category": ["a", "b", "a"]})
    validation = pd.DataFrame({"numeric": [np.nan], "category": ["never_seen"]})
    model = ridge_pipeline(train, ["numeric", "category"], alpha=1.0)
    model.fit(train, np.log1p([1.0, 2.0, 3.0]))
    assert np.isfinite(model.predict(validation)).all()


def test_fraud_feature_family_is_explicit():
    columns = ["hist_gmv", "hist_consumer_signal_days", "hist_merchant_probability_mean"]
    assert fraud_predictors(columns) == columns[1:]


def test_development_loader_never_opens_test(monkeypatch, tmp_path: Path):
    model_dir = tmp_path / "tables/modeling/run"
    report_dir = tmp_path / "reports/time_split"
    model_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (report_dir / "manifest.json").write_text(
        '{"config":{"snapshot_run_id":"run"}}', encoding="utf-8"
    )
    x = pd.DataFrame({
        "merchant_abn": ["1"], "cutoff": pd.to_datetime(["2022-01-01"]), "hist_gmv": [1.0]
    })
    y = pd.DataFrame({
        "merchant_abn": ["1"], "cutoff": pd.to_datetime(["2022-01-01"]), "target_revenue": [1.0]
    })
    for split in ["train", "validation", "test"]:
        x.to_parquet(model_dir / f"{split}_features.parquet", index=False)
        y.to_parquet(model_dir / f"{split}_labels.parquet", index=False)
    opened = []
    original = pd.read_parquet

    def recording_reader(path, *args, **kwargs):
        opened.append(Path(path).name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", recording_reader)
    config = {
        "snapshot_run_id": "run", "target_column": "target_revenue",
        "allowed_input_splits": ["train", "validation"],
    }
    load_development_data(tmp_path, config)
    assert opened == [
        "train_features.parquet", "train_labels.parquet",
        "validation_features.parquet", "validation_labels.parquet",
    ]
