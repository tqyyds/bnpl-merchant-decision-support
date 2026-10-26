# Cleaning Readiness Checklist

## Completed pre-clean controls

- [x] Course requirements separated into mandatory, recommended, administrative and phase-scope items.
- [x] Four course ZIPs stored locally, CRC-tested, hashed and inventoried.
- [x] All 14,195,505 transactions scanned; 606 partitions and date continuity verified.
- [x] Candidate keys, UUID format, nulls, duplicates, domains and foreign-key coverage measured.
- [x] Fraud grain and join multiplication quantified.
- [x] Merchant-tag variation and parsing risk quantified.
- [x] Official period-matched POA, Census and SEIFA sources acquired and registered.
- [x] ASGS/SA2 sensitivity sources acquired and registered.
- [x] RBA and ASIC context sources acquired and constrained to narrative use.
- [x] Raw contract, manifest schema, issue register and cleaning specification versioned.
- [x] Permitted Census/SEIFA source columns and POA-level formulas fixed in an external feature dictionary.
- [x] Audit notebook executed from a clean kernel without modifying `tables/raw`.

## Approved cleaning decisions

- [x] Unknown merchants retained and flagged; only the 4,026 master merchants are candidate-eligible in v1.
- [x] Exact consumer-fraud duplicates removed at daily grain; probabilities/presence propagated without applying a threshold or deleting orders.
- [x] Geography missingness retained explicitly; POA is primary and no SA2 allocation occurs in v1.
- [x] Versioned parser/crosswalk maps 971 raw merchant-category variants to 25 normalised values.
- [x] Raw amounts retained; v1 adds `log1p`, P99 and P99.9 flags without winsorisation or deletion.
- [ ] Confirm whether the restricted course ZIPs must ever be submitted remotely; official public external files are already approved for GitHub publication.

## Cleaning acceptance gates

- [x] Manifest hashes and schemas match before the v1 run.
- [x] Fraud native keys are unique before transaction joins.
- [x] Every join declares expected cardinality and preserves/asserts target row count.
- [x] Unknown and unmatched statuses are explicit—not imputed silently.
- [x] The only v1 row removal is 99 exact fraud-source duplicates; no order is removed, filled, capped or thresholded.
- [x] Curated merchant output has a unique merchant key, feature lineage and coverage report.

**Readiness verdict:** v1.1 cleaning is implemented and independently validated. The remaining open item concerns only whether restricted course ZIPs may be submitted remotely.
