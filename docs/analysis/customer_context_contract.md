# Customer context and candidate status contract v1

Grain: one merchant master record × cutoff. Every one of the 4,026 master merchants remains
present, including no-history candidates. The 396 IDs absent from the master are separately
exported as `unresolved_missing_master`; no take rate is invented for them.

## Candidate status and observation history

| Field | Definition | Missingness / use |
|---|---|---|
| `candidate_status` | `active_history`: at least one order within the inclusive prior 90 days; `inactive_recent_window`: first observed before cutoff but no order within 90 days; `no_observed_history`: no order observed by cutoff | No-history does not prove the merchant is newly incorporated or newly onboarded |
| `candidate_eligible_for_primary_model` | True only for active-history master merchants | Primary model excludes missing-master/no-recent-history cases; delivery preserves their disposition |
| `first_observed_order_asof` | Earliest source order date, only if <= cutoff; future first dates are masked | Unknown if never observed by cutoff; source begins 2021-02-28 and is left-censored |
| `hist_days_since_first_observed_order` | Cutoff minus the as-of first observed date | Not actual business age; supplemental evidence, outside the frozen 46 primary predictors |

## Customer residence coverage and concentration

Only historical orders between cutoff-89 and cutoff are used. Orders are collapsed to one
merchant/consumer pair with summed GMV. Distinct-customer weights therefore do not count repeated
orders multiple times. Positive raw order amounts make GMV weights nonnegative.

| Fields | Formula / interpretation |
|---|---|
| `ctx_observed_customers` | Distinct observed consumers in the historical window |
| `ctx_geo_customer_coverage`, `ctx_geo_gmv_coverage` | Customer/GMV share with `geo_match_status=matched_poa` |
| `ctx_seifa_customer_coverage`, `ctx_seifa_gmv_coverage` | Customer/GMV share with `seifa_match_status=matched` |
| `ctx_customer_state_gmv_hhi`, `ctx_customer_poa_gmv_hhi` | Sum of squared area GMV shares among POA-matched customers; unmatched GMV is excluded and coverage shown separately |
| `ctx_customer_state_count`, `ctx_customer_poa_count` | Number of distinct matched customer states / POAs |
| `ctx_dominant_customer_state` | Largest matched customer-state GMV; ties resolved alphabetically by state |

No-customer coverage is null, not zero. Counts are zero for no matched areas; concentration is null
when there is no matched GMV. State/postcode describe customer residence, not merchant premises.

## Area background fields — descriptive only

For each of the following source attributes, compute three fields:

- `ctx_<attribute>_customer_mean`: equal weight per distinct observed consumer with a usable value.
- `ctx_<attribute>_gmv_mean`: weighted by that consumer's historical merchant GMV, with the denominator
  restricted to consumers with a usable value.
- `ctx_<attribute>_customer_coverage`: consumers with a usable value / all observed consumers.

| Attribute | Cleaned source field | Unit / limitation |
|---|---|---|
| `area_household_income` | `median_household_income_weekly_aud` | AUD/week; mean of area household-income medians, not actual customer income or a pooled household median |
| `area_age18_39_share` | `population_18_39_share` | Fraction [0,1] in the customer's area; not individual age |
| `area_irsd` | `irsd_score` | Area disadvantage index, not personal credit risk |
| `area_irsad` | `irsad_score` | Area advantage/disadvantage index, not personal credit risk |

`ctx_reference_year=2021` describes the statistical vintage. `ctx_historical_availability_verified=false`
states that publication-time availability at the simulated cutoff has not been established. All `ctx_`
fields and the supplemental tenure/status fields remain outside the primary predictor allow-list.
They can support descriptive explanations, coverage review and a separately approved future experiment.
Provenance, source/version and file hashes are recorded in the context manifest.

No arbitrary aggregate risk or confidence score has been invented. Observation volume, recency,
active-day rate and coverage provide inspectable evidence; choosing a composite decision policy
belongs to the next ranking/training plan. No model is fitted by context construction.
