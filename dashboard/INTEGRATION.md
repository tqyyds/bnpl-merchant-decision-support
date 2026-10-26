# Seven-engine product integration

Updated 5 October 2026 (Australia/Sydney). The selected source is the sibling
`ads project 2-engines` checkout, saved run `seven_v1_20260906`.

## Product scope

The product runs the complete **saved-output integration and replay** workflow:
discover → validate → normalise → bind shared Risk → reconcile saved scenarios →
inspect merchant evidence → export. It preserves `mockup.html` and every engine file.
It does not train or execute engine algorithms. No frontend penalty, re-ranking or
onboarding decision is introduced. Here “profile” refers to the existing Portfolio engine.

| Engine | Evidence in the product | Integration role |
|---|---|---|
| Eligibility | Eligibility, disposition, supplied reasons | Governs the candidate/revenue universe |
| Revenue | Merchant 28-day estimate, historical revenue, model | Commercial baseline and saved selection totals |
| Confidence | Intervals, reliability, source actions when present | Review only; source acceptance remains visible |
| Risk | Native signals, coverage, recency, source review flags | One `risk-evidence-v1` binding for both consumers |
| Diversification | Merchant marginal HHI, activity composition, count/revenue HHI | Risk evidence by activity and course group |
| Strategic Fit | Source state and score | Saved business preference evidence; NOT_CONFIGURED stays null |
| Portfolio | Saved membership/ranks, solver status, scenario comparisons | Selected Risk evidence plus constraint execution status |

Arrows for Risk → Diversification and Risk → Portfolio describe the **integration
layer's evidence consumers**. They do not attest that either producer algorithm imported
Risk. Current saved outputs do not attest Risk constraint execution, so the API returns
`NOT_ATTESTED_BY_ENGINE`. Real Risk-driven optimisation needs engine-side policy,
feasibility and solver provenance, introduced in a future producer/adapter version.

## Shared Risk contract

`risk_interface.py` constructs a binding from contract version, saved run, window,
cutoff, Risk engine versions and the exact Risk parquet SHA-256. Every merchant and
both downstream consumers carry that same binding ID. Missing Risk rows remain unknown.
Native signals and coverage are fractions; recency is in days. No expected-loss AUD
or calibrated fraud probability is invented. Group evidence never becomes an individual
Risk score. Native evidence observed means a supplied native signal exists or source
coverage is positive; it does not mean complete or validated evidence.

The selected portfolio summary reconciles observed + unknown to selected count.
Activity and course-group breakdowns preserve denominators. Source review prompts
are separate from missing evidence. Revenue-with-evidence share describes commercial
exposure with any native evidence, not expected loss. Scenario comparisons use the same
Risk binding for every saved shortlist.

## Independent output registration

Two adapters share Dashboard API 1.0:

1. `seven-engine-files-v1` reads existing saved run folders unchanged.
2. `engine-bundle-v1` reads independently located parquet files from a dashboard-owned
   manifest. It supports paths and column renames with unchanged canonical semantics.

To generate a working configuration from an existing saved run, without writing into
the engine checkout:

```powershell
python scripts/create_dashboard_bundle.py --engine-root '../ads project 2-engines' --run seven_v1_20260906 --output dashboard/.local/registered-engine-config.json
python scripts/verify_dashboard_connection.py --engine-root '../ads project 2-engines' --config dashboard/.local/registered-engine-config.json
python -m dashboard.server --engine-root '../ads project 2-engines' --config dashboard/.local/registered-engine-config.json
```

The generator refuses to overwrite an existing config. Use another output name when
registering a new release. It records the checkout commit for identification; commit
identity alone does not prove which code produced an old artifact. File hashes are the
integrity authority. Local manifests contain paths/hashes and stay under ignored `.local`.

The configuration has a `bundles` array. Each bundle requires:

- `schema_version: engine-bundle-v1`, unique `run`, `snapshot_id`, `source_commit`;
- `windows` keyed by `latest`, `test`, or `validation` with `cutoffs`, `scenarios`;
- `outputs` keyed by canonical table names in `adapter.py`;
- each output's relative `path`, `sha256`, `engine_version`, matching `snapshot_id`,
  and optional `columns` mapping canonical names to source column names;
- source-supplied `solver_audit`, and source `revenue_model`/`confidence_acceptance`
  where available. Missing solver proof disables export.

Required tables are predictions, revenue, eligibility, candidate_dispositions and
portfolios. Optional engine tables may be omitted and stay unknown; a declared missing
or invalid output fails. Paths cannot escape the engine root. Hash/version mismatches,
duplicate keys and incompatible joins fail before results are displayed. A canonical
portfolio row needs explicit scenario and rank. A native file that omits either is not
silently reconstructed as a valid selection.

`engine-bundle-v1` deliberately does not import evaluation JSON: a future adapter must
validate its own evaluation lineage first. The legacy adapter retains its validated
outcome comparisons. Bundle views visibly disclose unavailable evaluation.

## Latest producer formats and remaining boundary

The repository's newer independent E/R/C/D/Strategy/Portfolio outputs are not assumed
compatible merely because their filenames exist. New status semantics, missing course
groups, omitted scenario/rank keys and aggregate-only Risk reports require an explicit
normaliser/producer contract. Neither reports from different dates nor GAM aggregate
metrics are substituted for missing merchant-level Risk evidence. This implementation
fully exercises the selected saved seven-engine source and offers an independently
located file registration contract; it does not claim the newer independent producers
have all completed a new coherent run.

## Reproduction and acceptance

```powershell
python -m pytest -q
node --test tests/test_dashboard_client.mjs
python scripts/verify_dashboard_connection.py --engine-root '../ads project 2-engines'
```

The replay checks every saved date/scenario, membership, estimated revenue, shared Risk
binding, source consistency and preservation of engine code/notebooks/artifacts. Synthetic
tests exercise independent output registration, missing/modified files, wrong lineage,
unsafe paths, column renames, HTTP endpoints and frontend transport/render semantics.
Browser acceptance covers Risk scope, Confidence review, scenario drill-through,
merchant detail, source switching, exports and responsive layouts. Results are recorded
in `VERIFICATION.md`; successful replay is not validation of model performance.

## Audit boundary — 5 October 2026

See [the engine audit](ENGINE_AUDIT_2026-10-05.md). Current Risk bindings attest shared
Dashboard evidence only. They do not attest consumption by producer algorithms.
Native-evidence schema rejects proxy-only Risk outputs; a separate semantic adapter is
required for GAM. Bundle lineage is dashboard-declared, not independently attested by
the producers. Historical freeze code drift is exposed alongside saved-output status.
