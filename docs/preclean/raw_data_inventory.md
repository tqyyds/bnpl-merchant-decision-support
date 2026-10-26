# Raw Data Inventory

## Course inputs

| Package | Logical content | Observed rows / partitions | Reference period | Integrity |
|---|---|---:|---|---|
| part 1 | consumers, user mapping, merchants, consumer fraud, merchant fraud | 499,999 consumers; 499,999 mappings; 4,026 merchants; 34,864 consumer-fraud rows; 114 merchant-fraud rows | Fraud dates and static master data | ZIP CRC pass; SHA-256 registered |
| part 2 | daily transaction Parquet files | 3,643,266 rows / 181 days | 2021-02-28 to 2021-08-27 | ZIP CRC pass; schema consistent |
| part 3 | daily transaction Parquet files | 4,508,106 rows / 184 days | 2021-08-28 to 2022-02-27 | ZIP CRC pass; schema consistent |
| part 4 | daily transaction Parquet files | 6,044,133 rows / 241 days | 2022-02-28 to 2022-10-26 | ZIP CRC pass; package directory label ends 2022-08-28 but content does not |

Across transaction packages there are 14,195,505 order rows and 606 continuous daily partitions. The date is encoded in the member path, not in Parquet columns.

## External inputs

| Tier | Dataset | Intended use | Grain / key | Do not use for |
|---|---|---|---|---|
| Primary | 2021 Census General Community Profile, POA | Population, age, income distribution, household-income median, labour force and unemployment features | POA / `POA_CODE_2021` | Merchant-level facts before a valid merchant location exists |
| Primary | SEIFA 2021, POA | IRSD and IRSAD score/decile | POA | Individual socioeconomic status |
| Primary | ASGS 2021 POA boundary, GDA2020 | Maps and POA validation | POA code | Exact legal postcode boundaries |
| Sensitivity | ASGS 2021 Coding Indexes | Validate `state + postcode`; identify one-to-many SA2 mappings | locality/postcode/state to SA2 | Deterministic postcode-to-SA2 assignment |
| Sensitivity | ASGS 2021 SA2 boundary, GDA2020 | SA2 sensitivity maps | SA2 code | Primary consumer join |
| Sensitivity | Regional Population 2021–22 | SA2 population sensitivity feature | SA2/year | POA production feature |
| Context | RBA 2022 Consumer Payments Survey | Narrative BNPL/payment benchmark | Survey respondent / published aggregate | Merchant feature or label |
| Context | ASIC REP 672 | Regulatory and industry context | Published aggregate | Merchant feature or label |

## Deferred or rejected

| Source | Disposition | Reason |
|---|---|---|
| ABS Counts of Australian Businesses / ANZSIC | Deferred | No reliable synthetic-merchant location and no defensible mapping from noisy merchant tags to official ANZSIC at this stage. |
| Australian Business Register lookup | Rejected | `merchant_abn` behaves like a synthetic numeric identifier: only 40 of 4,026 master values pass the ABN checksum, approximately the random pass rate. |

See `source_manifest.json` for byte-level provenance and `raw_schema_dictionary.md` for fields.

