# BNPL Cleaning ETL v1.2

The v1.2 pipeline implements the existing five policies plus a consumer source-field allow-list
in `config/cleaning_v1.json`. It never modifies `tables/raw`.

## Run

```powershell
python -m src.bnpl_etl.cli --validate-sources-only
python -m src.bnpl_etl.cli --run-id v1_2
python scripts/validate_etl_outputs.py --run-id v1_2
pytest -q
```

The pipeline refuses to overwrite complete or interrupted local runs. Use a new run ID for a
new source/policy version. Committed reference manifests do not reserve local run IDs. Actual
manifests are under `reports/etl/runs/`, with accepted references outside that runtime directory.

## Outputs

- `tables/staging/v1_2/transactions/order_datetime=YYYY-MM-DD/part-00000.parquet`: 606 cleaned daily order partitions.
- `tables/staging/v1_2/consumers.parquet`: consumer ID/state/postcode and approved derived geography/SEIFA fields; no name/address/gender.
- `tables/staging/v1_2/merchant_master.parquet`: parsed master merchants.
- `tables/staging/v1_2/merchant_category_crosswalk.parquet`: auditable 971-to-25 mapping.
- `tables/staging/v1_2/fraud/*.parquet`: daily fraud signals after exact deduplication.
- `tables/staging/v1_2/poa_features.parquet`: versioned POA feature table.
- `tables/curated/v1_2/merchant_features.parquet`: one row for every transacting merchant, with eligibility and aggregate evidence.
- `reports/etl/runs/v1_2_manifest.json`: actual source/policy/count/provenance and output-hash evidence.
- `reports/etl/v1_2_manifest.json`: committed accepted reference; never used as a run reservation.

## Implemented policies

1. Unknown merchants remain in the order fact with `merchant_master_status=missing`; their merchant feature rows have `candidate_eligible=false`.
2. Exact duplicate consumer-day fraud rows are removed. Conflicting duplicates fail the run. Probabilities and presence flags are retained; no threshold deletes transactions.
3. Postcodes are four-character strings. Unmatched/state-mismatched consumers remain present with null POA features and explicit `geo_match_status`. No SA2 allocation occurs.
4. Tags are parsed into category, revenue level and take rate. Category strings are case-folded, trimmed and whitespace-collapsed through a versioned crosswalk.
5. Raw dollar values are unchanged. The pipeline adds `log1p`, P99 and P99.9 flags using exact full-dataset quantiles; it does not cap or delete values.
6. Consumer source fields are allow-listed before enrichment; raw archives remain complete and local.

## Hard gates

- All registered sources must match manifest byte sizes and SHA-256.
- Transaction schema, positivity, row count, date continuity and order-key hashes must match the audited baseline.
- Joins declare cardinality; transaction input/output row counts must match.
- Geography and merchant referential counts are asserted against the audited baseline.
- A run is complete only when both `_SUCCESS` markers and the ETL manifest exist.
