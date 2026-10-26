# Implementation roadmap

This roadmap separates implemented analytical foundations from later product work. The cleaning ETL,
historical EDA, rolling snapshots and validation-only baselines are operational. Generated tables and
model artefacts remain local and Git-ignored; no protected-test result or production model is claimed.

## Phase 1 — Agree on the decision

**Status: partially complete.** The portfolio objective and candidate cap are documented; an actual
business owner, intervention and operating capacity still require confirmation.

- Confirm whether the portfolio is for outreach, onboarding review, account management, or another
  action.
- Set the decision cadence, responsible owner, and team capacity.
- Define the commercial target and explicitly distinguish revenue from profit.
- Approve which constraints are policy and which are merely dashboard scenarios.

**Exit gate:** signed-off decision statement, target, users, and acceptable actions.

## Phase 2 — Create governed analytical data

**Status: implemented for the current course data.** Cleaning ETL v1.2, quality gates, 4,026-candidate
coverage files and the protected-period controls are implemented and reproducible.

Review follow-up adds privacy-minimised consumer staging, reference-versus-runtime manifests,
deterministic latest-day fraud, a full v3 feature-quality report and immutable local run IDs.
Final delivery still needs all-candidate handling, 3–5 segments and Top 10 per segment,
overall Top 100 explanations and protected-time evaluation.

- Register local source files and public reference vintages.
- Implement schema, uniqueness, coverage, and join checks.
- Resolve or quarantine the 396 transaction ABNs absent from the merchant master.
- Parse merchant tags with an exception queue.
- Remove unnecessary consumer PII before creating analytical features.
- Protect the later evaluation window from feature development.

**Exit gate:** documented `(merchant, cutoff)` snapshots, protected-period controls and a quality report.

## Phase 3 — Establish baselines and features

**Status: complete for baseline v1.** Forty-six predictors are materialised at merchant-cutoff grain.
Two trailing-revenue rules and four fixed tabular candidates are compared on validation only; the
selected specification is frozen but not test-evaluated.

- Build the business-supported feature families in the conceptual pipeline.
- Enforce historical-activity eligibility in model files while retaining all candidates for coverage.
- Aggregate fraud at native entity-day grain before calculating merchant risk evidence.
- Rank merchants using simple historical GMV, take-rate revenue, customer count, and recency
  baselines.
- Review feature distributions, missingness, correlation, and stability.

**Exit gate:** reviewed feature catalogue and reproducible baseline portfolio results.

## Phase 4 — Model and test Boruta

**Status: not started.** Boruta is optional and follows review of baseline v1.

- Train a future take-rate revenue model using only historical features.
- Evaluate numeric accuracy and ranking quality on validation, freeze the full pipeline, then open
  the primary test once.
- Run Boruta inside training data only, repeated across seeds/resamples.
- Compare all-feature, business-defined, and Boruta feature sets.
- Test sensitivity of the top portfolio, not only overall model error.

**Exit gate:** selected modelling approach with evidence that it improves or matches simple
baselines and remains stable.

## Phase 5 — Design risk, confidence, and portfolio policy

- Agree on defensible historical risk indicators and their limitations.
- Define evidence confidence from volume, active period, and source coverage.
- Set capacity, concentration, risk, and manual-review constraints.
- Run sensitivity and feasibility tests with business owners.

**Exit gate:** approved, versioned scenario policy and interpretation guide.

## Phase 6 — Build the dashboard workflow

- Implement the overview, explorer, decision card, scenario builder, and governance views.
- Add role-based access, export controls, audit logging, and human-review fields.
- Conduct usability testing with strategy, partnerships, and risk users.

**Exit gate:** users can reproduce a recommendation, understand it, challenge it, and record a
decision without seeing customer PII.

## Phase 7 — Pilot and monitor

- Run a shadow pilot before using the recommendations operationally.
- Record outreach, due-diligence, acceptance, activation, and realised outcomes.
- Monitor data freshness, feature drift, ranking stability, portfolio concentration, risk events,
  and override patterns.
- Define retraining, rollback, and model-retirement triggers.

**Exit gate:** measured business benefit and governance approval for broader use.

## Definition of done

The product is not complete merely because a model or dashboard runs. It is complete when:

- the later-period portfolio beats agreed simple baselines;
- data-quality failures stop or visibly qualify recommendations;
- privacy-minimised outputs are enforced;
- every recommendation has reasons, warnings, version, and cut-off date;
- portfolio constraints are explicit and reproducible;
- authorised users can record and audit human decisions; and
- monitoring and rollback responsibilities are assigned.

