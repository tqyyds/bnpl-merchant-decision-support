from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import clean_paths, load_config, markdown_table, partition_date, read_partition, save_json
from src.run_artifacts import claim_run, finish_run, inventory, provenance, etl_manifest_path


SPLITS = ("train", "validation", "test")
METADATA = ["merchant_abn", "cutoff", "history_start", "history_end", "eligible_history"]
CATEGORICAL = ["merchant_category", "revenue_level"]
READ_COLUMNS = [
    "merchant_abn",
    "user_id",
    "order_datetime",
    "dollar_value",
    "consumer_fraud_probability",
    "merchant_fraud_probability",
]


def snapshot_schedule(first_date: str, last_date: str, config: dict) -> pd.DataFrame:
    """Build rolling labels while keeping every post-boundary outcome protected."""
    first, last = pd.Timestamp(first_date), pd.Timestamp(last_date)
    history, horizon, stride = (
        int(config[key]) for key in ("history_days", "target_days", "stride_days")
    )
    if min(history, horizon, stride) <= 0 or history < 56:
        raise ValueError("Positive horizons/stride and at least 56 historical days are required")
    if stride < horizon:
        raise ValueError("Target windows must not overlap in the primary supervised protocol")

    reference = pd.Timestamp(config["anchor_reference"])
    protected_start = pd.Timestamp(config["protected_outcome_start"])
    if reference + pd.Timedelta(days=1) != protected_start:
        raise ValueError("Anchor reference must immediately precede protected outcomes")

    anchor = reference
    while anchor - pd.Timedelta(days=stride) >= first + pd.Timedelta(days=history - 1):
        anchor -= pd.Timedelta(days=stride)

    rows: list[dict] = []
    while anchor + pd.Timedelta(days=horizon) <= last:
        rows.append(
            {
                "cutoff": anchor,
                "history_start": anchor - pd.Timedelta(days=history - 1),
                "history_end": anchor,
                "label_start": anchor + pd.Timedelta(days=1),
                "label_end": anchor + pd.Timedelta(days=horizon),
            }
        )
        anchor += pd.Timedelta(days=stride)

    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("No complete temporal snapshots")

    development = result["label_end"].lt(protected_start)
    development_indices = result.index[development].tolist()
    validation_count = int(config["validation_snapshot_count"])
    if len(development_indices) <= validation_count:
        raise ValueError("Not enough pre-protection snapshots for both training and validation")
    validation_indices = development_indices[-validation_count:]

    result["split"] = "test"
    result.loc[development, "split"] = "train"
    result.loc[validation_indices, "split"] = "validation"
    result["evaluation_role"] = "development"
    test_rows = result["split"].eq("test")
    result.loc[test_rows, "evaluation_role"] = "robustness"
    first_test_index = result.index[test_rows][0]
    result.loc[first_test_index, "evaluation_role"] = "primary_test"

    if result.loc[first_test_index, "cutoff"] != reference:
        raise ValueError("Primary test cutoff is not aligned to the protected-period boundary")
    if result.loc[test_rows, "label_start"].min() != protected_start:
        raise ValueError("Protected evaluation does not start on the configured date")
    if result.loc[development, "label_end"].max() >= protected_start:
        raise ValueError("A development target touches the protected outcome period")
    for split in SPLITS:
        if not result["split"].eq(split).any():
            raise ValueError(f"No {split} snapshots")
    return result


def _normalise_fraud(
    frame: pd.DataFrame | None,
    key: str,
    transaction_frame: pd.DataFrame,
    fallback_column: str,
) -> pd.DataFrame:
    if frame is None:
        if fallback_column not in transaction_frame:
            return pd.DataFrame(columns=[key, "order_datetime", "fraud_probability"])
        frame = transaction_frame[[key, "order_datetime", fallback_column]].dropna().rename(
            columns={fallback_column: "fraud_probability"}
        )
    else:
        frame = frame[[key, "order_datetime", "fraud_probability"]].copy()
    frame["order_datetime"] = pd.to_datetime(frame["order_datetime"])
    if key == "merchant_abn":
        values = frame[key].astype("string").str.replace(r"\.0$", "", regex=True)
        frame[key] = values.mask(values.str.fullmatch(r"\d+"), values.str.zfill(11))
    frame = frame.drop_duplicates()
    if frame.duplicated([key, "order_datetime"]).any():
        raise ValueError(f"Native fraud grain is not unique for {key} x date")
    return frame


