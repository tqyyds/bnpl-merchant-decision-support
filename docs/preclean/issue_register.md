# Data Quality Issue Register

| ID | Severity | Issue and evidence | Affected use | Required decision / acceptance test | Status |
|---|---|---|---|---|---|
| I-001 | High | Part-4 label ends 2022-08-28; actual partitions end 2022-10-26. | Time windows, reproducibility | Parse dates from members; assert 606 consecutive dates and registered maximum. | Resolved in v1 |
| I-002 | High | 396 merchants missing from master; 580,830/14,195,505 rows (4.09%). | Merchant ranking and take-rate revenue | Retain and flag; exclude from candidate eligibility without deleting orders. | Resolved in v1 |
| I-003 | High | 99 exact duplicate consumer `user_id × date` fraud rows. | Fraud joins | Remove exact duplicates; fail on conflicting probabilities; assert native key. | Resolved in v1 |
| I-004 | High | Fraud records are daily entity signals, not order labels; direct joins expand to 80,348 consumer-side and 4,059 merchant-side order matches. | Fraud filtering/flagging | Preserve probability/presence fields and transaction cardinality; apply no threshold. | Mitigated in v1; ranking sensitivity remains |
| I-005 | Medium | 971 raw category variants and four bracket styles reduce to 25 normalised categories. | Category features | Strict parser and versioned crosswalk; fail on parse errors. | Resolved in v1 |
| I-006 | Medium | Highly right-skewed dollar values; max $105,193.89, P99 $1,619.27, 112,368 under $1. | Revenue, outliers | Preserve raw, add `log1p` and exact quantile flags; no capping/deletion. | Resolved in v1; rank sensitivity remains |
| I-007 | High | 83,519 consumers (16.70%) do not match official state/postcode; 178,751 (35.75%) are multi-SA2. | Demographic enrichment | Keep explicit null/status; POA primary; perform no SA2 assignment. | Resolved for primary v1.1 |
| I-008 | Critical | Synthetic merchant IDs resemble ABNs but 99.01% fail checksum. | External business enrichment | Reject ABR linkage; rename semantics in analytical layer. | Resolved policy |
| I-009 | Medium | Only 24,081 of 499,999 mapped users transact in the observed period. | Population interpretation | Merchant aggregates use observed transacting users; the consumer dimension retains all registered consumers. | Resolved in v1 grain definitions |
| I-010 | Low | Black Friday 2021 produces the highest daily volume. | Outlier detection | Retain event; calendar-event features remain downstream. | Documented |
| I-011 | Medium | 146 state/postcode matches lack 2021 Census POA features; another 2,693 matched POAs lack a usable SEIFA score. | Demographic and socioeconomic enrichment | Distinguish `poa_feature_unavailable` from invalid geography and `poa_score_unavailable` from unmatched geography; leave affected features null. | Resolved in v1.1 |

No issue in this register authorises modification of raw files.

