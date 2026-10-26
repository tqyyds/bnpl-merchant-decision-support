# Raw Schema Dictionary

Observed types describe the untouched source. Target types are contracts for the later cleaning phase and are not implemented here.

## Transactions

Grain: one row per `order_id`; date from partition member path.

| Field | Observed | Target | Rules / notes |
|---|---|---|---|
| `user_id` | integer | string or nullable integer foreign key | All 24,081 transacting users match the mapping table. |
| `merchant_abn` | integer | 11-character string | Synthetic identifier only; zero-pad for representation, never ABR-enrich. |
| `dollar_value` | double | positive AUD float | Positive but extremely right-skewed; preserve full precision and flag long tail. |
| `order_id` | string | UUID string | Candidate primary key; all observed values are valid UUIDs and unique. |
| `order_datetime` | partition text | date | Parse only from the partition path; validate against the registered range. |

## Consumers (`tbl_consumer.csv`)

Grain: one row per `consumer_id`. The file is pipe-delimited despite the `.csv` extension.

| Field | Observed | Target | Rules / notes |
|---|---|---|---|
| `name` | text | text | Personal data; exclude from analytical outputs unless essential. |
| `address` | text | text | Personal data; no geocoding is authorised. |
| `state` | text | controlled string | Use with zero-padded postcode; retain invalid/unmatched status. |
| `postcode` | integer-like | 4-character string | Zero-pad only as a comparison field; do not silently impute. |
| `gender` | text | categorical | Inspect vocabulary before modelling; do not infer missing categories. |
| `consumer_id` | integer | stable identifier | Candidate primary key. |

## User mapping (`consumer_user_details.parquet`)

Grain: one row per mapping. `user_id` and `consumer_id` are both unique; observed relationship is strictly one-to-one across 499,999 rows.

## Merchants (`tbl_merchants.parquet`)

Grain: one row per `merchant_abn`. The identifier is stored as the Parquet/pandas index.

| Field | Observed | Target | Rules / notes |
|---|---|---|---|
| `merchant_abn` | integer index | 11-character string | Candidate primary key; synthetic. |
| `name` | text | text | Merchant display name. |
| `tags` | text representation of tuple/list | structured category, segment, take-rate | Four bracket styles exist. Parse explicitly; normalise case/spacing with a reviewed mapping. |

## Fraud tables

| Table | Grain / candidate key | Fields | Constraint |
|---|---|---|---|
| Consumer fraud | `user_id × date` | `user_id`, `order_datetime`, `fraud_probability` | 99 exact duplicate key rows exist. Probability is 0–100. Never join as an order-level label without deduplicating/aggregating and measuring expansion. |
| Merchant fraud | `merchant_abn × date` | `merchant_abn`, `order_datetime`, `fraud_probability` | Daily merchant signal, not order grain. Nineteen identifiers are absent from the merchant master but occur in transactions. |

## External target fields

All derived fields remain at POA grain until a downstream feature table is deliberately built: population; share aged 18–39; household income distribution and median household income; labour-force participation and unemployment; IRSD score/decile; IRSAD score/decile; source version; and `geo_match_status`. Exact source columns and formulas are fixed in `external_feature_dictionary.md`.
