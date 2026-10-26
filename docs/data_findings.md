# Findings from the supplied data

The four course ZIP files were inspected locally. No source or derived data from those archives is
stored in Git.

## Inventory

| Dataset | Observed scale or period | Relevance |
|---|---:|---|
| Merchant master | 4,026 merchants | Candidate universe, name, merchant tag, take rate |
| Consumer table and user mapping | 499,999 consumers/mappings | Customer state and postcode enrichment |
| Transaction snapshots | 14,195,505 orders | Merchant behaviour and future outcome |
| Transaction dates | 2021-02-28 to 2022-10-26 | Supports historical and later evaluation windows |
| Active transaction users | 24,081 users | Effective transacting customer population |
| Transaction merchant ABNs | 4,422 | Includes ABNs outside the merchant master |
| Consumer fraud file | 34,864 rows | Sparse observed risk signal through 2022-02-27 |
| Merchant fraud file | 114 rows | Very sparse merchant risk signal through 2022-02-27 |

## Material quality findings

- All 4,026 master merchants have transactions.
- 396 ABNs in the transaction data do not appear in the merchant master. They lack the master
  attributes needed for a normal candidate decision and should be quarantined for data resolution,
  not silently ranked.
- No duplicate transaction order rows were identified in the inspected snapshots.
- The consumer fraud file contains 99 duplicate user-date rows. A future implementation must define
  and document a deduplication rule.
- Fraud data ends on 2022-02-27, so it can be used as historical evidence but not as a later-period
  realised fraud outcome.
- Merchant tags combine industry, tier, and take rate in inconsistent text. Parsing rules and
  exception reporting are required.
- Transaction date is represented by the daily partition path rather than an ordinary column.
- Consumer names and street addresses are present but unnecessary for merchant prioritisation and
  should not enter curated analytical outputs.

## Proposed time design

| Window | Dates | Use |
|---|---|---|
| Historical feature window | 2021-02-28 to 2022-02-27 | Features, observed risk, and evidence coverage |
| Later evaluation window | 2022-02-28 to 2022-10-26 | Future GMV and take-rate revenue used only for validation |

This split prevents later transactions from leaking into predictors. In a production setting, the
same principle should be implemented with rolling cut-off dates.

## External data interpretation

The existing repository includes public ABS Postal Area context such as population, age, income,
and SEIFA indexes. These can summarise the areas from which a merchant's observed customers come.
They should be labelled **customer catchment context**, not merchant location, and should not be
used to infer an individual's socioeconomic status.

## Consequences for the product

1. The candidate list should start from the merchant master, with the 396 unmatched ABNs shown in a
   separate data-quality queue.
2. Missing fraud coverage must remain visible; missing is not the same as zero risk.
3. The later window should be protected as an evaluation set until model and feature choices are
   fixed.
4. Every dashboard recommendation should include its observation window, evidence coverage, and a
   human-review status.

