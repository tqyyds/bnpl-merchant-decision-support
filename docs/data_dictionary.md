# Analytical data dictionary

This document separates fields implemented in rolling snapshot v3 from planned or deferred product
fields. It does not imply that a production model has been approved.

## Source data

| Source | Grain | Relevant fields | Treatment |
|---|---|---|---|
| `tbl_merchants.parquet` | Merchant | name, tags, merchant ABN | Parse industry, tier, and take rate |
| Transaction snapshots | Order | user ID, merchant ABN, dollar value, order ID | Recover order date from partition path |
| `consumer_user_details.parquet` | User mapping | user ID, consumer ID | Join key only |
| `tbl_consumer.csv` | Consumer | state, postcode, name, address, gender | Retain state/postcode only; remove PII and gender |
| Consumer fraud probabilities | User-day observation | user ID, date, probability | Remove exact duplicates; aggregate native evidence; presence may define the explicitly named course proxy label |
| Merchant fraud probabilities | Merchant-day observation | merchant ABN, date, probability | Remove exact duplicates; retain native weighting; any order propagation records match multiplicity |
| ABS GCP and SEIFA | Postal Area | population, income, age context, indexes | Registered but deferred from rolling predictors |
| Operational risk events | Append-only event version | order, merchant, loss case/component, event type, status, business/availability timestamps, AUD amount | Future production source only; absent from course data |
| Finance loss reconciliation | Accounting period and approved dimensions | fraud loss, credit loss, fees, recoveries, net loss | Future production control only; absent from course data |

## Implemented rolling snapshot v3

The authoritative formula/unit/missingness/availability catalogue for all 46 predictors is
[`feature_catalogue.md`](../reports/feature_qa/rolling_90d_28d_v3/feature_catalogue.md).
v3 replaces arbitrary same-day consumer latest selection with latest-day equal-user mean.

Every supervised row represents one master merchant at one decision cutoff. Historical predictors
begin with `hist_`; later outcomes begin with `future_` and remain in separate evaluation-only label
files. Zero-history master merchants are retained in local coverage snapshots but excluded from
model feature/label files.

### Metadata — never predictors

| Field | Meaning |
|---|---|
| `merchant_abn` | Merchant join key; never used as a predictor |
| `cutoff` | Simulated decision date; feature information ends on this date |
| `history_start` / `history_end` | Inclusive 90-day feature window |
| `eligible_history` | Whether the merchant has at least one order in the feature window |

### Predictors — 46 implemented fields

| Family | Implemented fields | Meaning |
|---|---|---|
| Static merchant attributes | `merchant_category`, `revenue_level`, `take_rate_pct` | Normalised tag category, parsed a–e level and contractual take rate |
| Scale and order value | `hist_gmv`, `hist_orders`, `hist_unique_customers`, `hist_aov`, `hist_amount_median`, `hist_amount_std`, `hist_active_days` | Historical size, customer reach, order-value distribution and activity |
| Engagement and concentration | `hist_repeat_customer_rate`, `hist_customer_hhi`, `hist_orders_per_customer` | Repeat share, customer GMV concentration and ordering intensity |
| Recency and momentum | `hist_gmv_last28`, `hist_gmv_previous28`, `hist_gmv_last7`, `hist_growth_28d`, `hist_no_previous28_activity`, `hist_days_since_last_order` | Recent value, adjacent-period growth and recency |
| Stability and tail | `hist_daily_gmv_cv`, `hist_amount_cv`, `hist_gmv_per_active_day`, `hist_active_day_rate`, `hist_high_value_order_share`, `hist_high_value_gmv_share` | Daily/order volatility, active cadence and snapshot-local P99 tail exposure |
| Revenue and transforms | `hist_revenue_proxy`, `hist_gmv_log1p`, `hist_orders_log1p`, `hist_unique_customers_log1p`, `hist_revenue_proxy_log1p` | Historical take-rate revenue and skew-reducing transforms |
| Consumer fraud evidence | `hist_customer_entity_days`, `hist_consumer_signal_entity_days`, `hist_consumer_signal_days`, `hist_consumer_probability_mean`, `hist_consumer_probability_max`, `hist_consumer_probability_latest_day_mean`, `hist_consumer_signal_coverage`, `hist_consumer_signal_recency_days`, `hist_consumer_signal_missing` | Distinct merchant-user-day coverage; latest averages observed users on the latest matched day; absence remains missing evidence |
| Merchant fraud evidence | `hist_merchant_signal_days`, `hist_merchant_probability_mean`, `hist_merchant_probability_max`, `hist_merchant_probability_latest`, `hist_merchant_signal_calendar_coverage`, `hist_merchant_signal_recency_days`, `hist_merchant_signal_missing` | Native merchant-day coverage and probability summaries; absence remains missing evidence |

