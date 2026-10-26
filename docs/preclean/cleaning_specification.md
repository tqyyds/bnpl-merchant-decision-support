# Cleaning Specification v1.0.1

This document defines the transformations implemented by `src/bnpl_etl`. Raw files remain unchanged; the accepted v1.1 outputs are recorded in `reports/etl/v1_1_manifest.json`.

## Implemented pipeline order

1. Verify all manifest hashes, ZIP CRCs, required members, schemas and transaction baseline.
2. Materialise partition dates and canonical identifier strings in a new staging location outside `tables/raw`.
3. Parse merchant tags into category, revenue segment and take rate; apply a versioned category map.
4. Resolve fraud-source duplicates at their native daily grains; apply the approved no-threshold propagation rule; prove joins do not change transaction row count.
5. Handle merchant referential gaps using an explicit scenario approved for ranking.
6. Validate `state + four-digit postcode`; attach POA attributes while retaining match status and source version.
7. Flag monetary tails and calendar events; compare robust feature alternatives without altering raw values.
8. Produce curated merchant-level aggregates after all readiness gates pass.

## Implemented rules and retained alternatives

| Area | Implemented v1 rule | Alternatives for later sensitivity | Evidence |
|---|---|---|---|
| Unknown merchants | Retain and mark `merchant_master_status=missing`; set `candidate_eligible=false`. | Exclude orphan rows or recover a master record. | 396 merchants; 580,830 retained orders. |
| Consumer fraud duplicates | Remove exact duplicate rows at `user_id × date`; fail on conflicting probabilities. | Define an aggregation only if a future source contains conflicts. | 99 duplicates removed; 34,765 unique daily rows. |
| Fraud label | Preserve probabilities and presence flags; no threshold and no order deletion. | Exclude, flag, or down-weight in a named ranking scenario. | Transaction row count unchanged; 84,002 orders match either signal. |
| Geography missing | Keep features null and retain explicit unmatched or unavailable reason. | Broader geography only with a defensible crosswalk. | 416,334 matched with POA features; 83,035 absent nationally; 484 state mismatches; 146 POA feature gaps. |
| Multi-SA2 | No SA2 assignment in the primary pipeline. | Weighted, explicitly labelled sensitivity analysis. | Primary output contains POA only. |
| Category | Casefold, trim and collapse whitespace after strict parsing. | Versioned manual overrides if reviewed later. | 971 variants map to 25 labels with zero parse failures. |
| Dollar tails | Retain raw; add `log1p`, exact P99 and P99.9 flags. | Winsorise only in a named model scenario. | Raw sum/row count preserved; thresholds in run manifest. |

## Non-negotiable controls

- Raw bytes and raw columns remain unchanged.
- All row-affecting operations report input/output counts and key uniqueness.
- A left join must prove cardinality at the intended target grain.
- Nulls created by enrichment are measured, labelled and never silently imputed.
- External attributes stay at POA grain until a separate versioned feature build.

