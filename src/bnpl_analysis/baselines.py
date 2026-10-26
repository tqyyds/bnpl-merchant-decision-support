"""Validation-only merchant-ranking baselines with train-fitted preprocessing.

This module deliberately has no test-split argument. It reads only the train and
validation feature/label files and publishes aggregate validation evidence.
"""
from __future__ import annotations

import hashlib
import json
import importlib.metadata
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from .common import load_config, markdown_table, save_json
from src.run_artifacts import (claim_run, finish_run, file_hash, inventory, provenance,
                               snapshot_manifest_path, validate_run_id)


KEYS = ["merchant_abn", "cutoff"]
FRAUD_TOKENS = ("consumer_signal", "consumer_probability", "merchant_signal", "merchant_probability")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_baseline_config(root: Path, path: Path | None = None) -> dict:
    value = json.loads((path or root / "config/baseline_v1.json").read_text(encoding="utf-8"))
    for key in ('baseline_run_id', 'snapshot_run_id'):
        validate_run_id(value[key])
    if value["allowed_input_splits"] != ["train", "validation"]:
        raise ValueError("Baseline selection may read only train and validation")
    if int(value["ranking_k"]) < 1:
        raise ValueError("ranking_k must be positive")
    return value


def load_development_data(root: Path, config: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict, list[dict]]:
    """Load aligned development rows; protected test files are never opened."""
    snapshot_dir = root / "tables/modeling" / config["snapshot_run_id"]
    manifest = json.loads(snapshot_manifest_path(root, config['snapshot_run_id']).read_text(encoding="utf-8"))
    if manifest["config"]["snapshot_run_id"] != config["snapshot_run_id"]:
        raise ValueError("Baseline and snapshot manifests disagree")
    inputs: list[dict] = []
    frames: dict[str, pd.DataFrame] = {}
    for split in config["allowed_input_splits"]:
        if split not in {"train", "validation"}:
            raise ValueError(f"Protected split requested: {split}")
        feature_path = snapshot_dir / f"{split}_features.parquet"
        label_path = snapshot_dir / f"{split}_labels.parquet"
        x = pd.read_parquet(feature_path)
        y = pd.read_parquet(label_path)
        if x.duplicated(KEYS).any() or y.duplicated(KEYS).any():
            raise ValueError(f"Duplicate merchant-cutoff key in {split}")
        merged = x.merge(y[KEYS + [config["target_column"]]], on=KEYS, validate="one_to_one")
        if len(merged) != len(x) or len(x) != len(y):
            raise ValueError(f"Feature/label alignment failure in {split}")
        frames[split] = merged
        for kind, path in [("features", feature_path), ("labels", label_path)]:
            if manifest.get('protocol_version') == 'rolling_snapshot_v3':
                if not (snapshot_dir / '_SUCCESS').exists():
                    raise ValueError('Snapshot run is incomplete')
                registered = {value['path']: value for value in manifest['output_files']}
                expected = registered[path.relative_to(root).as_posix()]
                if expected['sha256'] != file_hash(path):
                    raise ValueError(f'Snapshot input changed after completion: {path.name}')
            inputs.append({
                "split": split,
                "kind": kind,
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
    return frames["train"], frames["validation"], manifest, inputs


def fraud_predictors(predictors: list[str]) -> list[str]:
    return [column for column in predictors if any(token in column for token in FRAUD_TOKENS)]


def _column_sets(frame: pd.DataFrame, predictors: list[str]) -> tuple[list[str], list[str]]:
    categorical = [column for column in predictors if not pd.api.types.is_numeric_dtype(frame[column])]
    numeric = [column for column in predictors if column not in categorical]
    return numeric, categorical


def ridge_pipeline(frame: pd.DataFrame, predictors: list[str], alpha: float) -> Pipeline:
    numeric, categorical = _column_sets(frame, predictors)
    transformer = ColumnTransformer([
        ("numeric", Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", StandardScaler()),
        ]), numeric),
        ("categorical", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ]), categorical),
    ])
    return Pipeline([("preprocess", transformer), ("model", Ridge(alpha=alpha))])


