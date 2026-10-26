# Seven-engine protocol v1

This is the approved implementation protocol. It supersedes the previous training pause,
the v2 engine branch, and any suggestion to refit on train plus validation. It does not
constitute real onboarding approval, a profit model, or a production fraud classifier.

## Data and decision scope

Only completed cleaning `v1_2` and `rolling_90d_28d_v3` are accepted. The local source
manifest and all referenced snapshot files are SHA-256 checked. Cleaned source files
are additionally hashed at the full-system freeze. Raw and derived course data remain
private and ignored by Git. Static merchant attributes are assumed historically available;
this cannot be established from the provided synthetic master.

All dates are inclusive course calendar dates, without invented intraday timestamps.
Cutoff means the day's complete partition has arrived. Each row is merchant × cutoff.
The model targets next-28-day GMV × take-rate / 100 in AUD, not profit or credit loss.

| Role | Cutoffs | Model rows | Future-label use |
|---|---|---:|---|
| Train | 20 Jun, 18 Jul, 15 Aug, 12 Sep, 10 Oct, 7 Nov 2021 | 23,537 | Fitting and three expanding temporal folds |
| Validation | 5 Dec 2021, 2 Jan and 30 Jan 2022 | 11,872 | Fixed candidate selection and complete-system validation |
| Primary test | 27 Feb 2022 | 3,930 | 28 Feb–27 Mar 2022, scored after prediction freeze |
| Robustness | 27 Mar, 24 Apr, 22 May, 19 Jun, 17 Jul, 14 Aug, 11 Sep 2022 | 27,514 | Seven non-overlapping 28-day outcomes, ending 9 Oct |
| Latest recommendation | 26 Oct 2022 | Determined from historical eligibility | No observable future outcome; never report realised revenue |

All 4,026 master candidates are retained in disposition outputs. For the primary test,
96 have no recent history and are not model rows. Unknown masters are retained in a
separate disposition category, not inferred through ABR. Future zero-revenue labels remain.
Historical windows overlap and the same merchants recur; non-overlapping labels are
not a claim of statistical independence. Only three validation dates are available.

## Revenue training and multi-metric selection

Outer folds: T1–T3 → T4, T1–T4 → T5, T1–T5 → T6. Every fold fits its own preprocessing.
Hyperparameters are selected by mean train-OOF NDCG, then oracle capture and a fixed
configuration-name tie break. Each selected family is finally fit on T1–T6 only.

Candidates: 28-day and 90-day revenue run rates; log-target Ridge alpha 1/10/100;
HGB log squared loss and raw Poisson loss, leaves 15/31 × iterations 100/250,
learning rate .05, minimum leaf 30, L2=1, automatic early stopping disabled.
Predictions return to AUD and are floored at zero. No label clipping or deletion occurs.

TCN: 30 daily steps, six channels; four causal residual blocks with two convolutions
per block, 16 channels, kernel 3, dilations 1/2/4/8, dropout .1. Last-step representation
plus static inputs feeds a 32-unit hidden layer and log-revenue output. MSE, AdamW,
lr .001, weight decay .0001, batch 256, maximum 100 epochs, gradient clip 1.
Seeds: 30034, 30035, 30036. No pretrained financial-market weights are transferred.

For each seed and outer fold, its last training cutoff is the inner early-stop date;
select epoch by NDCG@100 (earliest epoch wins ties), patience 10, then reinitialise
and train on the complete outer training fold for that many epochs. Final training
uses T1–T5 to select epochs on T6, reinitialises again, refits preprocessing on T1–T6,
and retrains for the saved per-seed epoch count. Average three AUD predictions.

A challenger replaces the 90-day baseline only when mean validation NDCG improves
by at least .001, mean oracle capture does not fall, and NDCG improves on at least
two dates. Among passing challengers use NDCG, capture, then fixed name order.
This is a pre-specified multi-metric rule, not statistical significance. NDCG uses
linear realised AUD relevance and log2 rank discounts; zero ideal relevance scores 1.
Portfolio income is a set sum, unaffected by order within an unchanged selected set.
Business reporting separates NDCG, selected realised revenue, capture and opportunity costs.
LambdaMART is unverified; Boruta and additional tuning are deferred.

## Confidence and risk evidence

Reliability is the geometric mean of capped train-P90 normalised log order volume,
active_days/90, exp(-recency/28), and complete source partitions/90. High >= .8,
medium >= .5, otherwise low; required missing evidence is unresolved. It is not a
probability of predictive correctness. Fraud evidence reliability is separate; registry
availability does not reduce the Revenue score.

