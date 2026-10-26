"""Course-only transaction fraud labels, point-in-time features, and shadow model.

The supplied fraud delta is represented at consumer-day and merchant-day grain.  The
course specification permits matching transactions to be treated as fraud, but this is
not a production final-adjudication label and must never be converted to realised loss.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import MissingIndicator, SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, SplineTransformer, StandardScaler


COURSE_LABEL_VERSION = "course_delta_union_v1"
MODEL_STATUS = "PROXY_SHADOW"
LOSS_MODEL_STATUS = "NOT_AVAILABLE"

SMOOTH_FEATURES = [
    "transaction_amount_log1p",
    "consumer_txn_count_30d_log1p",
    "consumer_active_days_30d",
    "consumer_avg_amount_30d_log1p",
    "consumer_amount_zscore_30d",
    "consumer_proxy_fraud_rate_90d",
    "merchant_txn_count_30d_log1p",
    "merchant_active_days_30d",
    "merchant_avg_amount_30d_log1p",
    "merchant_proxy_fraud_rate_90d",
]
LINEAR_FEATURES = ["consumer_amount_zscore_available"]
HISTORY_PROXY_FEATURES = ["consumer_proxy_fraud_rate_90d", "merchant_proxy_fraud_rate_90d"]
NUMERIC_FEATURES = SMOOTH_FEATURES + LINEAR_FEATURES
CATEGORICAL_FEATURES = ["merchant_category"]
MODEL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _require(frame: pd.DataFrame, fields: set[str]) -> None:
    missing = fields - set(frame)
    if missing:
        raise ValueError(f"Missing fields: {sorted(missing)}")


def label_course_transactions(frame: pd.DataFrame, label_variant: str = "UNION_PROPAGATED") -> pd.DataFrame:
    """Create the course label without claiming final confirmed fraud.

    A positive means the order matches at least one supplied entity-day delta row.  A
    negative means no supplied delta row matched.  Because the raw delta has no order
    identifier, every order sharing a matched entity-day key receives the same source
    signal.  Match multiplicity must be reported by the caller.
    """
    required = {
        "order_id",
        "order_datetime",
        "user_id",
        "merchant_abn",
        "dollar_value",
        "consumer_fraud_signal_present",
        "merchant_fraud_signal_present",
    }
    _require(frame, required)
    if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
        raise ValueError("Course transaction order_id must be non-null and unique within a batch")
    amount = pd.to_numeric(frame["dollar_value"], errors="coerce")
    if not np.isfinite(amount).all() or not amount.gt(0).all():
        raise ValueError("Course transaction amounts must be finite and positive")
    consumer = frame["consumer_fraud_signal_present"]
    merchant = frame["merchant_fraud_signal_present"]
    if consumer.isna().any() or merchant.isna().any():
        raise ValueError("Fraud signal presence flags must be explicit booleans")
    if not consumer.isin([True, False]).all() or not merchant.isin([True, False]).all():
        raise ValueError("Fraud signal presence flags must be booleans")

    out = frame.copy()
    out["order_datetime"] = pd.to_datetime(out["order_datetime"]).dt.normalize()
    out["merchant_abn"] = out["merchant_abn"].astype(str).str.zfill(11)
    consumer = consumer.astype(bool)
    merchant = merchant.astype(bool)
    out["consumer_day_match_multiplicity"] = (
        out.groupby("user_id", observed=True)["order_id"].transform("size").where(consumer, 0).astype(int)
    )
    out["merchant_day_match_multiplicity"] = (
        out.groupby("merchant_abn", observed=True)["order_id"].transform("size").where(merchant, 0).astype(int)
    )
    if label_variant == "UNION_PROPAGATED":
        label = consumer | merchant
    elif label_variant == "CONSUMER_ONLY":
        label = consumer
    elif label_variant == "SINGLE_MATCH_ONLY":
        exact = (consumer & out["consumer_day_match_multiplicity"].eq(1)) | (
            merchant & out["merchant_day_match_multiplicity"].eq(1)
        )
        ambiguous = (consumer | merchant) & ~exact
        label = (consumer | merchant).astype("boolean").mask(ambiguous)
    else:
        raise ValueError(f"Unsupported course label variant: {label_variant}")
    out["is_fraud"] = label
    out["label_eligible"] = out["is_fraud"].notna()
    out["course_label_source"] = np.select(
        [consumer.astype(bool) & merchant.astype(bool), consumer.astype(bool), merchant.astype(bool)],
        ["CONSUMER_AND_MERCHANT_DAY", "CONSUMER_DAY", "MERCHANT_DAY"],
        default="NO_DELTA_MATCH",
    )
    out["fraud_label_version"] = COURSE_LABEL_VERSION
    out["fraud_label_variant"] = label_variant
    out["fraud_label_semantics"] = "OBSERVED_COURSE_DELTA_NOT_FINAL_ADJUDICATION"
    return out


@dataclass
class _DailyRecord:
    day: pd.Timestamp
    transactions: int
    amount: float
    amount_sq: float
    fraud_transactions: int
    fraud_observed_transactions: int


@dataclass
class _EntityState:
    rows_30: deque[_DailyRecord] = field(default_factory=deque)
    rows_90: deque[_DailyRecord] = field(default_factory=deque)
    transactions_30: int = 0
    amount_30: float = 0.0
    amount_sq_30: float = 0.0
    fraud_transactions_90: int = 0
    fraud_observed_transactions_90: int = 0


class _EntityHistory:
    """Small rolling state updated only after every transaction for a day is scored."""

    def __init__(self) -> None:
        self._states: dict[object, _EntityState] = defaultdict(_EntityState)

    def stats(self, entity: object, day: pd.Timestamp) -> dict[str, float]:
        state = self._states[entity]
        oldest_30 = day - timedelta(days=30)
        while state.rows_30 and state.rows_30[0].day < oldest_30:
            expired = state.rows_30.popleft()
            state.transactions_30 -= expired.transactions
            state.amount_30 -= expired.amount
            state.amount_sq_30 -= expired.amount_sq
        oldest_90 = day - timedelta(days=90)
        while state.rows_90 and state.rows_90[0].day < oldest_90:
            expired = state.rows_90.popleft()
            state.fraud_transactions_90 -= expired.fraud_transactions
            state.fraud_observed_transactions_90 -= expired.fraud_observed_transactions
        count_30 = state.transactions_30
        amount_30 = state.amount_30
        amount_sq_30 = state.amount_sq_30
        active_30 = len(state.rows_30)
        count_90 = state.fraud_observed_transactions_90
        fraud_90 = state.fraud_transactions_90
        mean_30 = amount_30 / count_30 if count_30 else np.nan
        variance_30 = max(amount_sq_30 / count_30 - mean_30**2, 0.0) if count_30 else np.nan
        std_30 = np.sqrt(variance_30) if count_30 >= 3 else np.nan
        return {
            "txn_count_30d": float(count_30),
            "active_days_30d": float(active_30),
            "avg_amount_30d": float(mean_30),
            "amount_std_30d": float(std_30),
            "fraud_rate_90d": float(fraud_90 / count_90) if count_90 else np.nan,
        }

    def update(self, daily: pd.DataFrame, entity_field: str, day: pd.Timestamp) -> None:
        augmented = daily.assign(
            _amount_sq=daily["dollar_value"].astype(float).pow(2),
            _fraud_for_history=daily["is_fraud"].fillna(False).astype(int),
        )
        grouped = augmented.groupby(
            entity_field, sort=False, observed=True
        ).agg(
            transactions=("order_id", "size"),
            amount=("dollar_value", "sum"),
            amount_sq=("_amount_sq", "sum"),
            fraud_transactions=("_fraud_for_history", "sum"),
            fraud_observed_transactions=("label_eligible", "sum"),
        )
        for entity, row in grouped.iterrows():
            record = _DailyRecord(
                day=day,
                transactions=int(row.transactions),
                amount=float(row.amount),
                amount_sq=float(row.amount_sq),
                fraud_transactions=int(row.fraud_transactions),
                fraud_observed_transactions=int(row.fraud_observed_transactions),
            )
            state = self._states[entity]
            state.rows_30.append(record)
            state.rows_90.append(record)
            state.transactions_30 += record.transactions
            state.amount_30 += record.amount
            state.amount_sq_30 += record.amount_sq
            state.fraud_transactions_90 += record.fraud_transactions
            state.fraud_observed_transactions_90 += record.fraud_observed_transactions


class PointInTimeFraudFeatures:
    """Build transaction features from completed days strictly before the scored day."""

    def __init__(self) -> None:
        self.consumer = _EntityHistory()
        self.merchant = _EntityHistory()
        self.last_day: pd.Timestamp | None = None

    def transform_then_update(
        self,
        frame: pd.DataFrame,
        merchant_categories: pd.Series,
        label_variant: str = "UNION_PROPAGATED",
    ) -> pd.DataFrame:
        labelled = label_course_transactions(frame, label_variant=label_variant)
        days = labelled["order_datetime"].drop_duplicates()
        if len(days) != 1:
            raise ValueError("Each feature batch must contain one complete calendar day")
        day = pd.Timestamp(days.iloc[0])
        if self.last_day is not None and day <= self.last_day:
            raise ValueError("Transaction days must be complete and strictly chronological")

        consumer_stats = {key: self.consumer.stats(key, day) for key in labelled["user_id"].unique()}
        merchant_stats = {key: self.merchant.stats(key, day) for key in labelled["merchant_abn"].unique()}
        out = labelled[[
            "order_id", "order_datetime", "user_id", "merchant_abn", "dollar_value", "is_fraud",
            "label_eligible", "course_label_source", "consumer_day_match_multiplicity",
            "merchant_day_match_multiplicity", "fraud_label_version", "fraud_label_variant",
            "fraud_label_semantics",
        ]].copy()
        out["transaction_amount"] = out["dollar_value"].astype(float)
        out["transaction_amount_log1p"] = np.log1p(out["transaction_amount"])
        for prefix, key_field, lookup in (
            ("consumer", "user_id", consumer_stats),
            ("merchant", "merchant_abn", merchant_stats),
        ):
            for suffix in ("txn_count_30d", "active_days_30d", "avg_amount_30d"):
                out[f"{prefix}_{suffix}"] = out[key_field].map(lambda key, s=suffix: lookup[key][s])
            out[f"{prefix}_proxy_fraud_rate_90d"] = out[key_field].map(
                lambda key: lookup[key]["fraud_rate_90d"]
            )
        out["consumer_amount_zscore_30d"] = [
            (amount - consumer_stats[key]["avg_amount_30d"]) / consumer_stats[key]["amount_std_30d"]
            if np.isfinite(consumer_stats[key]["amount_std_30d"]) and consumer_stats[key]["amount_std_30d"] > 0
            else np.nan
            for amount, key in zip(out["transaction_amount"], out["user_id"])
        ]
        out["consumer_amount_zscore_available"] = out["consumer_amount_zscore_30d"].notna().astype(int)
        out["consumer_txn_count_30d_log1p"] = np.log1p(out["consumer_txn_count_30d"])
        out["consumer_avg_amount_30d_log1p"] = np.log1p(out["consumer_avg_amount_30d"])
        out["merchant_txn_count_30d_log1p"] = np.log1p(out["merchant_txn_count_30d"])
        out["merchant_avg_amount_30d_log1p"] = np.log1p(out["merchant_avg_amount_30d"])
        out["merchant_category"] = out["merchant_abn"].map(merchant_categories)
        if out["merchant_category"].isna().any():
            out["merchant_category"] = out["merchant_category"].fillna("UNKNOWN_SYNTHETIC_MERCHANT")

        # The update happens last: no current-day label or behaviour can enter its own features.
        self.consumer.update(labelled, "user_id", day)
        self.merchant.update(labelled, "merchant_abn", day)
        self.last_day = day
        return out


def deterministic_negative_sample(frame: pd.DataFrame, rate: float) -> tuple[pd.DataFrame, np.ndarray]:
    if not 0 < rate <= 1:
        raise ValueError("negative sample rate must be in (0, 1]")
    frame = frame.loc[frame["is_fraud"].notna()].copy()
    positives = frame["is_fraud"].astype(bool)
    hashed = pd.util.hash_pandas_object(frame["order_id"].astype(str), index=False).to_numpy(dtype=np.uint64)
    sampled_negative = (hashed % 1_000_000) < int(rate * 1_000_000)
    keep = positives.to_numpy() | sampled_negative
    sampled = frame.loc[keep].reset_index(drop=True)
    weights = np.where(sampled["is_fraud"].to_numpy(dtype=bool), 1.0, 1.0 / rate)
    return sampled, weights


class CourseFraudModel:
    """Linear baseline or penalised spline logistic GAM-style proxy model."""

    def __init__(
        self,
        kind: str = "logistic",
        c: float = 1.0,
        n_knots: int = 6,
        include_history_proxy_rates: bool = True,
        spline_min_unique: int = 8,
        spline_max_zero_share: float = 0.95,
    ) -> None:
        if kind not in {"logistic", "spline_gam"}:
            raise ValueError("kind must be logistic or spline_gam")
        if n_knots < 3 or spline_min_unique < 2 or not 0 <= spline_max_zero_share <= 1:
            raise ValueError("Invalid spline configuration")
        self.kind = kind
        self.c = c
        self.n_knots = n_knots
        self.include_history_proxy_rates = include_history_proxy_rates
        self.spline_min_unique = spline_min_unique
        self.spline_max_zero_share = spline_max_zero_share
        self.numeric_features = [
            field for field in NUMERIC_FEATURES
            if include_history_proxy_rates or field not in HISTORY_PROXY_FEATURES
        ]
        self.model_features = self.numeric_features + CATEGORICAL_FEATURES
        self.pipeline: Pipeline | None = None
        self.spline_qa: dict[str, dict] = {}

    @property
    def model_name(self) -> str:
        suffix = "full" if self.include_history_proxy_rates else "no_history_proxy_rate"
        family = "logistic" if self.kind == "logistic" else "spline_gam"
        return f"course_fraud_proxy_{family}_{suffix}_v1"

    def _prepare(self, frame: pd.DataFrame) -> Pipeline:
        transformers = []
        smooth = [field for field in SMOOTH_FEATURES if field in self.numeric_features]
        for field in smooth:
            values = pd.to_numeric(frame[field], errors="coerce").dropna()
            unique = int(values.nunique())
            zero_share = float(values.eq(0).mean()) if len(values) else 1.0
            eligible = unique >= self.spline_min_unique and zero_share <= self.spline_max_zero_share
            self.spline_qa[field] = {
                "n_unique": unique,
                "zero_share": zero_share,
                "transform": "spline" if eligible else "linear_fallback",
            }
        spline_fields = [field for field in smooth if self.spline_qa[field]["transform"] == "spline"]
        linear_fields = [field for field in self.numeric_features if field not in spline_fields]
        if self.kind == "logistic":
            linear_fields = list(self.numeric_features)
            spline_fields = []
        if spline_fields:
            transformers.append(("numeric_spline", Pipeline([
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("spline", SplineTransformer(
                    n_knots=self.n_knots,
                    degree=3,
                    knots="quantile",
                    extrapolation="linear",
                    include_bias=False,
                )),
            ]), spline_fields))
        if linear_fields:
            transformers.append(("numeric_linear", Pipeline([
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scale", StandardScaler()),
            ]), linear_fields))
        missing_fields = [field for field in self.numeric_features if frame[field].isna().any()]
        if missing_fields:
            # Indicators are a separate linear branch; they are never spline-expanded.
            transformers.append(("numeric_missing", MissingIndicator(
                features="missing-only", error_on_new=False
            ), missing_fields))
        categorical = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ])
        transformers.append(("categorical", categorical, CATEGORICAL_FEATURES))
        return Pipeline([
            ("prepare", ColumnTransformer(transformers)),
            ("model", LogisticRegression(C=self.c, max_iter=1000, solver="lbfgs")),
        ])

    def fit(self, frame: pd.DataFrame, sample_weight: np.ndarray | None = None) -> "CourseFraudModel":
        _require(frame, set(self.model_features) | {"is_fraud"})
        if frame["is_fraud"].isna().any():
            raise ValueError("Remove label-ineligible rows before fitting")
        target = frame["is_fraud"].astype(int)
        if target.nunique() != 2:
            raise ValueError("Training data must contain observed fraud and non-fraud rows")
        self.pipeline = self._prepare(frame)
        self.pipeline.fit(frame[self.model_features], target, model__sample_weight=sample_weight)
        return self

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        if self.pipeline is None:
            raise ValueError("Model has not been fitted")
        _require(frame, set(self.model_features))
        return self.pipeline.predict_proba(frame[self.model_features])[:, 1]


class SigmoidCalibrator:
    """Independent Platt scaling fitted only on an unsampled calibration period."""

    def __init__(self) -> None:
        self.model = LogisticRegression(C=1e6, max_iter=1000, solver="lbfgs")
        self.fitted = False

    @staticmethod
    def _logit(probability: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(probability, dtype=float), 1e-8, 1 - 1e-8)
        return np.log(p / (1 - p)).reshape(-1, 1)

    def fit(self, probability: np.ndarray, target: pd.Series | np.ndarray) -> "SigmoidCalibrator":
        y = np.asarray(target, dtype=int)
        if len(y) != len(probability) or np.unique(y).size != 2:
            raise ValueError("Calibration data must contain both classes")
        self.model.fit(self._logit(probability), y)
        self.fitted = True
        return self

    def predict(self, probability: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise ValueError("Calibrator has not been fitted")
        return self.model.predict_proba(self._logit(probability))[:, 1]


def expected_calibration_error(y_true: pd.Series | np.ndarray, probability: np.ndarray, bins: int = 10) -> float:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probability, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    indices = np.minimum(np.digitize(p, edges[1:-1], right=True), bins - 1)
    error = 0.0
    for index in range(bins):
        mask = indices == index
        if mask.any():
            error += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return float(error)


def classification_metrics(frame: pd.DataFrame, probability: np.ndarray, review_capacities=(0.01, 0.05)) -> dict:
    y = frame["is_fraud"].astype(int).to_numpy()
    p = np.asarray(probability, dtype=float)
    if len(y) != len(p) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Invalid fraud probabilities")
    if np.unique(y).size != 2:
        raise ValueError("Proxy evaluation requires both observed classes")
    result = {
        "rows": int(len(y)),
        "observed_fraud_rows": int(y.sum()),
        "observed_fraud_rate": float(y.mean()),
        "pr_auc": float(average_precision_score(y, p)),
        "brier_score": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "expected_calibration_error_10_bin": expected_calibration_error(y, p),
        "review_capacity": {},
    }
    order_ids = frame["order_id"].astype(str).to_numpy()
    for capacity in review_capacities:
        if not 0 < capacity <= 1:
            raise ValueError("Review capacity must be in (0, 1]")
        count = max(1, int(np.ceil(len(y) * capacity)))
        chosen = np.lexsort((order_ids, -p))[:count]
        predicted = np.zeros(len(y), dtype=int)
        predicted[chosen] = 1
        result["review_capacity"][f"{capacity:.4f}"] = {
            "reviewed_rows": count,
            "probability_threshold": float(p[chosen].min()),
            "precision": float(precision_score(y, predicted, zero_division=0)),
            "recall": float(recall_score(y, predicted, zero_division=0)),
        }
    return result


def label_sensitivity_metrics(
    frame: pd.DataFrame,
    probability: np.ndarray,
    review_capacities=(0.01, 0.05),
) -> dict[str, dict]:
    """Evaluate fixed predictions under the three declared course-label semantics."""
    required = {
        "course_label_source", "consumer_day_match_multiplicity",
        "merchant_day_match_multiplicity", "order_id",
    }
    _require(frame, required)
    consumer = frame["course_label_source"].isin(["CONSUMER_DAY", "CONSUMER_AND_MERCHANT_DAY"])
    merchant = frame["course_label_source"].isin(["MERCHANT_DAY", "CONSUMER_AND_MERCHANT_DAY"])
    union = consumer | merchant
    exact = (consumer & frame["consumer_day_match_multiplicity"].eq(1)) | (
        merchant & frame["merchant_day_match_multiplicity"].eq(1)
    )
    variants = {
        "UNION_PROPAGATED": (pd.Series(True, index=frame.index), union),
        "CONSUMER_ONLY": (pd.Series(True, index=frame.index), consumer),
        "SINGLE_MATCH_ONLY": (~union | exact, exact),
    }
    result = {}
    for name, (eligible, target) in variants.items():
        selected = frame.loc[eligible].copy()
        selected["is_fraud"] = target.loc[eligible].to_numpy()
        result[name] = classification_metrics(
            selected,
            np.asarray(probability)[eligible.to_numpy()],
            review_capacities=review_capacities,
        )
    return result


def select_proxy_champion(logistic_metrics: dict, gam_metrics: dict, brier_tolerance: float = 0.002) -> tuple[str, dict]:
    """Validation-only, predeclared comparison; never inspects locked-test metrics."""
    capacities = sorted(set(logistic_metrics["review_capacity"]) & set(gam_metrics["review_capacity"]))
    recall_improved = any(
        gam_metrics["review_capacity"][key]["recall"] > logistic_metrics["review_capacity"][key]["recall"]
        for key in capacities
    )
    checks = {
        "pr_auc_noninferior": gam_metrics["pr_auc"] >= logistic_metrics["pr_auc"],
        "brier_within_tolerance": gam_metrics["brier_score"] <= logistic_metrics["brier_score"] + brier_tolerance,
        "recall_improved_at_any_capacity": recall_improved,
    }
    champion = "spline_gam" if all(checks.values()) else "logistic"
    return champion, checks


def ranking_sensitivity(
    merchants: pd.DataFrame,
    revenue_field: str,
    risk_field: str = "fraud_risk_evidence_percentile",
    lambdas=(0.0, 0.05, 0.10, 0.20),
    capacity: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Produce non-optimising ranking scenarios; lambda zero remains the formal baseline."""
    _require(merchants, {"merchant_abn", revenue_field, risk_field})
    if merchants["merchant_abn"].duplicated().any():
        raise ValueError("Merchant ranking universe must be unique")
    frame = merchants.copy()
    if frame[[revenue_field, risk_field]].isna().any().any():
        raise ValueError("Ranking sensitivity cannot silently fill missing values")
    frame["revenue_percentile"] = frame[revenue_field].rank(method="average", pct=True)
    selections = []
    summaries = []
    baseline_ids = set(
        frame.sort_values(["revenue_percentile", "merchant_abn"], ascending=[False, True]).head(capacity)["merchant_abn"]
    )
    for value in lambdas:
        if value < 0:
            raise ValueError("Risk-evidence lambda must be non-negative")
        scored = frame.copy()
        scored["risk_evidence_lambda"] = float(value)
        scored["risk_adjusted_sensitivity_score"] = scored["revenue_percentile"] - value * scored[risk_field]
        selected = scored.sort_values(
            ["risk_adjusted_sensitivity_score", "merchant_abn"], ascending=[False, True]
        ).head(capacity).copy()
        selected["sensitivity_rank"] = np.arange(1, len(selected) + 1)
        selections.append(selected)
        ids = set(selected["merchant_abn"])
        summaries.append({
            "risk_evidence_lambda": float(value),
            "selected": int(len(selected)),
            "top_list_changes_vs_lambda_0": int(len(ids.symmetric_difference(baseline_ids)) // 2),
            "selected_predicted_revenue": float(selected[revenue_field].sum()),
            "selected_mean_risk_evidence_percentile": float(selected[risk_field].mean()),
            "claim": "SENSITIVITY_NOT_OPTIMAL_POLICY",
        })
    return pd.concat(selections, ignore_index=True), pd.DataFrame(summaries)


def aggregate_merchant_evidence(
    scored_transactions: pd.DataFrame,
    cutoff: str | pd.Timestamp,
    high_risk_threshold: float,
) -> pd.DataFrame:
    required = {"merchant_abn", "order_datetime", "dollar_value", "is_fraud", "predicted_course_fraud_probability"}
    _require(scored_transactions, required)
    cutoff = pd.Timestamp(cutoff).normalize()
    start = cutoff - pd.Timedelta(days=89)
    frame = scored_transactions.loc[
        pd.to_datetime(scored_transactions["order_datetime"]).between(start, cutoff, inclusive="both")
    ].copy()
    if frame.empty:
        raise ValueError("No transactions in merchant evidence window")
    frame["fraud_amount"] = frame["dollar_value"].where(frame["is_fraud"], 0.0)
    frame["probability_amount"] = frame["dollar_value"] * frame["predicted_course_fraud_probability"]
    frame["high_risk"] = frame["predicted_course_fraud_probability"].ge(high_risk_threshold)
    out = frame.groupby("merchant_abn", observed=True).agg(
        historical_orders=("order_id", "size"),
        historical_gmv_aud=("dollar_value", "sum"),
        observed_course_fraud_orders=("is_fraud", "sum"),
        observed_course_fraud_amount_aud=("fraud_amount", "sum"),
        mean_predicted_course_fraud_probability=("predicted_course_fraud_probability", "mean"),
        probability_weighted_amount_sum=("probability_amount", "sum"),
        high_risk_transaction_share=("high_risk", "mean"),
    ).reset_index()
    out["historical_course_fraud_rate"] = out["observed_course_fraud_orders"] / out["historical_orders"]
    out["historical_course_fraud_amount_share"] = out["observed_course_fraud_amount_aud"] / out["historical_gmv_aud"]
    out["amount_weighted_predicted_course_fraud_probability"] = (
        out.pop("probability_weighted_amount_sum") / out["historical_gmv_aud"]
    )
    out["fraud_risk_evidence_percentile"] = out["mean_predicted_course_fraud_probability"].rank(method="average", pct=True)
    out["cutoff"] = cutoff
    out["fraud_model_status"] = MODEL_STATUS
    out["loss_model_status"] = LOSS_MODEL_STATUS
    out["risk_status"] = "EVIDENCE_ONLY_NO_LOSS_LABELS"
    out["predicted_net_loss_28d_aud"] = np.nan
    out["predicted_loss_rate_28d"] = np.nan
    out["fraud_label_version"] = COURSE_LABEL_VERSION
    return out
