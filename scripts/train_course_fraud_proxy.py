"""Train the course-only proxy fraud models and emit immutable shadow artifacts."""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from engines.contracts import save, sha
from engines.course_fraud import (
    CourseFraudModel,
    PointInTimeFraudFeatures,
    SigmoidCalibrator,
    aggregate_merchant_evidence,
    classification_metrics,
    deterministic_negative_sample,
    label_sensitivity_metrics,
    select_proxy_champion,
)
from src.bnpl_analysis.common import clean_paths, partition_date, read_partition


READ_COLUMNS = [
    "order_id",
    "order_datetime",
    "user_id",
    "merchant_abn",
    "dollar_value",
    "consumer_fraud_signal_present",
    "merchant_fraud_signal_present",
]


def _dates(config: dict) -> dict[str, pd.Timestamp]:
    names = (
        "train_start", "train_end", "calibration_start", "calibration_end",
        "validation_start", "validation_end", "test_start", "test_end",
    )
    values = {name: pd.Timestamp(config[name]).normalize() for name in names}
    ordered = [values[name] for name in names]
    if ordered != sorted(ordered):
        raise ValueError("Fraud split dates must be chronological")
    for left, right in (("train_end", "calibration_start"), ("calibration_end", "validation_start"), ("validation_end", "test_start")):
        if values[right] != values[left] + pd.Timedelta(days=1):
            raise ValueError("Fraud split periods must be contiguous")
    return values


def _validate_config(config: dict) -> None:
    if config.get("label_semantics") != "OBSERVED_COURSE_DELTA_NOT_FINAL_ADJUDICATION":
        raise ValueError("Proxy label semantics must be explicit")
    if config.get("fraud_model_status") != "PROXY_SHADOW":
        raise ValueError("Course fraud model must remain PROXY_SHADOW")
    if config.get("loss_model_status") != "NOT_AVAILABLE":
        raise ValueError("Loss model must remain NOT_AVAILABLE")
    if config.get("ranking_penalty_enabled") or config.get("portfolio_loss_constraint_enabled"):
        raise ValueError("Course proxy training cannot activate ranking or loss constraints")
    if config.get("model_candidates", {}).get("calibration_method") != "sigmoid":
        raise ValueError("Version 1 supports independent sigmoid calibration only")
    if pd.Timestamp(config.get("proxy_label_coverage_end")) != pd.Timestamp(config.get("test_end")):
        raise ValueError("Locked test must end at the declared proxy-label coverage end")
    _dates(config)


def _split(day: pd.Timestamp, dates: dict[str, pd.Timestamp]) -> str | None:
    for name in ("train", "calibration", "validation", "test"):
        if dates[f"{name}_start"] <= day <= dates[f"{name}_end"]:
            return name
    return None


def build_feature_sets(root: Path, config: dict) -> dict[str, pd.DataFrame]:
    staging, _, files = clean_paths(root, config["cleaning_run_id"])
    dates = _dates(config)
    master = pd.read_parquet(staging / "merchant_master.parquet", columns=["merchant_abn", "merchant_category"])
    master["merchant_abn"] = master["merchant_abn"].astype(str).str.zfill(11)
    categories = master.drop_duplicates("merchant_abn").set_index("merchant_abn")["merchant_category"]
    builder = PointInTimeFraudFeatures()
    parts: dict[str, list[pd.DataFrame]] = {name: [] for name in ("train", "train_cv", "calibration", "validation", "test", "evidence")}
    cv_start = dates["train_end"] - pd.Timedelta(days=83)
    evidence_start = dates["test_end"] - pd.Timedelta(days=int(config["evidence_window_days"]) - 1)

    coverage_ends = []
    for source_name in ("consumer_daily.parquet", "merchant_daily.parquet"):
        source = pd.read_parquet(staging / "fraud" / source_name, columns=["order_datetime"])
        coverage_ends.append(pd.to_datetime(source["order_datetime"]).max().normalize())
    if any(day != dates["test_end"] for day in coverage_ends):
        raise ValueError(f"Configured test end does not match fraud-source coverage: {coverage_ends}")

    for number, path in enumerate(files, start=1):
        day = partition_date(path)
        if day > dates["test_end"]:
            break
        raw = read_partition(path, READ_COLUMNS)
        features = builder.transform_then_update(raw, categories, label_variant="UNION_PROPAGATED")
        role = _split(day, dates)
        if role == "train":
            if day >= cv_start:
                parts["train_cv"].append(features)
            sampled, weights = deterministic_negative_sample(features, float(config["negative_sample_rate"]))
            sampled["_sample_weight"] = weights
            parts["train"].append(sampled)
        elif role is not None:
            parts[role].append(features)
        if evidence_start <= day <= dates["test_end"]:
            parts["evidence"].append(features)
        if number % 60 == 0 or day == dates["test_end"]:
            print(f"Point-in-time fraud features through {day.date()}: {number} days", flush=True)

    output = {name: pd.concat(rows, ignore_index=True) for name, rows in parts.items() if rows}
    required = set(parts) - {"train_cv"}
    if required - set(output):
        raise ValueError(f"Incomplete fraud feature periods: {sorted(required - set(output))}")
    for name, frame in output.items():
        if frame["order_id"].duplicated().any():
            raise ValueError(f"Duplicate order_id in {name}")
    return output


