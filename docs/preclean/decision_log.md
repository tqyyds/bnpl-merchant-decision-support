# Decision Log

| Date | Decision | Rationale | Consequence |
|---|---|---|---|
| 2026-09-03 | Replace the prior real-estate project without a legacy backup; retain `.git`. | Explicit user direction. | Tracked history remains recoverable from Git; untracked old files were not backed up. |
| 2026-09-03 | Keep course raw data locally under `tables/raw/course` and ignore it in Git. | Course redistribution terms are unspecified. | Manifest and retrieval instructions are the committed provenance layer for course data. |
| 2026-09-03 | Track the eight official public external files under `tables/raw/external`. | The repository owner explicitly requested publication to the group GitHub repository; every file is below GitHub's 100 MB per-file limit. | External bytes, manifest and retrieval script are versioned; course ZIPs remain excluded. |
| 2026-09-03 | Use 2021 POA as the primary geography. | Consumer data supply state/postcode, and forced SA2 assignment would be ambiguous for 35.75% of consumers. | Primary demographic/SEIFA features remain POA-level. |
| 2026-09-03 | Restrict SA2 data to sensitivity analysis. | Coding indexes show postcode-to-SA2 is not one-to-one. | Any SA2 allocation requires weights and explicit uncertainty labels. |
| 2026-09-03 | Treat `merchant_abn` as a synthetic identifier and reject ABR linkage. | Only 40/4,026 master values pass the ABN checksum, near the random rate. | No real-business identity or ABR enrichment is permitted. |
| 2026-09-03 | Treat amount extremes and Black Friday volume as flags, not deletion grounds. | Long tails and event peaks may be economically valid. | Outlier treatment requires downstream sensitivity evidence. |
| 2026-09-03 | Do not create cleaned/curated data in this phase. | Explicit phase boundary. | Rules are specified but remain unapplied. |
| 2026-09-03 | Implement cleaning policy v1 after completion of the pre-clean phase. | Explicit user direction to apply the five proposed defaults. | Staging and curated outputs are generated locally and independently validated. |
| 2026-09-03 | Preserve all 14,195,505 orders and all raw dollar values. | Unknown merchants, fraud signals and long tails are analytical states rather than automatic deletion grounds. | Orders receive status/probability/log/quantile fields; no order is removed. |
| 2026-09-03 | Candidate eligibility requires a merchant-master record. | Take rate/category/name cannot be defensibly recovered for the 396 orphan merchants. | 4,026 of 4,422 transacting merchants are eligible for downstream ranking. |
| 2026-09-03 | Treat fraud probability as a daily signal without a v1 threshold. | The source is not order-grain and the course leaves threshold/application open. | Exact duplicate source rows are removed; presence/probability fields propagate without join expansion. |
| 2026-09-04 | Accept cleaning policy and ETL run v1.1 as the validated baseline. | Validation showed that valid POA assignments can still lack Census or SEIFA features, so match status must distinguish geography failure from feature unavailability. | Downstream work must use `geo_match_status` and `seifa_match_status`; v1 is superseded by v1.1. |
