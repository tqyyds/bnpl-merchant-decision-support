# Results and evidence

## Scale

The accepted ETL v1.2 manifest records 14,195,505 transactions over 606 date partitions, 499,999 consumers and 4,422 merchant master records. It removed 99 exact duplicate consumer-fraud observations and normalised 971 raw category variants into 25 categories. See [`etl_summary.json`](../reports/portfolio/etl_summary.json) and the original aggregate [`v1_2_manifest.json`](../reports/etl/v1_2_manifest.json).

These counts describe the historical local dataset. The public repository contains code and aggregates, not those records.

## Model comparison

[`model_comparison.json`](../reports/portfolio/model_comparison.json) is copied from historical run `seven_v1_20260906`. Its six model-family results are validation means across three cutoffs. The 90-day run rate achieved NDCG@100 0.9938591111 and oracle revenue capture@100 0.9957828142. The three-seed TCN achieved 0.9901850002 and 0.9959207960 respectively; it did not pass the fixed multi-metric gate to replace the baseline. TCN final epochs were 34, 42 and 20. [`runtime.json`](../reports/portfolio/runtime.json) records the original environment.

The strongest engineering result is an evidence-based selection process: a trained complex model is evaluated against simple baselines under the same temporal contract, and the selected solution follows the predeclared rule.

NDCG uses nonnegative linear income gain. Oracle capture is the selected merchants' realised take-rate income divided by the hindsight Top-100 income at the same cutoff. Neither is classification accuracy or a claim about actual lending profit. Repeated merchants, three validation cutoffs and overlapping histories limit independence and generalisation.

## Portfolio and integration evidence

The retained [`independent_validation.json`](../reports/portfolio/independent_validation.json) reconciles saved results across three validation dates, eight test dates and one latest date. It includes five saved portfolio scenarios and independent group recommendation slots, with a verdict of “Share with caveats.” Its status attests historical checks, not fresh model training in this public edition.

The dashboard audit describes reconciliation of 60 historical date/scenario combinations. Current public tests use synthetic fixtures to exercise temporal boundaries, exhaustive small MILP cases, source contracts, missingness, lineage, invalid files, HTTP routes and frontend DTO validation. Current test counts are recorded separately in [`PUBLIC_RELEASE.md`](PUBLIC_RELEASE.md).

## Limitations that remain visible

- **Target:** take-rate income is a revenue proxy; servicing costs, contractual acceptance, validated fraud losses and onboarding costs are unavailable.
- **Confidence:** some historical calibration bins fail acceptance. Conservative scenarios are sensitivity analyses, not certified revenue floors or joint portfolio guarantees.
- **Risk:** missing native evidence is unknown. The selected latest portfolio has unknown native risk evidence in the retained audit. No validated loss budget is active in the historical primary optimiser.
- **Metadata:** static master attributes and fraud publication times have point-in-time limitations. Consumer catchment is not merchant location.
- **Latest outcomes:** the latest historical cutoff is 26 October 2022; future realised outcomes are unobservable in the supplied data. It is not today's live market state.
- **Code drift:** saved outputs do not prove the current source exactly matches the historical freeze; the changed portfolio file is disclosed in the retained audit.
- **Public reproduction:** raw data and trained artifacts are deliberately absent. Demo values are invented and separate from the historical aggregate metrics.

See [`dashboard/ENGINE_AUDIT_2026-10-05.md`](../dashboard/ENGINE_AUDIT_2026-10-05.md) for the original detailed audit and proposed follow-up work.