def _candidate_specs(config: dict) -> list[dict]:
    candidates = config["model_candidates"]
    specs = [
        {"kind": "logistic", "c": float(c), "n_knots": 6}
        for c in candidates["linear_logistic_c"]
    ]
    specs.extend(
        {"kind": "spline_gam", "c": float(c), "n_knots": int(knots)}
        for knots in candidates["spline_gam_n_knots"]
        for c in candidates["spline_gam_c"]
    )
    return specs


def _new_model(spec: dict, config: dict, include_history: bool = True) -> CourseFraudModel:
    qa = config["spline_qa"]
    return CourseFraudModel(
        kind=spec["kind"],
        c=spec["c"],
        n_knots=spec["n_knots"],
        include_history_proxy_rates=include_history,
        spline_min_unique=int(qa["minimum_unique_values"]),
        spline_max_zero_share=float(qa["maximum_zero_share"]),
    )


def tune_candidates(frames: dict[str, pd.DataFrame], config: dict) -> tuple[dict[str, dict], list[dict]]:
    train = frames["train"]
    full = frames["train_cv"]
    end = _dates(config)["train_end"]
    starts = [end - pd.Timedelta(days=value) for value in (83, 55, 27)]
    reports = []
    for spec in _candidate_specs(config):
        folds = []
        for start in starts:
            stop = start + pd.Timedelta(days=27)
            fit = train.loc[train["order_datetime"].lt(start)]
            holdout = full.loc[full["order_datetime"].between(start, stop, inclusive="both")]
            if fit.empty or holdout.empty:
                raise ValueError("Insufficient internal temporal-fold data")
            model = _new_model(spec, config).fit(fit, fit["_sample_weight"].to_numpy())
            folds.append(classification_metrics(
                holdout,
                model.predict_proba(holdout),
                review_capacities=tuple(config["review_capacities"]),
            ))
        reports.append({
            "spec": spec,
            "mean_pr_auc": float(np.mean([row["pr_auc"] for row in folds])),
            "mean_brier_score": float(np.mean([row["brier_score"] for row in folds])),
            "folds": folds,
        })
        print(f"Candidate complete: {spec}", flush=True)
    selected = {}
    for kind in ("logistic", "spline_gam"):
        family = [row for row in reports if row["spec"]["kind"] == kind]
        selected[kind] = sorted(family, key=lambda row: (-row["mean_pr_auc"], row["mean_brier_score"], str(row["spec"])))[0]["spec"]
    return selected, reports


def fit_and_calibrate(spec: dict, frames: dict[str, pd.DataFrame], config: dict, include_history: bool = True):
    train = frames["train"]
    model = _new_model(spec, config, include_history=include_history).fit(
        train, train["_sample_weight"].to_numpy()
    )
    calibration = frames["calibration"]
    calibrator = SigmoidCalibrator().fit(model.predict_proba(calibration), calibration["is_fraud"])
    return model, calibrator


def calibrated_probability(model: CourseFraudModel, calibrator: SigmoidCalibrator, frame: pd.DataFrame) -> np.ndarray:
    return calibrator.predict(model.predict_proba(frame))


