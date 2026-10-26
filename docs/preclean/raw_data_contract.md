# Raw Data Contract v1.0.0

## Invariants

1. Raw files are immutable and live only under `tables/raw/course` or `tables/raw/external`.
2. Every input must have one manifest entry with publisher, landing/download URL, licence, reference period, retrieval date, local path, byte size, SHA-256, format, grain, candidate key and known limitations.
3. A checksum or schema change is a contract failure. Register a new manifest version; never silently accept drift.
4. The audit may construct comparison fields in memory but must not write to `tables/raw`.
5. No source is joined at a finer grain than it supports.

## Table contracts

- Transactions: one row per UUID `order_id`; daily partition path supplies `order_datetime`; `dollar_value > 0`; user and merchant identifiers are preserved.
- Consumers: one row per `consumer_id`; source delimiter is `|`.
- User mapping: strict one-to-one `user_id ↔ consumer_id`.
- Merchants: one row per synthetic `merchant_abn`; index must be materialised explicitly when read.
- Consumer fraud: `user_id × date` signal; duplicate source rows are a known violation that must be resolved before joining.
- Merchant fraud: `merchant_abn × date` signal; not an order label.

## Geography interface

Primary join key: `state + zero-padded postcode` to an official POA reference. Persist `geo_match_status`, match coverage, reference year and source version. POA is an ABS approximation of postcode geography and must be described as such. Never force a postcode to one SA2. SA2 results must be labelled sensitivity analysis and use documented weights where a postcode maps to multiple SA2s.

Permitted external fields and formulas are versioned in `external_feature_dictionary.md`. Adding a Census or SEIFA field is a contract change, not an ad hoc notebook choice.

## Target representations (not yet applied)

| Field | Target contract |
|---|---|
| `postcode` | exactly four characters, leading zeros retained |
| `merchant_abn` | exactly 11 numeric characters; synthetic ID label |
| `order_datetime` | calendar date |
| `dollar_value` | finite positive AUD float |
| `fraud_probability` | finite value in `[0, 100]` |

## Manifest JSON schema

The manifest root has `manifest_version`, `generated_at`, `raw_root`, and `sources`. Each source object requires: `id`, `publisher`, `title`, `tier`, `landing_url`, `download_url`, `license`, `reference_period`, `retrieval_date`, `local_path`, `file_size_bytes`, `sha256`, `format`, `grain`, `candidate_key`, `known_limitations`, and `integrity_status`.