Income bins use **historical 90-day `hist_revenue_proxy` only**. Train cutoffs receive
equal total weight when fixing quartile edges. Bins are right-closed and repeated edges
merge. Labels never choose a bin. Absolute log errors from T4–T6 OOF predictions supply
90th-percentile widths; each bin needs >=200 samples and >=2 dates or falls back globally.
OOF dates receive equal total weight within each error quantile. Intervals are expm1 of
log prediction +/- width, with lower bound >=0. Calibration is checked on all merchants,
each historical bin, ordinary Top-100, and conservative Top-100 for each validation date.
Deviation from 90% >5pp, any all-merchant date <80%, or conservative selected date <80%
is labelled insufficient. The conservative scenario remains a labelled descriptive
sensitivity; calibration inadequacy prevents reliability claims, not disclosure of its results.
Summing individual lower bounds NEVER establishes a 90% portfolio income guarantee.

Risk uses v3 native merchant-user-day and merchant-day evidence. Consumer latest means
equal user weights on the latest observed day, not an arbitrary last user. v3 probabilities
are fractions (raw-source probabilities were percentage points). Raw component values,
same-cutoff percentiles, counts, coverage and recency remain separate. Missing probabilities
stay null, including nullable 50%/80% manual-review prompts. No composite weights, real
fraud classification metrics, empirical-Bayes pseudo-counts, or monetary loss are invented.

An independently executed course-only proxy extension is specified in
[`course_fraud_proxy_gam.md`](course_fraud_proxy_gam.md). It uses the course-authorised convention
that orders matching consumer-day or merchant-day delta rows are proxy positives. Because the raw
delta has no `order_id`, this is an entity-day propagated proxy label, not final adjudication. The
penalised spline logistic GAM-style model remains `PROXY_SHADOW`; its transaction output is
`predicted_course_fraud_probability`, and its merchant aggregates are evidence only. Its label-aware
period ends with source coverage on 27 February 2022. Later transactions are unlabelled shadow
scoring data, never assumed negatives. This extension does not change the authoritative Top-100.

The future production fraud/loss extension is specified in
[`risk_label_and_loss_design.md`](risk_label_and_loss_design.md). It is a conditional design
approval, not part of seven-engine v1. Under the project's permanent no-real-label assumption it is
a reference contract rather than an executable roadmap. The current runtime state remains
`EVIDENCE_ONLY_NO_LOSS_LABELS`; the target state machine, operational ledgers, mature labels,
loss predictions, and risk-budget constraints do not exist in the current project.

## Future fraud and loss extension — inactive implementation contract

The repository includes opt-in validators, pure label builders, maturity helpers, and fail-closed
portfolio constraint support. They are not called by the authoritative seven-engine run and have
only synthetic test coverage. Production activation still requires an append-only operational
risk-event ledger with globally
unique events; version keys unique on `(source_system, source_record_id, revision)`; stable
`order_id`, `loss_case_id`, and `loss_component_id`; explicit supersession/reversal chains; and both
business-effective and analytical-availability timestamps. For any label build at `label_as_of = T`,
only event versions with `available_at <= T` may be resolved. Conflicting chains are quarantined;
choosing the largest revision without validating lineage is prohibited.

Order labels predict eventual confirmed fraud at the actual payment-authorisation decision time.
Merchant labels use the next 28-day gross-authorised order cohort and non-negative fraud loss,
credit loss, fee, and recovery components. One economic loss amount cannot be classified into both
fraud and credit gross loss; recoveries and reversals remain attached to their original order cohort.
Net loss is:

$$
L = L_{fraud} + L_{credit} + fees - recoveries
$$

Future GMV of zero produces a null loss rate and an explicit denominator status. Positive loss with
zero GMV, negative net loss, missing source coverage, or failed Finance reconciliation quarantines
the label; none is coerced to zero.

The initial maturity candidate is 90 days, subject to a risk-owner-approved maximum rate of labels
that change after maturity. If 90 days fails, maturity is retested at 120 and 150 days; failure at
all approved candidates produces `DEGRADED_LABEL_QUALITY`. The required development history is at
least 18 months of mature labels. The most recent three eligible non-overlapping 28-day windows are
protected test, the preceding three are validation, and earlier windows are training. Metric
thresholds are preregistered before test labels are opened.

The target future states are `EVIDENCE_ONLY_NO_MATURE_LABELS`, `SHADOW`, `VALIDATED`,
`DEGRADED_LABEL_QUALITY`, and `DEGRADED_MODEL_QUALITY`. Only `VALIDATED` may activate a configured
portfolio hard risk constraint; every other state retains evidence/review displays and disables
decisioning loss constraints.

