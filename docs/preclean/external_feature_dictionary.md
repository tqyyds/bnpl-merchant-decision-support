# External Feature Dictionary v1.0.0

This allow-list prevents post-hoc variable selection and mixed Census populations. It defines future features only; no feature table is created in this phase.

## Join and lineage fields

| Output field | Source / formula | Type | Validation |
|---|---|---|---|
| `poa_code_2021` | Four-character consumer postcode validated against `POA_CODE_2021` / `POA_CODE21` | string | Preserve leading zero; one row per POA in every selected table. |
| `geo_match_status` | `matched_poa`, `postcode_absent_nationally`, `state_postcode_mismatch`, or `poa_feature_unavailable` | category | Never convert unmatched/unavailable to matched through imputation. |
| `seifa_match_status` | `matched`, `poa_score_unavailable`, or `not_geo_matched` | category | Distinguish a valid POA with no published score from geography failure. |
| `geo_reference_year` | constant `2021` | integer | Must equal source vintage. |
| `geo_source_version` | manifest version plus source SHA-256 identifiers | string | Required on every derived export. |

`state + postcode` is validated through the 2022 locality-to-2021-SA2 coding index. POA code itself is postcode-like, but POA is an ABS approximation rather than an exact postal boundary.

## 2021 Census GCP POA allow-list

Archive member prefix: `2021 Census GCP Postal Areas for AUS/`.

| Output field | Member / source columns | Formula and population |
|---|---|---|
| `population_persons` | `2021Census_G01_AUST_POA.csv`: `POA_CODE_2021`, `Tot_P_P` | Direct count of persons. |
| `population_18_39_share` | `2021Census_G04A_AUST_POA.csv`: `Age_yr_18_P`, `Age_yr_19_P`, `Age_yr_20_24_P`, `Age_yr_25_29_P`, `Age_yr_30_34_P`, `Age_yr_35_39_P`; G01 `Tot_P_P` | Sum the six mutually exclusive person-age counts and divide by `Tot_P_P`. Null if denominator is zero; assert result in `[0,1]`. |
| `median_household_income_weekly_aud` | `2021Census_G02_AUST_POA.csv`: `Median_tot_hhd_inc_weekly` | Direct published median; household concept, AUD/week. |
| `household_income_distribution` | `2021Census_G33_AUST_POA.csv`: `Negative_Nil_income_Tot`, every `HI_*_Tot` stated-income band from `HI_1_149_Tot` through `HI_4000_more_Tot` | Retain counts and optionally divide each by the sum of stated bands. Do not include `Partial_income_stated_Tot` or `All_incomes_not_stated_Tot` in a stated-income denominator; report their shares separately. |
| `labour_force_participation_pct` | `2021Census_G43_AUST_POA.csv`: `Percnt_LabForc_prticipation_P` | Direct published percentage for persons; validate using `lfs_Tot_LF_P` and `P_15_yrs_over_P`. |
| `unemployment_pct` | G43: `Percent_Unem_loyment_P` | Direct published percentage for persons; validate using `lfs_Unmplyed_lookng_for_wrk_P / lfs_Tot_LF_P`. |

The `_P` suffix denotes persons. Male/female columns are not allow-listed for the initial feature layer. Counts may be randomly adjusted by the ABS and derived ratios can differ slightly from displayed published percentages.

## SEIFA 2021 POA allow-list

Workbook sheet `Table 1`, header rows 5–6, columns A–E only:

| Output field | Column interpretation | Rule |
|---|---|---|
| `poa_code_2021` | 2021 Postal Area code | Read as four-character string. |
| `irsd_score` | Index of Relative Socio-economic Disadvantage — Score | Area-level score. |
| `irsd_decile` | IRSD — Decile | Integer 1–10 where available. |
| `irsad_score` | Index of Relative Socio-economic Advantage and Disadvantage — Score | Area-level score. |
| `irsad_decile` | IRSAD — Decile | Integer 1–10 where available. |

SEIFA describes areas, not people. Do not interpret a consumer as personally advantaged/disadvantaged because of POA.

## Geometry and sensitivity

- POA geometry key: `POA_CODE21`; GDA2020; maps and coverage checks only.
- SA2 geometry key: `SA2_CODE21`; GDA2020; sensitivity only.
- 2022 coding-index fields: `POSTCODE`, `STATE`, `SA2_MAINCODE_2021`. Multiple SA2 values per `state + postcode` must remain one-to-many.
- Regional Population key: SA2 code × year; use 2021/2022 only in a named sensitivity scenario.

## Context sources

RBA CPS 2022 and ASIC REP 672 contribute citations and aggregate context only. They expose no fields to the merchant feature layer.
