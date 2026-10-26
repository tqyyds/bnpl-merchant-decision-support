# Architecture and engineering decisions

## Data foundation

The v1.2 ETL validates registered source sizes and SHA-256 hashes, separates raw, staging and curated layers, and writes partitioned transaction tables. It preserves unknown merchant/geography states, removes exact duplicate fraud observations and keeps tail values explicit rather than silently clipping them. Source and output manifests make historical runs inspectable.

Rolling snapshot v3 uses 90 historical days to construct features and a separate next-28-day label. Six training cutoffs precede three validation cutoffs and eight test cutoffs. Preprocessing is fitted on training data. Predictors and labels use separate loading paths. The revenue input contract defines 30 tabular fields and six daily sequence channels.

## Seven decision components

| Component | Implementation | Boundary |
|---|---|---|
| Eligibility | Master membership, activity, valid take rate, explicit dispositions | Historical rules do not prove contractual onboarding |
| Revenue | Run rates, Ridge, HGB and causal TCN | Predicts take-rate income proxy, not profit |
| Confidence | Temporal OOF empirical error intervals and reliability diagnostics | Historical calibration is insufficient in some bins |
| Risk | Native observations, missingness, coverage, recency and review prompts | No validated expected-loss model; unknown stays unknown |
| Diversification | Category/catchment shares, HHI, entropy and marginal concentration | Consumer geography is not merchant location |
| Strategic fit | Dated, owned MCDA policy interface | Neutral when unconfigured |
| Portfolio | Binary SciPy MILP with sequential revenue, cardinality and ID objectives | Saved optimality and constraints must be checked before export |

Source entry points: [`engines/train.py`](../engines/train.py), [`engines/system.py`](../engines/system.py), [`engines/portfolio.py`](../engines/portfolio.py), [`src/bnpl_analysis/time_split.py`](../src/bnpl_analysis/time_split.py).

The historical run does not activate the optional future risk-loss constraints. The separate course fraud proxy is an offline research extension; it is not integrated into the public demo or certified as real operational fraud probability.

## Dashboard boundary

```text
Saved engine outputs → schema/hash/lineage adapter → Dashboard API 1.0 → browser UI
Synthetic demo.json ────────────────────────────────────────────────────→ browser UI
```

The dashboard reads outputs without training or executing engines. Required joins use merchant ID and cutoff, invalid contracts fail explicitly, and missing outputs never silently switch to demo data. A shared versioned Risk binding reconciles displayed evidence across portfolio and diversification views. This establishes dashboard consistency, not proof that producer algorithms consumed Risk.

The optional Python bridge binds to loopback, serves an allow-list of static files and projected fields, rejects foreign Host headers and prevents spreadsheet formula execution in exported text. The static synthetic demo requires no backend dependencies.

## Historical reproducibility

Current source and historical execution are distinct. The retained audit identifies a changed portfolio source file relative to the historical freeze. Public aggregates describe the saved run, while automated tests check the published source using synthetic fixtures. A new end-to-end run requires authorised inputs and a new immutable run ID.

Detailed historical records remain under [`docs/analysis/`](analysis/) and [`dashboard/INTEGRATION.md`](../dashboard/INTEGRATION.md). Their dated scope statements should be interpreted in their original development context; this document and the root README describe the public edition.
