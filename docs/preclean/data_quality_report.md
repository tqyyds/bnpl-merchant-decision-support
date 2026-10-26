# Raw Data Quality Report

## Executive assessment

The raw data are suitable for controlled cleaning and exploratory merchant analysis, but they are **not yet safe for direct modelling or merchant ranking**. The most material risks are merchant referential gaps, fraud-grain mismatch, geography non-coverage, ambiguous category syntax, and the part-4 date-label mismatch. Transaction completeness and order-key integrity are strong.

## Scope and method

The audit reads all four course ZIPs without extraction, validates ZIP CRC and SHA-256, profiles every source table, and scans every transaction partition. Comparisons use in-memory fields only. External files are verified for publisher origin, download integrity, container structure, reference period and geography key. Counts below are deterministic audit results; the executable evidence is in `notebooks/01_raw_data_audit.ipynb`.

## Findings

| ID | Dimension | Evidence | Assessment | Cleaning implication |
|---|---|---|---|---|
| DQ01 | Completeness | 14,195,505 transactions across 606 consecutive daily partitions, 2021-02-28–2022-10-26; no null transaction fields. | Strong | Assert exact row and date baselines. |
| DQ02 | Key validity | All `order_id` values parse as UUID and no duplicates were found; mapping is 499,999-row one-to-one. | Strong | Preserve keys; fail on future duplicates. |
| DQ03 | Package metadata | Part-4 folder label claims an end date of 2022-08-28, but members continue through 2022-10-26. | High metadata risk | Trust member paths after validation; document discrepancy. |
| DQ04 | Merchant FK | Transaction data contain 4,422 merchants versus 4,026 in the master. 396 unknown IDs account for 580,830 rows (4.09%). | High | Choose explicit unknown-merchant policy; never silently inner-join. |
| DQ05 | Fraud grain | 34,864 consumer-fraud rows include 99 exact duplicate `user_id × date` rows. Unique consumer signals match 80,348 orders (max 11 orders/key). Merchant signals match 4,059 orders (max 535/key); 405 orders match both. | High | Resolve duplicates and define daily-to-order semantics before joining. |
| DQ06 | Category consistency | 971 case/spelling variants collapse to 25 normalised categories; tags use four bracket styles. | Medium | Parse structured components and maintain an auditable mapping table. |
| DQ07 | Amount distribution | Median $62.23; P99 $1,619.27; maximum $105,193.89; all values positive, including 112,368 below $1. | Medium | Treat as long-tailed; flag/review, do not delete by default. |
| DQ08 | Geography coverage | 83,519 of 499,999 consumers (16.70%) fail official `state + postcode` matching. Of all consumers, 178,751 (35.75%) map to more than one SA2. | High | Retain unmatched status; POA primary; SA2 only weighted sensitivity. |
| DQ09 | Merchant identifier semantics | Only 40 of 4,026 master IDs (0.99%) pass the real ABN checksum, consistent with random numbers. | Critical misuse risk | Label synthetic; prohibit ABR lookup or real-business inference. |
| DQ10 | Temporal plausibility | Highest observed daily count is 61,237 on 2021-11-26, consistent with Black Friday. | Monitor, not defect | Retain event spike; add calendar context downstream. |

## External-source readiness

All eight registered external files downloaded successfully on 2026-09-03. ZIP CRC checks pass. POA and SA2 boundary archives contain `.shp`, `.dbf`, `.shx`, and `.prj`. The Census archive includes 129 files and POA tables. SEIFA and Regional Population workbooks expose the expected table sheets. RBA and ASIC PDFs open successfully (61 and 31 pages). These checks establish transport and structural integrity, not substantive feature correctness.

## Use-case safety

- Safe now: reproduce raw counts, audit schemas, quantify joins and cite aggregate context.
- Unsafe now: train/rank merchants, convert daily fraud probabilities to order labels, drop unknown merchants, infer real ABN identities, or assign a postcode deterministically to SA2.
- Safe after documented cleaning decisions: POA-level consumer enrichment and transaction/merchant aggregates with lineage and coverage metrics.

## Assumptions and residual uncertainty

The course data are synthetic; transaction partition paths are treated as authoritative dates; hash-based order-ID uniqueness is reinforced by UUID validation but should remain a regression test; POA approximates postal geography; and public-source licences must remain attached to redistributed derived outputs.