def _consumer_fraud_features(
    history: pd.DataFrame,
    consumer_fraud: pd.DataFrame,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    exposures = history[["merchant_abn", "user_id", "order_datetime"]].drop_duplicates()
    if exposures.empty:
        return pd.DataFrame(index=pd.Index([], name="merchant_abn"))
    denominators = exposures.groupby("merchant_abn", observed=True).size().rename(
        "hist_customer_entity_days"
    )
    observed = exposures.merge(
        consumer_fraud,
        on=["user_id", "order_datetime"],
        how="left",
        validate="many_to_one",
    ).dropna(subset=["fraud_probability"])
    output = denominators.to_frame()
    if observed.empty:
        return output
    grouped = observed.groupby("merchant_abn", observed=True)
    aggregates = grouped.agg(
        hist_consumer_signal_entity_days=("fraud_probability", "size"),
        hist_consumer_signal_days=("order_datetime", "nunique"),
        hist_consumer_probability_mean=("fraud_probability", "mean"),
        hist_consumer_probability_max=("fraud_probability", "max"),
        hist_consumer_last_signal_date=("order_datetime", "max"),
    )
    latest = (
        observed.groupby(["merchant_abn", "order_datetime"], observed=True)["fraud_probability"]
        .mean()
        .sort_index()
        .groupby(level="merchant_abn", observed=True)
        .last()
        .rename("hist_consumer_probability_latest_day_mean")
    )
    output = output.join(aggregates, how="left").join(latest, how="left")
    output["hist_consumer_signal_coverage"] = (
        output["hist_consumer_signal_entity_days"] / output["hist_customer_entity_days"]
    )
    output["hist_consumer_signal_recency_days"] = (
        cutoff - output["hist_consumer_last_signal_date"]
    ).dt.days
    return output.drop(columns="hist_consumer_last_signal_date")


def _merchant_fraud_features(
    merchant_fraud: pd.DataFrame,
    cutoff: pd.Timestamp,
    history_days: int,
) -> pd.DataFrame:
    if merchant_fraud.empty:
        return pd.DataFrame(index=pd.Index([], name="merchant_abn"))
    grouped = merchant_fraud.groupby("merchant_abn", observed=True)
    output = grouped.agg(
        hist_merchant_signal_days=("fraud_probability", "size"),
        hist_merchant_probability_mean=("fraud_probability", "mean"),
        hist_merchant_probability_max=("fraud_probability", "max"),
        hist_merchant_last_signal_date=("order_datetime", "max"),
    )
    latest = (
        merchant_fraud.sort_values(["merchant_abn", "order_datetime"])
        .groupby("merchant_abn", observed=True)["fraud_probability"]
        .last()
    )
    output["hist_merchant_probability_latest"] = latest
    output["hist_merchant_signal_calendar_coverage"] = output["hist_merchant_signal_days"] / history_days
    output["hist_merchant_signal_recency_days"] = (
        cutoff - output["hist_merchant_last_signal_date"]
    ).dt.days
    return output.drop(columns="hist_merchant_last_signal_date")


def features_for_window(
    frame: pd.DataFrame,
    masters: pd.DataFrame,
    cutoff: pd.Timestamp,
    history_days: int,
    consumer_fraud: pd.DataFrame | None = None,
    merchant_fraud: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if history_days < 56:
        raise ValueError("At least 56 historical days are required for adjacent 28-day features")
    start = cutoff - pd.Timedelta(days=history_days - 1)
    history = frame.loc[pd.to_datetime(frame["order_datetime"]).between(start, cutoff)].copy()
    history = history.loc[history["merchant_abn"].isin(masters["merchant_abn"])]
    history["order_datetime"] = pd.to_datetime(history["order_datetime"])

    group = history.groupby("merchant_abn", observed=True)
    totals = group.agg(
        hist_gmv=("dollar_value", "sum"),
        hist_orders=("dollar_value", "size"),
        hist_unique_customers=("user_id", "nunique"),
        hist_aov=("dollar_value", "mean"),
        hist_amount_median=("dollar_value", "median"),
        hist_amount_std=("dollar_value", "std"),
        hist_active_days=("order_datetime", "nunique"),
        hist_last_order_date=("order_datetime", "max"),
    )
    pairs = history.groupby(["merchant_abn", "user_id"], observed=True).agg(
        pair_orders=("dollar_value", "size"), pair_gmv=("dollar_value", "sum")
    )
    if not pairs.empty:
        totals["hist_repeat_customer_rate"] = pairs["pair_orders"].gt(1).groupby(
            level="merchant_abn"
        ).mean()
        shares = pairs["pair_gmv"] / pairs.groupby(level="merchant_abn")["pair_gmv"].transform("sum")
        totals["hist_customer_hhi"] = shares.pow(2).groupby(level="merchant_abn").sum()

    daily = history.groupby(["merchant_abn", "order_datetime"], observed=True)["dollar_value"].sum()
    if not daily.empty:
        second_moment = daily.pow(2).groupby(level="merchant_abn").sum() / history_days
        daily_mean = totals["hist_gmv"] / history_days
        totals["hist_daily_gmv_cv"] = (
            np.sqrt((second_moment - daily_mean.pow(2)).clip(lower=0))
            / daily_mean.replace(0, np.nan)
        )

    def window_sum(days_back_start: int, days_back_end: int) -> pd.Series:
        mask = history["order_datetime"].between(
            cutoff - pd.Timedelta(days=days_back_start),
            cutoff - pd.Timedelta(days=days_back_end),
        )
        return history.loc[mask].groupby("merchant_abn", observed=True)["dollar_value"].sum()

    totals["hist_gmv_last28"] = window_sum(27, 0).reindex(totals.index, fill_value=0)
    totals["hist_gmv_previous28"] = window_sum(55, 28).reindex(totals.index, fill_value=0)
    totals["hist_gmv_last7"] = window_sum(6, 0).reindex(totals.index, fill_value=0)

    if not history.empty:
        high_value_threshold = float(history["dollar_value"].quantile(0.99))
        high_value = history.assign(is_high_value=history["dollar_value"].ge(high_value_threshold))
        high_group = high_value.groupby("merchant_abn", observed=True)
        totals["hist_high_value_order_share"] = high_group["is_high_value"].mean()
        totals["hist_high_value_gmv_share"] = (
            high_value.loc[high_value["is_high_value"]]
            .groupby("merchant_abn", observed=True)["dollar_value"]
            .sum()
            .reindex(totals.index, fill_value=0)
            / totals["hist_gmv"].replace(0, np.nan)
        )

    consumer_native = _normalise_fraud(
        consumer_fraud, "user_id", frame, "consumer_fraud_probability"
    )
    merchant_native = _normalise_fraud(
        merchant_fraud, "merchant_abn", frame, "merchant_fraud_probability"
    )
    consumer_native = consumer_native.loc[consumer_native["order_datetime"].between(start, cutoff)]
    merchant_native = merchant_native.loc[
        merchant_native["order_datetime"].between(start, cutoff)
        & merchant_native["merchant_abn"].isin(masters["merchant_abn"])
    ]
    fraud_features = _consumer_fraud_features(history, consumer_native, cutoff).join(
        _merchant_fraud_features(merchant_native, cutoff, history_days), how="outer"
    )
    totals = totals.join(fraud_features, how="outer")

    selected_master_columns = ["merchant_abn", "merchant_category", "revenue_level", "take_rate_pct"]
    result = masters[selected_master_columns].merge(
        totals.reset_index(), on="merchant_abn", how="left", validate="one_to_one"
    )
    # Preserve the predictor schema even when an entire window has no orders.
    for column in ("hist_repeat_customer_rate", "hist_customer_hhi", "hist_daily_gmv_cv"):
        if column not in result:
            result[column] = np.nan
    zero_columns = [
        "hist_gmv", "hist_orders", "hist_unique_customers", "hist_active_days",
        "hist_gmv_last28", "hist_gmv_previous28", "hist_gmv_last7",
        "hist_high_value_order_share", "hist_high_value_gmv_share",
        "hist_customer_entity_days", "hist_consumer_signal_entity_days",
        "hist_consumer_signal_days", "hist_merchant_signal_days",
    ]
    for column in zero_columns:
        if column not in result:
            result[column] = 0
    result[zero_columns] = result[zero_columns].fillna(0)
    optional_fraud_columns = [
        "hist_consumer_signal_coverage",
        "hist_consumer_probability_mean",
        "hist_consumer_probability_max",
        "hist_consumer_probability_latest_day_mean",
        "hist_consumer_signal_recency_days",
        "hist_merchant_signal_calendar_coverage",
        "hist_merchant_probability_mean",
        "hist_merchant_probability_max",
        "hist_merchant_probability_latest",
        "hist_merchant_signal_recency_days",
    ]
    for column in optional_fraud_columns:
        if column not in result:
            result[column] = np.nan
    result[["hist_consumer_signal_coverage", "hist_merchant_signal_calendar_coverage"]] = result[
        ["hist_consumer_signal_coverage", "hist_merchant_signal_calendar_coverage"]
    ].fillna(0)
    result["eligible_history"] = result["hist_orders"].gt(0)
    result["hist_revenue_proxy"] = result["hist_gmv"] * result["take_rate_pct"] / 100
    result["hist_orders_per_customer"] = (
        result["hist_orders"] / result["hist_unique_customers"].replace(0, np.nan)
    )
    result["hist_gmv_per_active_day"] = result["hist_gmv"] / result["hist_active_days"].replace(0, np.nan)
    result["hist_active_day_rate"] = result["hist_active_days"] / history_days
    result["hist_days_since_last_order"] = (cutoff - result["hist_last_order_date"]).dt.days
    result["hist_amount_cv"] = result["hist_amount_std"] / result["hist_aov"].replace(0, np.nan)
    result["hist_growth_28d"] = (
        result["hist_gmv_last28"] / result["hist_gmv_previous28"].replace(0, np.nan) - 1
    )
    result["hist_no_previous28_activity"] = result["hist_gmv_previous28"].eq(0).astype(int)
    for kind in ("consumer", "merchant"):
        for column in (
            f"hist_{kind}_probability_mean",
            f"hist_{kind}_probability_max",
            ("hist_consumer_probability_latest_day_mean" if kind == "consumer"
             else "hist_merchant_probability_latest"),
        ):
            if column in result:
                result[column] = result[column] / 100
        count_column = "hist_consumer_signal_entity_days" if kind == "consumer" else "hist_merchant_signal_days"
        result[f"hist_{kind}_signal_missing"] = result[count_column].eq(0).astype(int)
    for field in ("hist_gmv", "hist_orders", "hist_unique_customers", "hist_revenue_proxy"):
        result[f"{field}_log1p"] = np.log1p(result[field])
    result = result.drop(columns="hist_last_order_date")
    result["cutoff"], result["history_start"], result["history_end"] = cutoff, start, cutoff
    return result.sort_values("merchant_abn").reset_index(drop=True)


def targets_for_window(
    daily: pd.DataFrame,
    masters: pd.DataFrame,
    cutoff: pd.Timestamp,
    horizon: int,
) -> pd.DataFrame:
    start, end = cutoff + pd.Timedelta(days=1), cutoff + pd.Timedelta(days=horizon)
    later = daily.loc[daily["date"].between(start, end)].groupby(
        "merchant_abn", observed=True
    )["gmv"].sum()
    result = masters[["merchant_abn", "take_rate_pct"]].copy()
    result["future_gmv"] = result["merchant_abn"].map(later).fillna(0)
    result["target_revenue"] = result["future_gmv"] * result["take_rate_pct"] / 100
    result["cutoff"], result["label_start"], result["label_end"] = cutoff, start, end
    return result.drop(columns="take_rate_pct").sort_values("merchant_abn").reset_index(drop=True)


def build_time_splits(root: Path, config: dict | None = None) -> dict:
    config = config or load_config(root)
    staging, _, files = clean_paths(root, config["cleaning_run_id"])
    schedule = snapshot_schedule(
        str(partition_date(files[0]).date()), str(partition_date(files[-1]).date()), config
    )
    masters = pd.read_parquet(staging / "merchant_master.parquet")
    consumer_fraud = pd.read_parquet(staging / "fraud" / "consumer_daily.parquet")
    merchant_fraud = pd.read_parquet(staging / "fraud" / "merchant_daily.parquet")
    local = root / "tables/modeling" / config["snapshot_run_id"]
    audit_dir = local / "all_candidates"
    claim_run(local)
    audit_dir.mkdir(parents=True, exist_ok=True)

    daily_parts = []
    for path in files:
        frame = read_partition(path, ["merchant_abn", "dollar_value"])
        day = frame.groupby("merchant_abn", observed=True)["dollar_value"].sum().rename("gmv").reset_index()
        day["date"] = partition_date(path)
        daily_parts.append(day)
    daily = pd.concat(daily_parts, ignore_index=True)
    partitions = {partition_date(path): path for path in files}
    features = {split: [] for split in SPLITS}
    targets = {split: [] for split in SPLITS}
    for row in schedule.itertuples(index=False):
        window = pd.concat(
            [read_partition(partitions[date], READ_COLUMNS) for date in pd.date_range(row.history_start, row.history_end)],
            ignore_index=True,
        )
        all_x = features_for_window(
            window, masters, row.cutoff, config["history_days"], consumer_fraud, merchant_fraud
        )
        all_y = targets_for_window(daily, masters, row.cutoff, config["target_days"])
        eligible_keys = all_x.loc[all_x["eligible_history"], ["merchant_abn", "cutoff"]]
        x = all_x.loc[all_x["eligible_history"]].reset_index(drop=True)
        y = eligible_keys.merge(all_y, on=["merchant_abn", "cutoff"], how="left", validate="one_to_one")
        pd.testing.assert_frame_equal(x[["merchant_abn", "cutoff"]], y[["merchant_abn", "cutoff"]])
        assert (x["history_end"] < y["label_start"]).all()
        features[row.split].append((all_x, x))
        targets[row.split].append(y)
        print(
            f"Snapshot {row.cutoff.date()}: {row.split}/{row.evaluation_role}, "
            f"{len(x):,} eligible of {len(all_x):,} candidates (targets not printed)",
            flush=True,
        )

    summary_rows = []
    predictor_columns: list[str] = []
    for split in SPLITS:
        all_x = pd.concat([item[0] for item in features[split]], ignore_index=True)
        x = pd.concat([item[1] for item in features[split]], ignore_index=True)
        y = pd.concat(targets[split], ignore_index=True)
        assert not all_x.duplicated(["merchant_abn", "cutoff"]).any()
        assert not x.duplicated(["merchant_abn", "cutoff"]).any()
        assert x["eligible_history"].all()
        predictor_columns = [column for column in x.columns if column not in METADATA]
        assert not any("future" in column or "target" in column for column in predictor_columns)
        assert not any("tail_p" in column for column in predictor_columns)
        numeric = x[predictor_columns].select_dtypes(include="number")
        assert not np.isinf(numeric.to_numpy(dtype=float)).any()
        all_x.to_parquet(audit_dir / f"{split}_all_candidates.parquet", index=False)
        x.to_parquet(local / f"{split}_features.parquet", index=False)
        y.to_parquet(local / f"{split}_labels.parquet", index=False)
        expected = schedule.loc[schedule["split"].eq(split)]
        summary_rows.append(
            {
                "split": split,
                "snapshots": int(x["cutoff"].nunique()),
                "candidate_rows": len(all_x),
                "eligible_rows": len(x),
                "excluded_no_history_rows": int((~all_x["eligible_history"]).sum()),
                "first_cutoff": str(x["cutoff"].min().date()),
                "last_cutoff": str(x["cutoff"].max().date()),
                "first_label_date": str(y["label_start"].min().date()),
                "last_label_date": str(y["label_end"].max().date()),
                "primary_test_snapshots": int(expected["evaluation_role"].eq("primary_test").sum()),
                "robustness_snapshots": int(expected["evaluation_role"].eq("robustness").sum()),
            }
        )

    train, validation, test = summary_rows
    assert train["last_label_date"] < validation["first_label_date"]
    assert validation["last_label_date"] < test["first_label_date"]
    summary = {
        "protocol_version": "rolling_snapshot_v3",
        "provenance": provenance(root, config),
        "input_files": inventory(root, [etl_manifest_path(root, config['cleaning_run_id'])]),
        "config": config,
        "splits": summary_rows,
        "predictor_columns": predictor_columns,
        "categorical_predictors": CATEGORICAL,
        "metadata_not_predictors": METADATA,
        "source_end": str(partition_date(files[-1]).date()),
        "protected_outcome_start": config["protected_outcome_start"],
        "last_complete_label_date": str(schedule["label_end"].max().date()),
        "unused_trailing_source_days": int(
            (partition_date(files[-1]) - schedule["label_end"].max()).days
        ),
        "overlapping_target_windows": False,
        "eligible_history_enforced_in_model_files": True,
        "native_fraud_grain_features": True,
        "long_horizon_sensitivity_built": False,
        "preprocessing_fitted": False,
        "model_trained": False,
        "holdout_outcomes_reported": False,
        "full_dataset_tail_flags_excluded": True,
        "external_context_excluded": True,
    }
    summary['output_files'] = inventory(root, local.rglob('*.parquet'))
    save_json(summary, local / "manifest.json")
    output = root / "reports/time_split" / config["snapshot_run_id"]
    save_json(summary, output / "manifest.json")
    printable = schedule.copy()
    for column in ["cutoff", "history_start", "history_end", "label_start", "label_end"]:
        printable[column] = printable[column].dt.strftime("%Y-%m-%d")
    _write_split_report(summary, printable, output)
    finish_run(local)
    print("PASS: rolling snapshots built; post-2022-02-27 outcomes remain evaluation-only", flush=True)
    return summary


def _write_split_report(summary: dict, schedule: pd.DataFrame, output: Path) -> None:
    config = summary["config"]
    text = f"""# Temporal split v3 — rolling merchant snapshots

## Protocol

One supervised example is one **eligible merchant at one decision cutoff**. Features use the
{config['history_days']} calendar days ending at the cutoff and the label is next-{config['target_days']}-day
take-rate revenue. Snapshots advance every {config['stride_days']} days, so target windows do not
overlap. The final three pre-protection snapshots are internal validation; every outcome from
{config['protected_outcome_start']} onward is excluded from training, preprocessing, Boruta and tuning.

The first protected snapshot (cutoff {config['anchor_reference']}) is the primary out-of-time test.
Later protected snapshots are frozen-model temporal robustness checks. They are not additional
training data and their outcomes are not published here.

{markdown_table(pd.DataFrame(summary['splits']))}

## Why the primary target is 28 days, not 90 days

A 180-day feature window followed by a 90-day target is useful as a later sensitivity analysis,
but the pre-protection history supplies only about two non-overlapping 90-day outcome windows.
That is insufficient for a clean training/internal-validation split. The 90-day-history/28-day-target
protocol supplies six training and three validation decision dates without target overlap. The
configured {config['long_horizon_sensitivity_days']}-day horizon remains deferred until the primary
model and evaluation policy are frozen.

## Leakage safeguards

- Training and validation labels end before {config['protected_outcome_start']}.
- All predictors end at the cutoff; every label starts the following day.
- The same cutoff is never split randomly across merchants.
- Target windows do not overlap, including across train/validation/test boundaries.
- Only rows with historical activity are written to model feature/label files. All 4,026 master
  candidates remain in separate local coverage files so exclusion is explicit and auditable.
- Consumer fraud is aggregated once per merchant-user-day exposure; merchant fraud remains one
  merchant-day observation. Repeated orders cannot silently order-weight native probabilities.
- Consumer latest means the mean of distinct observed users on the latest signal day, so
  input row order cannot choose an arbitrary customer.
- Merchant identity, future values, all-period tail flags and unverified external context are excluded.
- No scaler, imputer, encoder, Boruta selector or model has been fitted.
- Static merchant attributes/take rates and fraud publication lag remain retrospective assumptions.

## Feature engineering implemented

- Commercial scale: GMV, orders, customers, AOV, median, volatility and revenue proxy.
- Engagement/concentration: repeat-customer rate, orders per customer and customer-GMV HHI.
- Activity/momentum: active-day rate, recency, trailing 7/28-day GMV and prior-28-day growth.
- Stability/tails: daily GMV CV and snapshot-local high-value order/GMV shares.
- Risk evidence: native-grain consumer/merchant fraud count, coverage, mean, max, latest and recency.
- Missingness: fraud absence flags remain distinct from zero probability.

## Local outputs

`tables/modeling/{config['snapshot_run_id']}/` contains eligible feature/label Parquet files.
`all_candidates/` contains local coverage-only snapshots for all master merchants. Everything is
Git-ignored. Test targets are stored separately and must be opened only after the model, preprocessing,
feature selection and thresholds have been frozen. The final {summary['unused_trailing_source_days']}
source days cannot form another complete {config['target_days']}-day label window and remain unused.

## Complete snapshot schedule

{markdown_table(schedule)}

## Next modelling checks

Fit trailing-revenue and simple tabular baselines on training only, choose on validation, then run
the primary test once. Report NDCG@100, top-100 realised revenue versus oracle, rank correlation,
MAE and portfolio stability by cutoff. Treat the eight test dates—not merchant-row count—as the
temporal evidence base, and report robustness dates separately from the primary test.
"""
    (output / "README.md").write_text(text, encoding="utf-8")
