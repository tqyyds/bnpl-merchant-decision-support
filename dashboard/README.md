# Merchant Portfolio engine workspace

This front end is a **read-only integration window** for saved engine outputs. It never
imports, trains, optimises, rewrites or freezes engines. Engine-owned decisions remain
authoritative. The default source is the sibling `ads project 2-engines` checkout.

The original synthetic prototype is preserved at `mockup.html`. The new engine-connected
workspace has its own `index.html` entry point and does not replace the original page.

From this repository root:

```powershell
python -m dashboard.server
```

Open `http://127.0.0.1:8766/`. An alternative source can be selected at startup:

```powershell
python -m dashboard.server --engine-root '../ads project 2-engines' --port 8766
```

The server uses existing pandas/pyarrow dependencies and binds only to loopback. It serves
an explicit static-file allow-list and projected merchant fields; raw course files,
pickled models, unrestricted directories and consumer records are not HTTP-accessible.
It is a local course analysis tool, without a multi-user authentication/deployment layer.
CSV export creates a local browser download of the complete saved shortlist, with run,
cutoff, scenario and source fingerprint. Filters do not alter the recommendation.

## Screens

- Overview: engine-owned shortlist, estimated revenue, operating-activity mix, actual
  evaluated baseline comparison when supplied, and independent group Top-10 lists.
- Explorer: search, group/decision/confidence filters, stable sorting, 25-row pagination,
  and merchant evidence. A filtered-out selected merchant is replaced by a visible match;
  no matches clears the detail card.
- Connections: seven component statuses, output versions, file integrity, solver status
  and source caveats. Missing secondary outputs stay unknown. Latest recommendations
  never display realised revenue or evaluation metrics.
- Risk: observed/unknown native evidence, source review queue, activity coverage, and
  the same versioned Risk binding consumed by Diversification and Portfolio views.
- Confidence: source actions/bands, intervals and an inspection queue. An unaccepted
  engine keeps the whole selected shortlist in review, even if legacy bands are high.
- Scenarios: every saved scenario at the selected date, membership swaps, revenue cost,
  count/revenue HHI and Risk evidence coverage, reconciled to one source fingerprint.

Scenario controls select **saved engine scenarios**. There is no browser-side surrogate
optimiser. Risk prompts and confidence do not impose invented primary-selection rules.
The UI presents the source status `EVIDENCE_ONLY_NO_LOSS_LABELS` unchanged.

## Integration boundary

```text
Engine-owned output files → EngineAdapter → Dashboard API 1.0 → EngineClient → UI
```

`adapter.py` owns file locations, native columns, key checks and normalisation.
`api-client.js` owns transport and response-version validation. `app.js` only understands
the normalised DTO, so future engine changes do not have to propagate throughout the UI.

The adapter discovers runs under `artifacts/seven_engines/<run>/` and reads
`latest_system`, `test_system`, or `validation_system`. Required files are predictions,
portfolios, candidate_dispositions, revenue and eligibility parquet files. Secondary
confidence, risk, diversification, strategic_fit, portfolio membership and group_top10
files are optional. Present but invalid files fail explicitly. Missing files never cause
an automatic switch to demo data. Prediction-lock parquet hashes are checked when a lock
exists; absent locks are labelled unverified. This is parquet integrity verification, not
a claim that every JSON report, code file or original raw source was freeze-verified.

For a column rename, create a local configuration (or update `adapter-config.json`):

```json
{
  "adapter": "seven-engine-files-v1",
  "artifact_directory": "artifacts/seven_engines",
  "columns": {
    "revenue": {"prediction": "predicted_revenue_aud"},
    "predictions": {"prediction": "predicted_revenue_aud"}
  }
}
```

Pass it with `--config path/to/config.json`. Only the canonical allow-listed fields are
returned even when native tables contain extra columns. A materially different engine
layout can now use `engine-bundle-v1` for independently located parquet outputs whose
fields have the same semantics. The manifest binds SHA-256, engine version and one
snapshot identity per output. Semantic changes (including new native score definitions,
HTTP services or different eligibility rules) still require a new adapter. Never merge
unrelated releases. See [the integration contract](INTEGRATION.md) for the exact boundary.

## HTTP contract

- `GET /api/catalog`: API version, source label, available runs, splits, dates, scenarios.
- `GET /api/snapshot?run=...&split=latest&cutoff=2022-10-26&scenario=primary`: provenance,
  seven engine statuses, summary, actual evaluation (nullable), merchant evidence,
  independent group ranks, warnings, integrity and export availability.
- Contract/source errors: HTTP 422 with `{ "code": "ENGINE_CONTRACT_ERROR", "error": "..." }`.
- `GET /api/export` with the same parameters: an HTTP CSV attachment of the complete
  saved shortlist, with provenance and spreadsheet formula protection. The UI keeps a
  direct download link available for embedded browsers that do not report download events.
- `GET /api/workflow?run=...&split=latest&cutoff=2022-10-26`: source-consistent saved
  scenario comparison and the shared Risk binding; no engine execution or optimiser.

Required prediction values must be finite and nonnegative. Null evidence serialises
as JSON null, never zero. Merchants are joined by **merchant ID × cutoff**. Portfolio
ranks must be unique and contiguous; Revenue, Eligibility, predictions and dispositions
must reconcile. Solver totals are checked using the scenario's correct objective
(individual lower bounds for conservative, revenue estimates otherwise). Unknown or
non-optimal solver status disables export. File caching is invalidated by size/mtime;
reload rejects outputs changed during a read.

Demo mode is explicitly selected in the source menu or via `/?demo=1`. `demo.json`
contains only invented records and is visibly labelled synthetic. For a static demo:

```powershell
python -m http.server 8767 --bind 127.0.0.1 --directory dashboard
```

Then open `http://127.0.0.1:8767/?demo=1`. Double-clicking HTML uses `file://`, which
cannot fetch JSON modules; use one of the HTTP commands above.

## Verification

```powershell
python -m pytest tests/test_dashboard_adapter.py -q
node --test tests/test_dashboard_client.mjs
python scripts/verify_dashboard_connection.py --engine-root '../ads project 2-engines'
```

The first command exercises synthetic contracts, missing outputs, schema drift, hash
mismatch, independent group membership, invalid joins, source privacy and HTTP routes.
The third reads every available saved date/scenario, reconciles shared Risk and scenario
results, and confirms engine Python/notebook/artifact files are unchanged. It writes no output into the engine source directory
and does not rerun trained engines. Browser checks cover source switching, filters,
empty results, detail cards, sorting, pagination and responsive layouts.
