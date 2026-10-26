"""Versioned engine-output adapter. All source access is read-only and allow-listed."""
from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

import pandas as pd
import numpy as np
import pyarrow.parquet as pq

API_VERSION = "1.0"
ENGINES = ("revenue", "eligibility", "confidence", "risk", "diversification", "strategic_fit", "portfolio")
SPLITS = ("latest", "test", "validation")
REQUIRED = ("predictions", "portfolios", "candidate_dispositions", "revenue", "eligibility")
BASE = ["merchant_abn", "cutoff"]
FIELDS = {
    "predictions": BASE + ["merchant_name", "merchant_category", "course_group", "history_start", "history_end", "prediction", "hist_orders", "hist_unique_customers", "hist_active_days", "hist_revenue_proxy", "hist_repeat_customer_rate", "hist_growth_28d"],
    "candidate_dispositions": BASE + ["merchant_name", "merchant_category", "candidate_disposition", "eligible", "reason_codes"],
    "portfolios": BASE + ["scenario", "global_rank"],
    "group_top10": BASE + ["course_group", "group_rank"],
    "revenue": BASE + ["prediction", "engine_version", "policy_version"],
    "eligibility": BASE + ["eligible", "reason_codes", "status", "registry_status", "engine_version", "policy_version"],
    "confidence": BASE + ["lower", "upper", "revenue_reliability", "confidence_band", "engine_version", "policy_version", "recommended_action", "decision_reason_codes", "interval_status", "rank_boundary_status", "supporting_history_status", "representativeness_status", "environment_status"],
    "risk": BASE + ["hist_consumer_probability_max", "hist_merchant_probability_max", "hist_consumer_signal_coverage", "hist_merchant_signal_calendar_coverage", "hist_consumer_signal_recency_days", "hist_merchant_signal_recency_days", "review_prompt_50", "review_prompt_80", "risk_status", "engine_version", "policy_version"],
    "diversification": BASE + ["marginal_category_hhi", "engine_version", "policy_version"],
    "strategic_fit": BASE + ["strategic_score", "strategic_status", "engine_version", "policy_version"],
    "portfolio": BASE + ["engine_version", "policy_version"],
}
MANDATORY = {
    "predictions": BASE + ["prediction", "merchant_category", "course_group"],
    "candidate_dispositions": BASE + ["eligible", "candidate_disposition"],
    "portfolios": BASE + ["scenario", "global_rank"],
    "revenue": BASE + ["prediction"],
    "eligibility": BASE + ["eligible", "reason_codes"],
    "confidence": BASE + ["lower", "upper", "revenue_reliability", "confidence_band"],
    "risk": BASE + ["risk_status"],
    "strategic_fit": BASE + ["strategic_status"],
    "diversification": BASE + ["marginal_category_hhi"],
    "portfolio": BASE,
    "group_top10": BASE + ["course_group", "group_rank"],
}


class ContractError(ValueError):
    """An actionable source/contract error, safe to expose to the local UI."""


def safe_token(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value) or ".." in value:
        raise ContractError("Invalid run or scenario identifier")
    return value