def _source_lineage(root: Path, cleaning_run_id: str) -> dict:
    lineage_path = root / "tables" / "modeling" / "rolling_90d_28d_v3" / "manifest.json"
    reference_path = root / "reports" / "etl" / f"{cleaning_run_id}_manifest.json"
    if not lineage_path.is_file() or not reference_path.is_file():
        raise FileNotFoundError("Both rolling-v3 and accepted cleaning manifests are required")
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    candidates = [
        row for row in lineage.get("input_files", [])
        if str(row.get("path", "")).endswith(f"/{cleaning_run_id}_manifest.json")
    ]
    if len(candidates) != 1:
        raise ValueError("Rolling-v3 manifest must identify exactly one cleaning manifest")
    expected = candidates[0]["sha256"]
    actual = sha(reference_path)
    if actual != expected:
        raise ValueError("Accepted cleaning manifest does not match rolling-v3 lineage")
    return {
        "lineage_manifest_path": str(lineage_path.relative_to(root)).replace("\\", "/"),
        "lineage_manifest_sha256": sha(lineage_path),
        "source_manifest_path": str(reference_path.relative_to(root)).replace("\\", "/"),
        "source_manifest_sha256": actual,
        "recorded_source_path": candidates[0]["path"],
    }


def finalize_incomplete_run(root: Path, run_id: str, config_path: Path) -> Path:
    """Complete a run that stopped after outputs but before manifest/_SUCCESS."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)
    destination = root / "artifacts" / "course_fraud_proxy" / run_id
    state_path = destination / "state.json"
    if not state_path.is_file() or json.loads(state_path.read_text())["status"] != "IN_PROGRESS":
        raise ValueError("Only an explicit IN_PROGRESS proxy run may be finalized")
    if (destination / "_SUCCESS").exists() or (destination / "manifest.json").exists():
        raise ValueError("Completed or manifested runs are immutable")
    outputs = [
        destination / "temporal_tuning.json", destination / "models.pkl",
        destination / "locked_test_predictions.parquet", destination / "merchant_fraud_evidence.parquet",
        destination / "evaluation.json",
    ]
    missing = [str(path) for path in outputs if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(f"Incomplete proxy outputs: {missing}")
    evaluation = json.loads((destination / "evaluation.json").read_text(encoding="utf-8"))
    expected_state = (
        evaluation.get("fraud_model_status"), evaluation.get("loss_model_status"),
        evaluation.get("risk_status"), evaluation.get("portfolio_loss_constraint_enabled"),
    )
    if expected_state != ("PROXY_SHADOW", "NOT_AVAILABLE", "EVIDENCE_ONLY_NO_LOSS_LABELS", False):
        raise ValueError("Evaluation state cannot be finalized")
    lineage = _source_lineage(root, config["cleaning_run_id"])
    manifest = {
        "run_id": run_id,
        "status": "COMPLETE_PROXY_SHADOW",
        "config_path": str(config_path.resolve()),
        "config_sha256": sha(config_path),
        **lineage,
        "outputs": [{
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": sha(path),
        } for path in outputs],
        "prohibited_claims": [
            "final confirmed fraud probability", "realised or expected financial loss",
            "validated production risk model", "optimal risk penalty lambda",
        ],
    }
    save(manifest, destination / "manifest.json")
    save({
        "status": "COMPLETE_PROXY_SHADOW",
        "fraud_model_status": "PROXY_SHADOW",
        "loss_model_status": "NOT_AVAILABLE",
        "locked_test_opened_once": True,
    }, state_path)
    (destination / "_SUCCESS").touch()
    return destination


def run(root: Path, run_id: str, config_path: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)
    destination = root / "artifacts" / "course_fraud_proxy" / run_id
    destination.mkdir(parents=True, exist_ok=False)
    save({"status": "IN_PROGRESS", "loss_model_status": "NOT_AVAILABLE"}, destination / "state.json")

    frames = build_feature_sets(root, config)
    selected, tuning = tune_candidates(frames, config)
    save(tuning, destination / "temporal_tuning.json")

    fitted = {}
    validation_reports = {}
    validation_probability = {}
    for family in ("logistic", "spline_gam"):
        model, calibrator = fit_and_calibrate(selected[family], frames, config)
        probability = calibrated_probability(model, calibrator, frames["validation"])
        fitted[family] = (model, calibrator)
        validation_probability[family] = probability
        validation_reports[family] = classification_metrics(
            frames["validation"], probability, tuple(config["review_capacities"])
        )

    ablation_model, ablation_calibrator = fit_and_calibrate(
        selected["spline_gam"], frames, config, include_history=False
    )
    ablation_probability = calibrated_probability(ablation_model, ablation_calibrator, frames["validation"])
    validation_reports["spline_gam_no_history_proxy_rate"] = classification_metrics(
        frames["validation"], ablation_probability, tuple(config["review_capacities"])
    )

    champion, champion_checks = select_proxy_champion(
        validation_reports["logistic"], validation_reports["spline_gam"]
    )
    model, calibrator = fitted[champion]
    test_probability = calibrated_probability(model, calibrator, frames["test"])
    test_report = classification_metrics(frames["test"], test_probability, tuple(config["review_capacities"]))
    sensitivity = {
        "validation": label_sensitivity_metrics(
            frames["validation"], validation_probability[champion], tuple(config["review_capacities"])
        ),
        "locked_test": label_sensitivity_metrics(
            frames["test"], test_probability, tuple(config["review_capacities"])
        ),
    }

    primary_capacity = f"{float(config['primary_review_capacity']):.4f}"
    threshold = validation_reports[champion]["review_capacity"][primary_capacity]["probability_threshold"]
    evidence = frames["evidence"].copy()
    evidence["predicted_course_fraud_probability"] = calibrated_probability(model, calibrator, evidence)
    merchant = aggregate_merchant_evidence(evidence, config["test_end"], threshold)
    merchant["fraud_model_version"] = model.model_name
    merchant["probability_calibration"] = "sigmoid_on_independent_complete_period"

    test_predictions = frames["test"][[
        "order_id", "order_datetime", "merchant_abn", "is_fraud", "course_label_source",
        "consumer_day_match_multiplicity", "merchant_day_match_multiplicity",
        "fraud_label_version", "fraud_label_semantics",
    ]].copy()
    test_predictions["predicted_course_fraud_probability"] = test_probability
    test_predictions["fraud_model_version"] = model.model_name
    test_predictions["fraud_model_status"] = "PROXY_SHADOW"
    test_predictions.to_parquet(destination / "locked_test_predictions.parquet", index=False)
    merchant.to_parquet(destination / "merchant_fraud_evidence.parquet", index=False)
    with (destination / "models.pkl").open("wb") as stream:
        pickle.dump({
            "selected_specs": selected,
            "models": fitted,
            "ablation": (ablation_model, ablation_calibrator),
            "champion": champion,
        }, stream)

    evaluation = {
        "claim_scope": "COURSE_PROXY_ONLY_NOT_FINAL_FRAUD_OR_FINANCIAL_LOSS",
        "champion_family": champion,
        "champion_model_version": model.model_name,
        "champion_checks": champion_checks,
        "selected_specs": selected,
        "validation": validation_reports,
        "locked_test": test_report,
        "label_sensitivity": sensitivity,
        "spline_qa": fitted["spline_gam"][0].spline_qa,
        "ablation_interpretation": "Compare full and no-history-proxy-rate models; a large gap indicates persistence in the supplied proxy signal.",
        "high_risk_threshold_source": {
            "period": "validation",
            "review_capacity": float(config["primary_review_capacity"]),
            "probability_threshold": float(threshold),
        },
        "fraud_model_status": "PROXY_SHADOW",
        "loss_model_status": "NOT_AVAILABLE",
        "risk_status": "EVIDENCE_ONLY_NO_LOSS_LABELS",
        "ranking_penalty_enabled": False,
        "portfolio_loss_constraint_enabled": False,
    }
    save(evaluation, destination / "evaluation.json")
    return finalize_incomplete_run(root, run_id, config_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config", default="config/course_fraud_model_v1.json")
    parser.add_argument("--finalize-incomplete", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config_path = (root / args.config).resolve()
    output = finalize_incomplete_run(root, args.run_id, config_path) if args.finalize_incomplete else run(root, args.run_id, config_path)
    print(f"Course proxy fraud artifacts: {output}", flush=True)