The exact ordered list is versioned under `reports/time_split/rolling_90d_28d_v3/`. No-fraud
variants exclude signal/probability fields; they retain `hist_customer_entity_days`, which counts
commercial exposure independently of whether any fraud signal is present.

### Separate label files

| Field | Meaning |
|---|---|
| `merchant_abn` / `cutoff` | Alignment key shared with the feature file |
| `label_start` / `label_end` | Inclusive next-28-day outcome window |
| `future_gmv` | Observed next-28-day GMV |
| `target_revenue` | Next-28-day GMV multiplied by contractual take rate |

All outcomes beginning 2022-02-28 are protected. Baseline v1 reads only train and validation labels.

These are Revenue labels only. They are not fraud, default, chargeback, or realised-loss labels.

## Course fraud proxy model — implemented shadow extension

The course-only implementation is defined in
[`course_fraud_proxy_gam.md`](analysis/course_fraud_proxy_gam.md). Its transaction grain is one row
per `order_id`, but its label evidence originates at consumer-day and merchant-day grain.

| Field | Meaning |
|---|---|
| `is_fraud` | Course proxy target under the declared label variant; never final adjudication |
| `course_label_source` | consumer-day, merchant-day, both, or no delta match |
| `consumer_day_match_multiplicity` / `merchant_day_match_multiplicity` | Number of same-day orders receiving the entity-day signal |
| `fraud_label_version` / `fraud_label_variant` | Versioned proxy definition and sensitivity semantics |
| `fraud_label_semantics` | Always `OBSERVED_COURSE_DELTA_NOT_FINAL_ADJUDICATION` |
| `predicted_course_fraud_probability` | Calibrated probability of the course proxy label, not confirmed fraud |
| `fraud_model_version` | Explicit Logistic or penalised spline logistic GAM-style artifact name |
| `fraud_model_status` | Permanently `PROXY_SHADOW` |

Merchant evidence adds `historical_course_fraud_rate`, `historical_course_fraud_amount_share`,
`mean_predicted_course_fraud_probability`, `amount_weighted_predicted_course_fraud_probability`,
`high_risk_transaction_share`, and `fraud_risk_evidence_percentile`. The amount-weighted probability
is dimensionless and must not be renamed or summed as AUD loss. `loss_model_status` remains
`NOT_AVAILABLE`; both predicted net-loss fields remain null.

## Future production risk labels — designed, not implemented

The approved future-state definitions and complete audit contracts are in
[`risk_label_and_loss_design.md`](analysis/risk_label_and_loss_design.md). No table in this section
exists in the current runtime. Daily course `fraud_probability` values may not be presented as
production fraud or loss targets; only their matched presence may be used under the separately named
and caveated course proxy contract above.

### `operational_risk_events`

Append-only grain: one immutable event version per `event_id`, also unique on
`(source_system, source_record_id, revision)`. Effective versions are resolved point-in-time using
`available_at`, explicit supersession, and reversal chains. Conflicts are quarantined rather than
resolved by selecting the largest revision.

Required fields include `event_id`, `source_system`, `source_record_id`, `revision`,
`supersedes_event_id`, `original_loss_event_id`, `loss_case_id`, `loss_component_id`, `order_id`,
`merchant_abn`, `event_type`, `case_status`, `occurred_at`, `available_at`, and `amount_aud`.

### `order_fraud_labels`

Grain: one row per `(order_id, label_version)`.

| Field family | Required fields and interpretation |
|---|---|
| Keys and decision time | `order_id`, `merchant_abn`, `order_created_at`, `scored_at`; `scored_at` is the payment-authorisation decision point |
| Observation audit | `label_as_of`, `label_generated_at`, `data_as_of`, `observation_end`, `maturity_at` |
| Target | nullable `fraud_label`, `label_status`, `label_reason_code`, `confirmed_at` |
| Coverage and matching | `source_coverage_complete`, `required_sources`, `missing_sources`, `coverage_snapshot_id`, `order_match_status` |
| Reproducibility | `label_version`, `source_snapshot_hash`, `label_code_version`, `label_config_hash` |

Only final confirmed fraud is positive. A negative requires an approved maturity window, complete
source coverage, and no effective confirmed-fraud event. All unresolved cases remain null.

### `merchant_loss_labels`

Grain: one row per `(merchant_abn, cutoff, label_version)`. Orders authorised in the inclusive
next-28-day cohort are observed through `label_end + maturity_window_days`; recoveries and reversals
remain attributed to their original order cohort. The merchant universe comes from the eligible
cutoff snapshot, never from future orders, so zero-future-order merchants remain in the label table.