## Five course groups and recommendations

`engines/contracts.py::GROUPS` is the canonical exact 25-string mapping. It groups
operating activities into Home/Garden/Decorative Arts; Fashion/Personal Care/Accessories;
Digital/Technology/Communications; Mobility/Outdoor; Culture/Creative/Gifts/Office.
See the generated input contract for every original string and rationale.
Every category appears exactly once; unknown categories fail, never fuzzy-match.
The spelling of existing normalised categories, including source typos, is intentional.

After common eligibility, the same frozen Revenue model ranks each complete group
by prediction descending and canonical 11-digit synthetic merchant ID ascending.
Group Top-10 is independent of overall Top-100, not its subset or a concatenation
substitute. Fewer than ten means an explicit shortage. Group models are not separately fit.
Per-group reporting includes size, NDCG@10, selected realised revenue, group oracle
capture, interval coverage and selected/unselected historical-feature comparisons.

## Other rules and portfolio MILP

Eligibility requires master, orders >=1, active days >=1 and finite rate 0<rate<=100.
Onboarding eligibility remains unknown. No future revenue filtering is allowed.
Diversification describes category and all-GMV customer-state catchment shares,
HHI, Shannon entropy, exp(entropy), and marginal category HHI. UNKNOWN geography is
retained. Existing matched-only `ctx_` HHIs have a different denominator and are not mixed.
Customer residence is not merchant location; no geography enters Revenue or constraints.
Strategic fit has dated, owned and reasoned MCDA rules, but defaults NOT_CONFIGURED,
null score, zero monetary bonus and no exclusions. Dimensionless scores are not AUD.

SciPy MILP explicitly uses integer variables and Bounds(0,1), with negative income
coefficients for minimisation. Formal capacity <=100; sensitivities cap each category
at 30 or 20 or low/unresolved Revenue confidence at 10. Conservative lower-bound
ranking is separate. Optimise income first, then cardinality under the income lock,
then ascending-ID lexicographic inclusion under both locks. No epsilon-weighted
mixed objective. A second feasible-solution exclusion proves uniqueness when possible;
otherwise sequential feasibility solves implement the ID objective exactly.
Tolerance is atol 1e-6 AUD + rtol 1e-9 × |optimal revenue|; mip_rel_gap=0.
Compare feasibility and income first, then count and IDs under identical tie rules.
Timeout incumbents/gaps are not claimed optimal; full-system scoring stops if a required
optimum is unproven. Baseline and oracle use the identical candidate universe and constraints.
Realised opportunity cost may be negative. Source: [SciPy MILP](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html).

For a future risk-constrained scenario, let binary `x_i` select merchant `i`, `L_i` be either the
conditional mean loss for `EXPECTED_LOSS` or P95 loss for `CONSERVATIVE_LOSS_P95`, and `G_i` be
predicted next-28-day gross authorised GMV. The optional amount and rate constraints are:

$$
\sum_i x_i L_i \le B_L
$$

$$
\sum_i x_i L_i \le r_{max}\sum_i x_i G_i
$$

The rate uses portfolio totals, never the simple average of merchant loss rates, and selected GMV
must be positive. A risk-constrained run requires at least one authorised budget, `VALIDATED` risk
state, and finite non-null predictions sharing the same model version, label version, scenario, and
prediction-as-of timestamp. Invalid inputs return `INVALID_RISK_INPUTS`; an infeasible approved
budget returns `INFEASIBLE`. The optimiser must not fill missing values with zero, relax a budget,
or change loss scenarios automatically. Meeting an expected or P95 budget is not a guarantee that
realised loss will remain below it.

## State machine and private tutor delivery

`engines.train` never loads test features or labels. `engines.system develop` validates
all components and scenarios. `freeze` records code, source, model and policy hashes.
`test` verifies the freeze, saves all eight test prediction and selection files and their
hash lock, then opens labels for scoring. It refuses to overwrite an existing test run.
Latest recommendations use the identical frozen model and policies without labels.
Any post-test model/policy change is a new developed system, not the same untouched test.

Local tutor HTML, named-merchant CSVs, complete dispositions and the course ZIP contain
actual recommendations. Public GitHub contains code, methods and aggregate evidence only.
The demo dashboard is not a course result. ABNs are synthetic; source merchant names are
course records, not verified real-world business identities. Share the tutor ZIP through
a course-approved private channel. Do not upload it publicly or retrain to inspect it.