def tree_pipeline(frame: pd.DataFrame, predictors: list[str], settings: dict, seed: int) -> Pipeline:
    numeric, categorical = _column_sets(frame, predictors)
    transformer = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median", add_indicator=True), numeric),
        ("categorical", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
        ]), categorical),
    ], sparse_threshold=0)
    model = HistGradientBoostingRegressor(random_state=seed, **settings)
    return Pipeline([("preprocess", transformer), ("model", model)])


def ndcg_at_k(actual: np.ndarray, predicted: np.ndarray, k: int) -> float:
    """NDCG with non-negative linear revenue gain, suitable for currency targets."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    limit = min(k, len(actual))
    if limit == 0:
        return float("nan")
    discount = np.log2(np.arange(2, limit + 2))
    chosen = np.argsort(-predicted, kind="stable")[:limit]
    ideal = np.argsort(-actual, kind="stable")[:limit]
    ideal_dcg = float(np.sum(actual[ideal] / discount))
    return float(np.sum(actual[chosen] / discount) / ideal_dcg) if ideal_dcg > 0 else 1.0


def ranking_metrics(frame: pd.DataFrame, prediction_column: str, k: int) -> pd.DataFrame:
    rows = []
    for cutoff, group in frame.groupby("cutoff", sort=True):
        actual = group["target_revenue"].to_numpy(dtype=float)
        predicted = np.clip(group[prediction_column].to_numpy(dtype=float), 0, None)
        limit = min(k, len(group))
        chosen = np.argsort(-predicted, kind="stable")[:limit]
        ideal = np.argsort(-actual, kind="stable")[:limit]
        selected_revenue = float(actual[chosen].sum())
        oracle_revenue = float(actual[ideal].sum())
        rank_corr = pd.Series(actual).rank(method="average").corr(
            pd.Series(predicted).rank(method="average")
        )
        rows.append({
            "cutoff": str(pd.Timestamp(cutoff).date()),
            "rows": len(group),
            "mae": float(np.mean(np.abs(actual - predicted))),
            "spearman": float(rank_corr) if pd.notna(rank_corr) else 0.0,
            "ndcg_at_100": ndcg_at_k(actual, predicted, k),
            "top_100_realised_revenue_aud": selected_revenue,
            "oracle_top_100_revenue_aud": oracle_revenue,
            "oracle_capture_at_100": selected_revenue / oracle_revenue if oracle_revenue else 1.0,
        })
    return pd.DataFrame(rows)


def top_k_stability(frame: pd.DataFrame, prediction_column: str, k: int) -> float:
    sets = []
    for _, group in frame.groupby("cutoff", sort=True):
        selected = group.nlargest(min(k, len(group)), prediction_column)["merchant_abn"]
        sets.append(set(selected))
    values = [len(left & right) / len(left | right) for left, right in zip(sets, sets[1:])]
    return float(np.mean(values)) if values else float("nan")


def _fit_predict(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    predictors: list[str],
    factory: Callable[[], Pipeline],
) -> tuple[np.ndarray, Pipeline]:
    model = factory()
    model.fit(train[predictors], np.log1p(train["target_revenue"].to_numpy(dtype=float)))
    prediction = np.clip(np.expm1(model.predict(validation[predictors])), 0, None)
    if not np.isfinite(prediction).all():
        raise ValueError("Model emitted non-finite validation predictions")
    return prediction, model


def run_baselines(root: Path, config_path: Path | None = None) -> dict:
    config = load_baseline_config(root, config_path)
    artifact_dir = root / "artifacts" / config["baseline_run_id"]
    if artifact_dir.exists():
        raise FileExistsError(f'Baseline run already exists: {artifact_dir}; choose a new run ID')
    train, validation, manifest, inputs = load_development_data(root, config)
    claim_run(artifact_dir)
    target = config["target_column"]
    if target != "target_revenue":
        raise ValueError("The current metric contract requires target_revenue")
    predictors = list(manifest["predictor_columns"])
    excluded_fraud = fraud_predictors(predictors)
    no_fraud_predictors = [column for column in predictors if column not in excluded_fraud]
    predictions: dict[str, np.ndarray] = {
        "trailing_28d_revenue": np.clip(
            validation["hist_gmv_last28"].to_numpy() * validation["take_rate_pct"].to_numpy() / 100, 0, None
        ),
        "trailing_90d_run_rate": np.clip(
            validation["hist_revenue_proxy"].to_numpy()
            * manifest['config']['target_days'] / manifest['config']['history_days'], 0, None
        ),
    }
    fitted: dict[str, Pipeline] = {}
    model_specs = [
        ("ridge_log_all", predictors, lambda: ridge_pipeline(train, predictors, config["ridge_alpha"])),
        ("ridge_log_no_fraud", no_fraud_predictors,
         lambda: ridge_pipeline(train, no_fraud_predictors, config["ridge_alpha"])),
        ("hist_gradient_boosting_log_all", predictors,
         lambda: tree_pipeline(train, predictors, config["hist_gradient_boosting"], config["random_seed"])),
        ("hist_gradient_boosting_log_no_fraud", no_fraud_predictors,
         lambda: tree_pipeline(train, no_fraud_predictors, config["hist_gradient_boosting"], config["random_seed"])),
    ]
    for name, columns, factory in model_specs:
        predictions[name], fitted[name] = _fit_predict(train, validation, columns, factory)

    details = []
    aggregate = []
    scored = validation[KEYS + [target]].copy()
    for name, prediction in predictions.items():
        column = f"prediction__{name}"
        scored[column] = prediction
        metric_frame = ranking_metrics(scored, column, int(config["ranking_k"]))
        metric_frame.insert(0, "model", name)
        details.extend(metric_frame.to_dict(orient="records"))
        aggregate.append({
            "model": name,
            "mean_ndcg_at_100": float(metric_frame.ndcg_at_100.mean()),
            "mean_oracle_capture_at_100": float(metric_frame.oracle_capture_at_100.mean()),
            "mean_spearman": float(metric_frame.spearman.mean()),
            "mean_mae_aud": float(metric_frame.mae.mean()),
            "mean_top_100_realised_revenue_aud": float(metric_frame.top_100_realised_revenue_aud.mean()),
            "mean_top_100_jaccard_stability": top_k_stability(scored, column, int(config["ranking_k"])),
        })
    aggregate_frame = pd.DataFrame(aggregate).sort_values(
        [config["selection_primary_metric"], config["selection_tiebreak_metric"]],
        ascending=False,
    ).reset_index(drop=True)
    selected = aggregate_frame.iloc[0]["model"]

    output_dir = root / "reports/baseline" / config['baseline_run_id']
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(artifact_dir / "validation_predictions.parquet", index=False)
    for name, model in fitted.items():
        joblib.dump(model, artifact_dir / f"{name}.joblib")

    result = {
        "status": "PASS",
        "provenance": provenance(root, config),
        "baseline_run_id": config["baseline_run_id"],
        "snapshot_run_id": config["snapshot_run_id"],
        "development_protocol": {
            "input_splits": config["allowed_input_splits"],
            "train_rows": len(train),
            "validation_rows": len(validation),
            "validation_cutoffs": sorted(str(value.date()) for value in validation.cutoff.unique()),
            "preprocessing_fit_split": "train",
            "selection_split": "validation",
            "test_features_opened": False,
            "test_labels_opened": False,
            "test_evaluated": False,
        },
        "predictors": {
            "all_feature_count": len(predictors),
            "no_fraud_feature_count": len(no_fraud_predictors),
            "fraud_columns_excluded_in_no_fraud_variants": excluded_fraud,
        },
        "model_settings": config,
        "selection": {
            "selected_model": selected,
            "primary_metric": config["selection_primary_metric"],
            "tiebreak_metric": config["selection_tiebreak_metric"],
            "status": "validation_selected_not_tested",
        },
        "aggregate_validation_metrics": aggregate_frame.to_dict(orient="records"),
        "validation_metrics_by_cutoff": details,
        "input_files": inputs,
        "local_artifacts_git_ignored": [
            "validation_predictions.parquet",
            *[f"{name}.joblib" for name in fitted],
        ],
    }
    result['provenance']['runtime_versions']['scikit-learn'] = importlib.metadata.version('scikit-learn')
    result['provenance']['runtime_versions']['joblib'] = importlib.metadata.version('joblib')
    save_json(result, output_dir / "metrics.json")
    selected_predictors = {
        "trailing_28d_revenue": ["hist_gmv_last28", "take_rate_pct"],
        "trailing_90d_run_rate": ["hist_revenue_proxy"],
        "ridge_log_all": predictors,
        "hist_gradient_boosting_log_all": predictors,
        "ridge_log_no_fraud": no_fraud_predictors,
        "hist_gradient_boosting_log_no_fraud": no_fraud_predictors,
    }[selected]
    contract = {
        "contract_version": "baseline_model_contract_v2",
        "baseline_run_id": config['baseline_run_id'],
        "snapshot_run_id": config['snapshot_run_id'],
        "selected_model": selected,
        "selection_status": "validation_selected_not_tested",
        "target": manifest["config"]["target"],
        "feature_window_days": manifest["config"]["history_days"],
        "target_window_days": manifest["config"]["target_days"],
        "predictors": selected_predictors,
        "preprocessing_fit_split": "train",
        "selection_split": "validation",
        "protected_outcome_start": manifest["protected_outcome_start"],
        "test_opened": False,
        "test_evaluated": False,
        "next_gate": "independent review and explicit one-time primary-test evaluation",
        "input_files": inputs,
        "snapshot_manifest_sha256": file_hash(snapshot_manifest_path(root, config['snapshot_run_id'])),
        "provenance": result['provenance'],
    }
    save_json(contract, output_dir / "model_contract.json")
    save_json(contract, artifact_dir / "model_contract.json")
    save_json(result, artifact_dir / "metrics.json")
    save_json({'output_files': inventory(root, artifact_dir.glob('*.*'))}, artifact_dir / 'freeze.json')
    finish_run(artifact_dir)

    display = aggregate_frame.copy()
    for column in ["mean_ndcg_at_100", "mean_oracle_capture_at_100", "mean_spearman", "mean_top_100_jaccard_stability"]:
        display[column] = display[column].map(lambda value: f"{value:.4f}")
    for column in ["mean_mae_aud", "mean_top_100_realised_revenue_aud"]:
        display[column] = display[column].map(lambda value: f"{value:,.2f}")
    readme = f"""# Validation-only baseline comparison