| Field family | Required fields and interpretation |
|---|---|
| Keys and window | `merchant_abn`, `cutoff`, `label_start`, `label_end`, `maturity_at` |
| Observation audit | `label_generated_at`, `label_as_of`, `data_as_of`, `observation_end`, `is_mature`, `label_status`, `label_reason_code` |
| Exposure | `future_orders`, `future_gmv_aud`; GMV is gross authorised eligible-order value before loss adjustments |
| Outcomes | `confirmed_fraud_orders`, `fraud_rate`, `gross_fraud_loss_aud`, `gross_credit_loss_aud`, `fees_aud`, `recoveries_aud`, `net_loss_aud`, nullable `net_loss_rate` |
| Quality | `denominator_status`, `currency`, `source_coverage_complete`, `required_sources`, `missing_sources`, `coverage_snapshot_id`, `reconciliation_status` |
| Reproducibility | `label_version`, `source_snapshot_hash`, `label_code_version`, `label_config_hash` |

`net_loss_aud = gross_fraud_loss_aud + gross_credit_loss_aud + fees_aud - recoveries_aud`. Components are
non-negative and one economic loss component cannot be counted as both fraud and credit loss.
When future GMV is zero, the loss rate is null rather than zero; positive loss with zero future GMV
is quarantined.

## Planned or deferred fields — not in snapshot v2

Supplemental context and candidate-status fields are now implemented separately in
`tables/features/customer_context_v1/`; see [the context contract](analysis/customer_context_contract.md).
They are included in the latest merchant export, but do not expand the primary 46-predictor allow-list.
The older planned names below remain historical aliases rather than exact current schema names.

| Field or family | Status and reason |
|---|---|
| `merchant_name` | Display-only candidate; intentionally excluded from predictors |
| `hist_postcode_gmv_hhi`, `hist_state_gmv_hhi`, `hist_dominant_customer_state` | Deferred; customer residence is not merchant location |
| `hist_monthly_gmv_cv`, month-to-month `hist_gmv_growth` | Superseded in v2 by daily CV and adjacent 28-day growth |
| `hist_postal_context_coverage`, weighted household income and IRSD | Deferred until as-of availability and geographic interpretation are approved |
| `hist_confidence_score` | Planned decision-support field; no agreed formula |

The older conceptual names map to v2 as follows:

| Earlier conceptual name | Implemented v2 treatment |
|---|---|
| `industry` | `merchant_category` |
| `merchant_tier` | `revenue_level` |
| `take_rate_percent` | `take_rate_pct` |
| `hist_take_rate_revenue` | `hist_revenue_proxy` |
| `hist_transaction_count` | `hist_orders` |

## Proposed merchant score and portfolio fields — not implemented

| Field | Meaning |
|---|---|
| `predicted_future_take_rate_revenue` | Model prediction in currency units |
| `risk_index` | Historical conceptual alias only; the current engine exposes separate evidence components and does not calculate an aggregate index |
| `confidence_score` | 0–1 evidence coverage measure |
| `probability_of_eventual_confirmed_fraud` | Future order-model probability conditional on information available at the payment-authorisation decision point |
| `predicted_net_loss_28d_aud` | Future merchant-model conditional mean net loss for the next 28-day cohort |
| `predicted_net_loss_28d_p95_aud` | Future conservative P95 loss output; not an expected-loss estimate |
| `predicted_loss_rate_28d` | Future predicted loss divided by predicted gross authorised GMV at portfolio-compatible grain |
| `predicted_future_gmv_28d_aud` | Positive denominator required for a portfolio loss-rate constraint |
| `risk_state` | Future state: evidence-only, shadow, validated, degraded-label-quality, or degraded-model-quality |
| `risk_adjusted_value` | Historical conceptual alias; future design uses explicit loss-budget constraints rather than an arbitrary combined score |
| `decision_score` | Percentile rank of risk-adjusted value, scaled 0–100 |
| `review_class` | eligible, manual review, or data unresolved before optimisation |
| `positive_reasons` | Semicolon-separated business reason codes |
| `warnings` | Semicolon-separated limitations and warnings |
| `portfolio_selected` | Whether the current scenario selected the merchant |
| `portfolio_rank` | Rank among selected merchants |
| `portfolio_decision` | Recommended, selected for review, not selected, or unresolved |

Risk-constrained scenarios are future-state only. They require `risk_state = VALIDATED`, consistent
non-null finite predictions, a single model/label/as-of contract, and at least one authorised
`max_total_expected_net_loss_aud` or `max_expected_loss_rate` setting. Missing predictions are never
filled with zero.