def clean(value):
    """JSON null preserves unknown evidence; never replace it with zero."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


@lru_cache(maxsize=96)
def _read_cached(path: str, stamp: int, size: int, columns: tuple):
    file = Path(path)
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    frame = pq.read_table(file, columns=list(columns)).to_pandas()
    after = file.stat()
    if (after.st_mtime_ns, after.st_size) != (stamp, size):
        raise ContractError("Engine output changed while loading. Refresh after the run finishes.")
    return frame, digest


class EngineAdapter:
    def __init__(self, engine_root: Path, config: dict | None = None):
        self.root = Path(engine_root).resolve()
        self.config = config or {}
        self.mapping = self.config.get("columns", {})
        if self.config.get("adapter", "seven-engine-files-v1") != "seven-engine-files-v1":
            raise ContractError("Unsupported adapter. Register a new adapter for the changed engine format.")
        self.artifacts = self.root / self.config.get("artifact_directory", "artifacts/seven_engines")
        if not self.artifacts.resolve().is_relative_to(self.root):
            raise ContractError("Artifact directory must stay inside the configured engine root")

    def run_path(self, run):
        path = (self.artifacts / safe_token(run)).resolve()
        if not path.is_relative_to(self.root) or not path.is_dir():
            raise ContractError("Engine run not found in the configured source")
        return path

    @staticmethod
    def json_file(path: Path, default=None):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ContractError(f"Cannot read {path.name}: invalid JSON or unavailable source") from exc

    def table_path(self, folder, name):
        return folder / f"{name}.parquet"

    def column_mapping(self, folder, name):
        return self.mapping.get(name, {})

    def table(self, folder: Path, name: str, hashes: dict | None = None):
        path = self.table_path(folder, name)
        if not path.is_file():
            raise ContractError(f"Missing {name}.parquet; finish the run or update the adapter")
        mapping = self.column_mapping(folder, name)
        try:
            present = pq.ParquetFile(path).schema_arrow.names
            mandatory = MANDATORY[name]
            missing = [k for k in mandatory if mapping.get(k, k) not in present]
            if missing:
                raise ContractError(f"{name}: required fields missing: {', '.join(missing)}. Update the column mapping.")
            wanted = FIELDS[name]
            if len(set(mapping.get(k, k) for k in wanted)) != len(wanted):
                raise ContractError(f"{name}: column mapping must not merge canonical fields")
            columns = tuple(dict.fromkeys(mapping.get(k, k) for k in wanted if mapping.get(k, k) in present))
            stat = path.stat()
            raw, digest = _read_cached(str(path), stat.st_mtime_ns, stat.st_size, columns)
            if hashes is not None and hashes.get(f"{name}.parquet", "").lower() != digest:
                raise ContractError(f"{name}: prediction-lock hash mismatch or missing lock entry")
            reverse = {mapping.get(k, k): k for k in wanted}
            frame = raw.rename(columns=reverse).copy()
            if name == "risk" and not set(frame).intersection({"hist_consumer_probability_max", "hist_merchant_probability_max",
                    "hist_consumer_signal_coverage", "hist_merchant_signal_calendar_coverage", "review_prompt_50", "review_prompt_80"}):
                raise ContractError("Unsupported Risk evidence schema. Native signal fields are required; proxy model outputs need their own semantic adapter.")
            if frame[BASE].isna().any().any():
                raise ContractError(f"{name}: null merchant/cutoff key")
            frame["merchant_abn"] = frame.merchant_abn.astype(str)
            if frame.merchant_abn.str.strip().eq("").any():
                raise ContractError(f"{name}: empty merchant identifier")
            frame["cutoff"] = pd.to_datetime(frame.cutoff, errors="raise").dt.strftime("%Y-%m-%d")
            keys = BASE + (["scenario"] if name == "portfolios" else [])
            if frame.duplicated(keys).any():
                raise ContractError(f"{name}: duplicate merchant/cutoff keys")
            for col in ("prediction", "global_rank", "group_rank"):
                if col in frame:
                    values = pd.to_numeric(frame[col], errors="coerce")
                    if values.isna().any() or not values.map(math.isfinite).all() or values.lt(0).any():
                        raise ContractError(f"{name}: invalid {col}")
            if "eligible" in frame and (frame.eligible.isna().any() or not frame.eligible.map(lambda x: isinstance(x, (bool, np.bool_))).all()):
                raise ContractError(f"{name}: eligible must be a boolean")
            fractions = [k for k in frame if k in ("revenue_reliability", "hist_consumer_probability_max", "hist_merchant_probability_max", "hist_consumer_signal_coverage", "hist_merchant_signal_calendar_coverage")]
            for column in fractions:
                values = pd.to_numeric(frame[column].dropna(), errors="coerce")
                if not values.between(0, 1).all():
                    raise ContractError(f"{name}: {column} must be a fraction between 0 and 1")
            if name == "confidence":
                for column in ("lower", "upper"):
                    values = pd.to_numeric(frame[column].dropna(), errors="coerce")
                    if values.isna().any() or not values.map(math.isfinite).all() or values.lt(0).any():
                        raise ContractError("confidence: invalid interval bounds")
                if (frame.lower > frame.upper).any():
                    raise ContractError("confidence: lower bound exceeds upper bound")
            for column in ("review_prompt_50", "review_prompt_80"):
                if column in frame and not frame[column].dropna().map(lambda x: isinstance(x, (bool, np.bool_))).all():
                    raise ContractError(f"risk: {column} must be a nullable boolean")
            for column in ("hist_consumer_signal_recency_days", "hist_merchant_signal_recency_days"):
                if column in frame:
                    values = pd.to_numeric(frame[column].dropna(), errors="coerce")
                    if values.isna().any() or not values.map(math.isfinite).all() or values.lt(0).any():
                        raise ContractError(f"risk: invalid {column}")
            return frame, digest
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(f"Cannot read {name}.parquet; check the source schema and adapter") from exc

    def has_table(self, folder, name):
        return self.table_path(folder, name).is_file()

    def execution_provenance(self, run_path):
        freeze = self.json_file(run_path / "freeze.json", {})
        changed, missing = [], []
        for relative, expected in freeze.get("code", {}).items():
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root):
                raise ContractError("Frozen code path escapes the engine root")
            if not path.is_file():
                missing.append(relative)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                changed.append(relative)
        return {"mode": "SAVED_OUTPUT_REPLAY", "frozen_at": freeze.get("frozen_utc"),
            "code_status": "CURRENT_CODE_DIFFERS_FROM_FROZEN_RUN" if changed or missing else
                           "CURRENT_CODE_MATCHES_FROZEN_RECORD" if freeze.get("code") else "FROZEN_CODE_RECORD_UNAVAILABLE",
            "changed_files": changed, "missing_files": missing,
            "runtime_dependencies": "NOT_EXECUTED_BY_DASHBOARD"}

    def catalog(self):
        runs = []
        if self.artifacts.is_dir():
            for path in sorted(self.artifacts.iterdir(), reverse=True):
                if not path.is_dir() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", path.name):
                    continue
                splits = []
                for split in SPLITS:
                    folder = path / f"{split}_system"
                    if not (folder / "predictions.parquet").exists():
                        continue
                    try:
                        predictions, _ = self.table(folder, "predictions")
                        portfolios, _ = self.table(folder, "portfolios")
                        splits.append({"id": split, "cutoffs": sorted(predictions.cutoff.unique()),
                                       "scenarios": sorted(portfolios.scenario.unique())})
                    except ContractError as exc:
                        splits.append({"id": split, "error": str(exc), "cutoffs": [], "scenarios": []})
                if splits:
                    state = self.json_file(path / "state.json", {})
                    runs.append({"id": path.name, "status": state.get("status", "UNKNOWN"), "splits": splits})
        return {"api_version": API_VERSION, "adapter": "seven-engine-files-v1", "source": "local_engine_outputs",
                "source_label": self.root.name, "runs": runs}

    def snapshot(self, run: str, split: str, cutoff: str, scenario: str):
        if split not in SPLITS or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff):
            raise ContractError("Invalid split or cutoff")
        safe_token(scenario)
        run_path = self.run_path(run)
        folder = run_path / f"{split}_system"
        lock = self.json_file(folder / "prediction_lock.json", {})
        hashes = lock.get("files")
        warnings = [] if hashes else ["No prediction lock available; source integrity is unverified."]
        tables, digests, states = {}, {}, []
        for name in FIELDS:
            try:
                frame, digest = self.table(folder, name, hashes)
                tables[name] = frame.loc[frame.cutoff.eq(cutoff)].copy()
                digests[name] = digest
            except ContractError as exc:
                if name in REQUIRED or self.has_table(folder, name):
                    raise
                warnings.append(str(exc))
        predictions = tables["predictions"]
        if predictions.empty:
            raise ContractError("No engine results for this cutoff")
        chosen = tables["portfolios"].loc[tables["portfolios"].scenario.eq(scenario)]
        solver_records = self.json_file(folder / "solver_audit.json", [])
        solver = next((x for x in solver_records if x.get("cutoff") == cutoff and x.get("scenario") == scenario), None)
        if chosen.empty and solver is None:
            raise ContractError("Scenario unavailable for this cutoff")
        if sorted(chosen.global_rank.tolist()) != list(range(1, len(chosen) + 1)):
            raise ContractError("Portfolio ranks must be unique and contiguous from 1")
        ids = set(predictions.merchant_abn)
        if not set(chosen.merchant_abn).issubset(ids):
            raise ContractError("Portfolio contains a merchant absent from predictions")
        groups = tables.get("group_top10")
        if groups is not None:
            if not set(groups.merchant_abn).issubset(ids):
                raise ContractError("Group Top-10 contains a merchant absent from predictions")
            expected = predictions.set_index("merchant_abn").course_group
            if not groups.course_group.eq(groups.merchant_abn.map(expected)).all():
                raise ContractError("Group Top-10 membership disagrees with prediction groups")
            for _, group in groups.groupby("course_group"):
                if len(group) > 10 or sorted(group.group_rank.tolist()) != list(range(1, len(group) + 1)):
                    raise ContractError("Group Top-10 ranks must be contiguous and contain at most ten merchants")
        revenue = tables["revenue"].set_index("merchant_abn")
        if set(revenue.index) != ids:
            raise ContractError("Revenue and prediction universes differ")
        joined = predictions.set_index("merchant_abn").prediction
        if not np.allclose(joined, revenue.loc[joined.index, "prediction"], atol=1e-6, rtol=1e-9):
            raise ContractError("Revenue and prediction amounts disagree")
        eligibility = tables["eligibility"].set_index("merchant_abn")
        if not ids.issubset(eligibility.index) or not eligibility.loc[list(ids), "eligible"].eq(True).all():
            raise ContractError("Predictions contain an ineligible or unresolved merchant")
        dispositions = tables["candidate_dispositions"].set_index("merchant_abn")
        if "risk" in tables and not set(tables["risk"].merchant_abn).issubset(dispositions.index):
            raise ContractError("Risk evidence includes merchants outside the candidate universe")
        if not ids.issubset(dispositions.index):
            raise ContractError("Candidate dispositions omit predicted merchants")
        disposition_eligible = set(dispositions.index[dispositions.eligible.eq(True)])
        if disposition_eligible != ids:
            raise ContractError("Eligible disposition and prediction universes differ")
        selected_ranks = dict(zip(chosen.merchant_abn, chosen.global_rank))
        predicted_total = float(joined.loc[list(selected_ranks)].sum())
        solver_status = (solver or {}).get("status", "UNVERIFIED")
        if solver:
            objective = predicted_total
            if scenario == "conservative":
                if "confidence" not in tables:
                    raise ContractError("Conservative scenario requires confidence lower-bound evidence")
                bounds = tables["confidence"].set_index("merchant_abn").reindex(list(selected_ranks)).lower
                if bounds.isna().any():
                    raise ContractError("Conservative scenario has unresolved lower bounds")
                objective = float(bounds.sum())
            if solver.get("count") != len(chosen) or solver.get("revenue") is None or abs(solver["revenue"] - objective) > 1e-5 + 1e-8 * max(objective, 1):
                raise ContractError("Solver audit does not reconcile with the selected portfolio")
        if solver_status != "OPTIMAL":
            warnings.append("Portfolio optimality is unverified; export is disabled.")
        training = self.json_file(run_path / "training.json", {})
        execution = self.execution_provenance(run_path)
        if execution["code_status"] == "CURRENT_CODE_DIFFERS_FROM_FROZEN_RUN":
            warnings.append("Saved outputs belong to frozen historical code; the current engine checkout differs. This is replay, not a rerun of current engines.")
        champion = training.get("champion", "Unknown")
        calibration = self.json_file(run_path / "calibration.json", {}).get(champion, {})
        calibration_status = calibration.get("calibration_status", "UNKNOWN")
        if calibration_status != "CALIBRATED":
            warnings.append(f"Intervals: {calibration_status}. Individual intervals are not a joint portfolio guarantee.")
        maps = {name: frame.set_index("merchant_abn").to_dict("index") for name, frame in tables.items() if name not in ("portfolios",)}
        for name in ENGINES:
            frame = tables.get(name)
            versions = sorted(frame.engine_version.dropna().astype(str).unique()) if frame is not None and "engine_version" in frame else []
            status = "CONNECTED" if frame is not None and not frame.empty else "MISSING"
            if name == "confidence" and status == "CONNECTED":
                status = calibration_status
            if name == "risk" and frame is not None and "risk_status" in frame and not frame.empty:
                status = ", ".join(sorted(frame.risk_status.dropna().unique()))
            if name == "strategic_fit" and frame is not None and "strategic_status" in frame and not frame.empty:
                status = ", ".join(sorted(frame.strategic_status.dropna().unique()))
            if frame is not None and name not in ("eligibility",) and set(frame.merchant_abn) != ids:
                warnings.append(f"{name}: incomplete evidence coverage; absent rows remain unknown.")
            states.append({"id": name, "status": status, "rows": len(frame) if frame is not None else 0, "versions": versions,
                           "source_sha256": digests.get(name), "cutoff": cutoff})
        merchants = []
        for identifier, disposition in maps["candidate_dispositions"].items():
            p = maps["predictions"].get(identifier, {})
            e = maps["eligibility"].get(identifier, {})
            c = maps.get("confidence", {}).get(identifier, {})
            r = maps.get("risk", {}).get(identifier, {})
            g = maps.get("group_top10", {}).get(identifier, {})
            d = maps.get("diversification", {}).get(identifier, {})
            s = maps.get("strategic_fit", {}).get(identifier, {})
            eligible = e.get("eligible", False) is True
            rank = selected_ranks.get(identifier)
            merchants.append({"id": identifier, "name": p.get("merchant_name", disposition.get("merchant_name")),
                "category": p.get("merchant_category", disposition.get("merchant_category")), "group": p.get("course_group"),
                "eligible": eligible, "disposition": disposition.get("candidate_disposition"),
                "reason_codes": e.get("reason_codes", disposition.get("reason_codes")),
                "decision": "selected" if rank else "not_selected" if eligible else "ineligible", "rank": rank,
                "group_rank": g.get("group_rank"), "prediction": p.get("prediction"),
                "confidence": {"lower": c.get("lower"), "upper": c.get("upper"), "reliability": c.get("revenue_reliability"), "band": c.get("confidence_band"),
                    **{k: c.get(k) for k in ("recommended_action", "decision_reason_codes", "interval_status", "rank_boundary_status", "supporting_history_status", "representativeness_status", "environment_status")}},
                "risk": {"status": r.get("risk_status"), "consumer_probability_max": r.get("hist_consumer_probability_max"),
                    "merchant_probability_max": r.get("hist_merchant_probability_max"), "consumer_coverage": r.get("hist_consumer_signal_coverage"),
                    "merchant_coverage": r.get("hist_merchant_signal_calendar_coverage"), "review_50": r.get("review_prompt_50"), "review_80": r.get("review_prompt_80"),
                    "consumer_recency_days": r.get("hist_consumer_signal_recency_days"), "merchant_recency_days": r.get("hist_merchant_signal_recency_days")},
                "history": {"start": p.get("history_start"), "end": p.get("history_end"), "orders": p.get("hist_orders"),
                    "customers": p.get("hist_unique_customers"), "active_days": p.get("hist_active_days"), "revenue": p.get("hist_revenue_proxy"),
                    "repeat_rate": p.get("hist_repeat_customer_rate"), "growth": p.get("hist_growth_28d")},
                "diversification": {"marginal_category_hhi": d.get("marginal_category_hhi")},
                "strategy": {"status": s.get("strategic_status"), "score": s.get("strategic_score")}})
        metrics = None
        if split != "latest":
            evaluation = self.json_file(folder / "evaluation.json", {})
            raw_metric = next((m for m in evaluation.get("portfolio_metrics", []) if m.get("cutoff") == cutoff and m.get("scenario") == scenario), None)
            if raw_metric:
                if evaluation.get("prediction_lock_sha256") and evaluation["prediction_lock_sha256"] != hashlib.sha256((folder / "prediction_lock.json").read_bytes()).hexdigest():
                    raise ContractError("Evaluation refers to a different prediction lock")
                if "selected" in raw_metric and raw_metric["selected"] != len(chosen):
                    raise ContractError("Evaluation count disagrees with the saved shortlist")
                metrics = {k: raw_metric.get(k) for k in ("realised_revenue_aud", "baseline_realised_same_constraints_aud", "delta_vs_baseline_aud", "oracle_capture_same_constraints", "ranking_ndcg_at100_full_universe")}
        groups = sorted(predictions.course_group.dropna().unique())
        from .risk_interface import attach_risk
        return attach_risk(clean({"api_version": API_VERSION, "adapter": "seven-engine-files-v1", "source": "local_engine_outputs", "source_label": self.root.name,
            "run": run, "split": split, "cutoff": cutoff, "scenario": scenario, "champion": champion,
            "loaded_at": datetime.now(timezone.utc).isoformat(), "integrity": "VERIFIED_PARQUET_HASHES" if hashes else "UNVERIFIED",
            "source_fingerprint": hashlib.sha256(json.dumps({"tables": digests, "lock": lock, "solver": solver_records,
                "training": training, "calibration": calibration}, sort_keys=True).encode()).hexdigest()[:16],
            "solver": {k: (solver or {}).get(k) for k in ("status", "gap", "count", "revenue")},
            "summary": {"candidates": len(merchants), "eligible": len(predictions), "selected": len(chosen), "predicted_revenue": predicted_total},
            "metrics": metrics, "warnings": warnings, "engines": states, "groups": groups, "merchants": merchants,
            "execution": execution, "export_allowed": solver_status == "OPTIMAL"}), digests.get("risk"))
