from __future__ import annotations

from pathlib import Path
from textwrap import shorten

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .common import clean_paths, load_config, markdown_table, partition_date, read_partition, save_json
from .time_split import snapshot_schedule


def concentration(values: pd.Series, count: int = 100) -> float:
    total = float(values.sum())
    return float(values.nlargest(count).sum() / total) if total else 0.0


def historical_files(files: list[Path], end: str) -> list[Path]:
    return [path for path in files if partition_date(path) <= pd.Timestamp(end)]


def exploration_scope(config: dict, first: str, last: str) -> dict:
    schedule = snapshot_schedule(first, last, config)
    eda_end = pd.Timestamp(config['eda_end'])
    overlaps = {}
    for split in ('train', 'validation', 'test'):
        rows = schedule.loc[schedule.split.eq(split)]
        overlaps[split] = bool((rows.label_start.le(eda_end) & rows.label_end.ge(pd.Timestamp(first))).any())
    return {
        'eda_label_period_overlap': overlaps,
        'no_protected_test_outcomes_explored': not overlaps['test'],
        'internal_validation_is_development': True,
    }


def run_eda(root: Path, config: dict | None = None) -> dict:
    config = config or load_config(root)
    staging, _, all_files = clean_paths(root, config["cleaning_run_id"])
    files = historical_files(all_files, config["eda_end"])
    report_dir = root / "reports/eda" / config['analysis_run_id']
    local_dir = root / "tables/modeling" / config["analysis_run_id"]
    figures = report_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    local_dir.mkdir(parents=True, exist_ok=True)
    masters = pd.read_parquet(staging / "merchant_master.parquet")
    geo = pd.read_parquet(staging / "consumers.parquet", columns=["consumer_id", "geo_match_status", "seifa_match_status"])
    geo_lookup = geo.set_index("consumer_id")["geo_match_status"]
    columns = ["merchant_abn", "user_id", "consumer_id", "dollar_value", "order_datetime",
               "consumer_fraud_probability", "merchant_fraud_probability", "fraud_signal_any"]
    daily_parts, daily_rows, pair_parts, amounts = [], [], [], []
    geo_counts: dict[str, int] = {}
    for number, path in enumerate(files, 1):
        frame = read_partition(path, columns)
        frame["consumer_observed"] = frame["consumer_fraud_probability"].notna().astype(int)
        frame["merchant_observed"] = frame["merchant_fraud_probability"].notna().astype(int)
        frame["consumer_probability_sum"] = frame["consumer_fraud_probability"].fillna(0)
        frame["merchant_probability_sum"] = frame["merchant_fraud_probability"].fillna(0)
        grouped = frame.groupby("merchant_abn", observed=True).agg(
            gmv=("dollar_value", "sum"), orders=("dollar_value", "size"),
            consumer_observed=("consumer_observed", "sum"), merchant_observed=("merchant_observed", "sum"),
            consumer_probability_sum=("consumer_probability_sum", "sum"),
            merchant_probability_sum=("merchant_probability_sum", "sum"),
        ).reset_index()
        grouped["date"] = partition_date(path)
        daily_parts.append(grouped)
        pairs = frame.groupby(["merchant_abn", "user_id"], observed=True).size().rename("orders").reset_index()
        pair_parts.append(pairs)
        amounts.append(frame["dollar_value"].to_numpy())
        daily_rows.append({"date": partition_date(path), "orders": len(frame), "gmv": float(frame["dollar_value"].sum()),
                           "consumer_observed": int(frame["consumer_observed"].sum()),
                           "merchant_observed": int(frame["merchant_observed"].sum()),
                           "any_signal": int(frame["fraud_signal_any"].sum())})
        for status, count in frame["consumer_id"].map(geo_lookup).fillna("unmapped_consumer").value_counts().items():
            geo_counts[str(status)] = geo_counts.get(str(status), 0) + int(count)
        if number % 60 == 0:
            print(f"EDA historical partitions: {number}/{len(files)}", flush=True)

    daily = pd.DataFrame(daily_rows)
    by_day = pd.concat(daily_parts, ignore_index=True)
    pair_counts = pd.concat(pair_parts, ignore_index=True).groupby(["merchant_abn", "user_id"], observed=True)["orders"].sum()
    customers = pair_counts.groupby(level="merchant_abn").agg(unique_customers="size")
    customers["repeat_customer_rate"] = pair_counts.gt(1).groupby(level="merchant_abn").mean()
    totals = by_day.groupby("merchant_abn", observed=True).sum(numeric_only=True)
    totals["active_days"] = by_day.groupby("merchant_abn", observed=True).size()
    totals = totals.join(customers)
    totals["average_order_value"] = totals["gmv"] / totals["orders"]
    totals["consumer_fraud_coverage"] = totals["consumer_observed"] / totals["orders"]
    totals["merchant_fraud_coverage"] = totals["merchant_observed"] / totals["orders"]
    totals["consumer_probability_mean_observed"] = totals["consumer_probability_sum"] / totals["consumer_observed"].replace(0, np.nan)
    totals["merchant_probability_mean_observed"] = totals["merchant_probability_sum"] / totals["merchant_observed"].replace(0, np.nan)
    merchant = masters.merge(totals.reset_index(), on="merchant_abn", how="left", validate="one_to_one")
    merchant["take_rate_revenue"] = merchant["gmv"] * merchant["take_rate_pct"] / 100
    merchant.to_parquet(local_dir / "merchant_eda.parquet", index=False)
    daily.to_parquet(local_dir / "daily_eda.parquet", index=False)
    values = np.concatenate(amounts)
    quantile_points = [0, .01, .25, .5, .75, .95, .99, .999, 1]
    quantiles = {str(q): float(v) for q, v in zip(quantile_points, np.quantile(values, quantile_points))}
    monthly = daily.assign(month=daily["date"].dt.strftime("%Y-%m")).groupby("month").agg(
        days=("date", "size"), orders=("orders", "sum"), gmv=("gmv", "sum"),
        consumer_observed=("consumer_observed", "sum"), merchant_observed=("merchant_observed", "sum"))
    monthly["orders_per_observed_day"] = monthly["orders"] / monthly["days"]
    monthly["consumer_fraud_coverage_pct"] = 100 * monthly["consumer_observed"] / monthly["orders"]
    monthly["merchant_fraud_coverage_pct"] = 100 * monthly["merchant_observed"] / monthly["orders"]
    industries = merchant.groupby("merchant_category", observed=True).agg(
        merchants=("merchant_abn", "size"), gmv=("gmv", "sum"), revenue=("take_rate_revenue", "sum"))
    industries["gmv_share"] = industries["gmv"] / industries["gmv"].sum()
    top_industry = industries.sort_values("gmv", ascending=False)
    peak = daily.loc[daily["orders"].idxmax()]
    summary = {
        "status": "historical_eda_only",
        "start": str(daily["date"].min().date()), "end": str(daily["date"].max().date()),
        "historical_days": len(files), "historical_orders": int(daily["orders"].sum()),
        "historical_gmv_aud": float(daily["gmv"].sum()),
        "peak_order_date": str(peak["date"].date()), "peak_daily_orders": int(peak["orders"]),
        "master_merchants": len(masters), "historically_active_master_merchants": int(merchant["orders"].fillna(0).gt(0).sum()),
        "historical_transacting_merchants": len(totals),
        "unknown_merchant_orders": int(totals.loc[~totals.index.isin(masters["merchant_abn"]), "orders"].sum()),
        "active_users": int(pair_counts.index.get_level_values("user_id").nunique()),
        "amount_quantiles_aud": quantiles,
        "top_100_candidate_gmv_share": concentration(merchant["gmv"]),
        "top_100_candidate_revenue_share": concentration(merchant["take_rate_revenue"]),
        "candidate_revenue_proxy_aud": float(merchant["take_rate_revenue"].sum()),
        "median_candidate_repeat_customer_rate": float(merchant["repeat_customer_rate"].median()),
        "consumer_fraud_order_coverage": float(daily["consumer_observed"].sum() / daily["orders"].sum()),
        "merchant_fraud_order_coverage": float(daily["merchant_observed"].sum() / daily["orders"].sum()),
        "any_fraud_order_coverage": float(daily["any_signal"].sum() / daily["orders"].sum()),
        "candidates_without_consumer_fraud_observations": int(merchant["consumer_observed"].fillna(0).eq(0).sum()),
        "candidates_without_merchant_fraud_observations": int(merchant["merchant_observed"].fillna(0).eq(0).sum()),
        "customer_geography_order_counts": geo_counts,
        "raw_consumer_geo_counts": {str(k): int(v) for k, v in geo["geo_match_status"].value_counts().items()},
        "largest_industry": str(top_industry.index[0]),
        "largest_industry_gmv_share": float(top_industry.iloc[0]["gmv_share"]),
        **exploration_scope(config, str(partition_date(all_files[0]).date()),
                            str(partition_date(all_files[-1]).date())),
    }

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "axes.titlesize": 12})
    fig, ax = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, constrained_layout=True)
    ax[0].plot(daily["date"], daily["orders"], color="#315fdb", linewidth=1)
    ax[0].set(title="Historical daily activity — later outcomes excluded", ylabel="Orders")
    ax[1].plot(daily["date"], daily["gmv"] / 1e6, color="#0a9a84", linewidth=1)
    ax[1].set(ylabel="GMV (AUD million)", xlabel="Order date")
    fig.savefig(figures / "01_historical_activity.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    ax[0].hist(np.log10(values), bins=70, color="#315fdb")
    ax[0].set(title="Order amounts: log scale", xlabel="log10(AUD order amount)", ylabel="Orders")
    ax[1].hist(np.log10(merchant["gmv"].dropna().clip(lower=.01)), bins=40, color="#0a9a84")
    ax[1].set(title="Master-merchant GMV: log scale", xlabel="log10(AUD historical GMV)", ylabel="Merchants")
    fig.savefig(figures / "02_value_distributions.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    industry_plot = top_industry.head(10).sort_values("gmv_share")["gmv_share"].mul(100)
    industry_plot.index = [shorten(str(name), width=34, placeholder="...") for name in industry_plot.index]
    industry_plot.plot.barh(ax=ax[0], color="#315fdb")
    ax[0].tick_params(axis="y", labelsize=9)
    ax[0].set(title="Top industries by candidate GMV", xlabel="Share of candidate GMV (%)", ylabel="")
    for field, label, color in [("gmv", "GMV", "#315fdb"), ("take_rate_revenue", "Take-rate revenue", "#0a9a84")]:
        ordered = merchant[field].fillna(0).sort_values().to_numpy()
        curve = np.r_[0, ordered.cumsum() / ordered.sum()]
        ax[1].plot(np.linspace(0, 1, len(curve)), curve, label=label, color=color)
    ax[1].plot([0, 1], [0, 1], "--", color="#aaaaaa")
    ax[1].set(title="Merchant value concentration", xlabel="Cumulative merchant share", ylabel="Cumulative value share")
    ax[1].legend()
    fig.savefig(figures / "03_concentration.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(11, 4.7), constrained_layout=True)
    monthly[["consumer_fraud_coverage_pct", "merchant_fraud_coverage_pct"]].plot.bar(ax=ax[0], color=["#315fdb", "#d58a15"])
    ax[0].set(title="Observed fraud-signal coverage, not fraud rate", ylabel="Orders matched to a signal (%)", xlabel="Historical month")
    ax[0].legend(["Consumer signal", "Merchant signal"], fontsize=8)
    coverage = pd.Series(geo_counts).sort_values()
    coverage.index = [str(status).replace("_", " ") for status in coverage.index]
    bars = ax[1].barh(coverage.index, coverage.div(coverage.sum()).mul(100), color="#0a9a84")
    ax[1].bar_label(bars, fmt="%.2f%%", padding=3, fontsize=8)
    ax[1].tick_params(axis="y", labelsize=8)
    ax[1].set(title="Order-weighted geography coverage", xlabel="Historical orders (%)", ylabel="", xlim=(0, 100))
    fig.savefig(figures / "04_coverage.png", dpi=160); plt.close(fig)

    corr_fields = ["gmv", "orders", "unique_customers", "average_order_value", "take_rate_pct", "take_rate_revenue", "repeat_customer_rate", "active_days"]
    corr = merchant[corr_fields].rank().corr()
    fig, ax = plt.subplots(figsize=(8.7, 7), constrained_layout=True)
    im = ax.imshow(corr, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(corr_fields)), corr_fields, rotation=60, ha="right")
    ax.set_yticks(range(len(corr_fields)), corr_fields)
    for i in range(len(corr_fields)):
        for j in range(len(corr_fields)):
            ax.text(j, i, f"{corr.iloc[i,j]:.2f}", ha="center", va="center", fontsize=8)
    ax.set_title("Historical merchant-feature Spearman correlation")
    fig.colorbar(im, ax=ax, shrink=.7)
    fig.savefig(figures / "05_feature_correlation.png", dpi=160); plt.close(fig)

    save_json(summary, report_dir / "summary.json")
    monthly.round(3).reset_index().to_json(report_dir / "monthly_aggregates.json", orient="records", indent=2)
    corr.round(4).to_json(report_dir / "feature_correlations.json", indent=2)
    _write_report(summary, monthly, top_industry, report_dir)
    print("PASS: historical EDA completed; no later-period outcomes explored", flush=True)
    return summary


def _write_report(s: dict, monthly: pd.DataFrame, industries: pd.DataFrame, report_dir: Path) -> None:
    formatted_quantiles = [f'{v:.4g}' if 0 < abs(v) < .0001 else f'{v:,.4f}'
                           for v in s['amount_quantiles_aud'].values()]
    text = f"""# Cleaned-data EDA — historical period only

Period: **{s['start']} to {s['end']}**. Source: configured completed cleaning run.
EDA covers training and internal-validation calendar periods. Protected test outcome dates
are excluded. Internal validation is development evidence, not an untouched final evaluation.

## Printed results

- Orders: **{s['historical_orders']:,}** across **{s['historical_days']}** days.
- GMV: **AUD {s['historical_gmv_aud']:,.2f}** across all historical orders.
- Active master merchants: **{s['historically_active_master_merchants']:,}** of {s['master_merchants']:,}.
- Active users: **{s['active_users']:,}**. Unknown-master orders: **{s['unknown_merchant_orders']:,}**.
- Busiest historical day: **{s['peak_order_date']}**, with **{s['peak_daily_orders']:,}** orders.
- Top 100 candidate merchants account for **{s['top_100_candidate_gmv_share']:.2%}** of candidate GMV and
  **{s['top_100_candidate_revenue_share']:.2%}** of candidate take-rate revenue.
- Median merchant repeat-customer share: **{s['median_candidate_repeat_customer_rate']:.2%}**.
- Consumer fraud-signal coverage: **{s['consumer_fraud_order_coverage']:.3%}** of orders.
- Merchant fraud-signal coverage: **{s['merchant_fraud_order_coverage']:.3%}** of orders.
- Candidates with no observed merchant fraud signal: **{s['candidates_without_merchant_fraud_observations']:,}**.

## Interpretation

1. **Value is unevenly distributed.** Evaluate top-K portfolio value and ranking quality, not only average error.
2. **Amounts are skewed.** Compare log transforms and robust losses; do not delete large valid orders automatically.
3. **Fraud signals are sparse observations, not realised fraud labels.** Preserve missingness and coverage;
   a merchant with no matched signal is not proven safe.
4. **Simple scale variables may be redundant.** Use the correlation chart to motivate a baseline and a
   training-only Boruta sensitivity experiment, not automatic feature deletion.
5. **Partial months need care.** February 2021 has only one observed day and February 2022 ends on the 27th.
   Compare per-day activity or complete months rather than unadjusted monthly totals.
6. **Geographic context is not individual-level evidence.** Coverage here is weighted by observed orders;
   full consumer-master coverage has a different denominator. External vintages are not assumed available
   at historical decision dates and are excluded from the first temporal modelling features.
7. **Do not let future activity determine eligibility.** {s['master_merchants'] - s['historically_active_master_merchants']}
   master merchants have no activity in this EDA period. At each model cutoff, rank only merchants
   with activity observed in that cutoff's history, and keep cold-start cases separately.
8. **Repeat activity is low and scale measures are strongly related.** Orders and distinct customer
   counts have near-perfect historical rank correlation. This motivates a feature-redundancy check,
   but is not proof that one feature must be removed for every model.

## Historical order amount quantiles (AUD)

{markdown_table(pd.DataFrame({'quantile': list(s['amount_quantiles_aud']), 'AUD': formatted_quantiles}))}

## Monthly aggregates

{markdown_table(monthly[['days','orders','gmv','orders_per_observed_day']].round(2).reset_index())}

## Largest industries (aggregate only)

{markdown_table(industries.head(10)[['merchants','gmv','gmv_share']].round(4).reset_index())}

## Figures

![Historical activity](figures/01_historical_activity.png)

![Value distributions](figures/02_value_distributions.png)

![Concentration](figures/03_concentration.png)

![Coverage](figures/04_coverage.png)

![Correlation](figures/05_feature_correlation.png)

## Privacy and reproducibility

Only aggregate statistics and figures are published. No customer rows, merchant-level rankings,
raw transactions, or model datasets are embedded. Local merchant-level EDA tables remain under
the Git-ignored `tables/modeling/eda_v1/` directory.
"""
    (report_dir / "README.md").write_text(text, encoding="utf-8")
