# Course fraud proxy GAM implementation

## Decision scope

The project will not receive final-adjudication fraud outcomes or realised-loss components. The
trainable Risk path is therefore a course-only proxy model, not a production fraud or loss model.
The course specification permits transactions matching the supplied fraud delta to be treated as
fraud. The actual sources are consumer-day and merchant-day probability tables without an
`order_id`; matching them to orders propagates an entity-day signal and does not create independently
confirmed fraud events.

The permanent states are:

```text
fraud_model_status = PROXY_SHADOW
loss_model_status  = NOT_AVAILABLE
risk_status        = EVIDENCE_ONLY_NO_LOSS_LABELS
```

`predicted_net_loss_28d_aud` and `predicted_loss_rate_28d` remain null. Proxy outputs do not enable
portfolio loss constraints or alter the formal Top-100 ranking.

## Proxy label and coverage

The primary `UNION_PROPAGATED` label is true when either the consumer-day or merchant-day delta
matches an order and false when neither matches. It is versioned as `course_delta_union_v1` with
semantics `OBSERVED_COURSE_DELTA_NOT_FINAL_ADJUDICATION`. Every labelled transaction records the
source and both match multiplicities.

Two fixed sensitivity definitions are also evaluated. `CONSUMER_ONLY` ignores merchant-day matches.
`SINGLE_MATCH_ONLY` retains a positive only when at least one matched entity-day key maps to exactly
one order; propagated matches are excluded rather than relabelled negative.

Both fraud sources end on 27 February 2022. The label-aware protocol therefore stops on that date:

| Role | Inclusive dates | Use |
|---|---|---|
| Train | 29 May-5 December 2021 | Weighted fitting and three internal rolling folds |
| Calibration | 6 December 2021-2 January 2022 | Sigmoid/Platt mapping only, complete prevalence |
| Validation | 3-30 January 2022 | Family comparison and review thresholds |
| Locked test | 31 January-27 February 2022 | One evaluation after selection |

Transactions after 27 February 2022 are unlabelled shadow-scoring candidates. They must not be
treated as negative or used for PR-AUC, calibration, or model selection.

## Point-in-time features

Daily partitions are processed chronologically. Features for day `t` are calculated before day `t`
is written to rolling state, so every history ends at `t-1`. Entity identifiers are join/state keys,
never predictors. The model uses log amount and activity features, 30-day consumer/merchant history,
90-day prior proxy rates, a consumer amount z-score, its availability flag, and merchant category.

The z-score is null unless the consumer has at least three prior 30-day transactions and a non-zero
amount standard deviation. It is never silently set to zero. Only Train is negative-sampled at a
deterministic 5% rate; sampled negatives receive inverse-probability weight 20. Calibration,
Validation, locked Test, and merchant scoring use complete prevalence.

## Models

The baseline is median imputation, scaling, one-hot merchant category, and L2 Logistic Regression.
The candidate is accurately described as a **penalised spline logistic GAM-style model**: cubic
quantile spline bases followed by a common L2 logistic penalty. Missing indicators use a separate
linear branch and are never spline-expanded.

The fixed candidate grid contains Logistic `C` in `{0.1, 1, 10}` and GAM-style `n_knots` in
`{4, 6, 8}` crossed with the same three `C` values. Degree remains three. Features with fewer than
eight unique Train values or more than 95% zeros fall back to a linear term. The complete spline QA
is saved with the run.

The full GAM-style model is compared with `NO_HISTORY_PROXY_RATE`, which removes consumer and
merchant prior proxy-rate features. A large performance gap would mean that persistence in the
course signal dominates transaction characteristics.

## Executed result

Run `gam_proxy_v1d_20260907` completed successfully. Internal rolling selection chose Logistic
`C=0.1` and GAM-style `n_knots=6, C=10`. Validation selected the GAM-style family under the frozen
non-inferiority checks.

| Metric | Logistic validation | GAM-style validation | GAM no-history validation | GAM locked test |
|---|---:|---:|---:|---:|
| Proxy PR-AUC | 0.4487 | 0.5168 | 0.5149 | 0.4930 |
| Brier score | recorded in artifact | recorded in artifact | recorded in artifact | 0.00792 |
| 10-bin ECE | recorded in artifact | recorded in artifact | recorded in artifact | 0.00190 |

At locked-test 1% review capacity, precision was 0.6113 and recall 0.4895. At 5%, precision was
0.1381 and recall 0.5530. These are proxy-label metrics only. The small full-versus-ablation PR-AUC
gap indicates that the selected result is not mainly explained by the two prior proxy-rate features,
but it does not establish real-fraud generalisation.

`UNION_PROPAGATED` and `CONSUMER_ONLY` were identical in the locked-test window because no matched
merchant-day-only positives occurred there. `SINGLE_MATCH_ONLY` changed both prevalence and the
evaluation population materially, so its higher PR-AUC is not directly comparable and is retained
as label-grain sensitivity rather than evidence of better real-fraud accuracy.

## Merchant evidence and ranking boundary

The selected, independently calibrated proxy model is aggregated over the trailing 90 days into
count-weighted and amount-weighted mean probabilities, observed course-proxy rate and amount share,
high-risk transaction share, and a cross-merchant evidence percentile. The amount-weighted value is
dimensionless evidence; it is not AUD expected loss.

Optional ranking sensitivities may use fixed lambdas `{0, .05, .10, .20}` with
`revenue_percentile - lambda * risk_evidence_percentile`. No lambda is estimated as optimal, and
`ranking_penalty_enabled` remains false until a human explicitly chooses a reporting scenario.

## Reproduction

From the repository root:

```powershell
python -m scripts.train_course_fraud_proxy `
  --root . `
  --run-id <new_run_id> `
  --config config/course_fraud_model_v1.json
```

The destination is immutable. It contains tuning evidence, fitted models/calibrators, locked-test
predictions, merchant evidence, evaluation, manifest, state, and `_SUCCESS`. Restricted row-level
artifacts remain Git-ignored.