## tl;dr

`{selected}` ranked first on mean validation NDCG@100. This is a development result, not a test
result. No test feature or label file was opened by this workflow, and the model is not presented as
final performance evidence.

## Context & Methods

Six models use the existing 90-day-history / next-28-day snapshot contract. The two trailing-revenue
rules require no fitting. Ridge and histogram gradient boosting are trained on `log1p(target_revenue)`;
predictions are transformed back to AUD and clipped at zero. Numeric medians, missingness indicators,
scaling, categorical imputation and encoding are fitted on train only. Fixed settings are versioned in
`config/baseline_v1.json`; validation is used only to compare the predeclared candidates.

NDCG uses non-negative linear revenue gain. Oracle capture is realised revenue from the predicted
Top 100 divided by realised revenue from the true Top 100 at the same cutoff. Stability is the mean
Jaccard overlap between consecutive validation Top-100 portfolios.

### Key Assumptions

- Merchant master attributes and fraud publication timing remain unversioned as documented upstream.
- Missing fraud means missing evidence, not zero risk; no-fraud variants test dependence on this source.
- Three validation cutoffs are limited evidence, so small differences should not be over-interpreted.

## Data

- Train: {len(train):,} merchant-cutoff rows across {train.cutoff.nunique()} cutoffs.
- Validation: {len(validation):,} rows across {validation.cutoff.nunique()} cutoffs.
- Test: sealed; not read or evaluated.

## Results

{markdown_table(display)}

## Takeaways

The selected validation candidate is frozen in `model_contract.json`. Before any primary-test access,
an independent review should confirm the metric implementation, input hashes, preprocessing boundary,
and selection rule. Boruta and TCN remain later experiments and must beat these baselines without
changing the protected test protocol.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return result
