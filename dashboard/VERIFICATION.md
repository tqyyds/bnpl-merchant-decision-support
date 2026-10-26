# Front-end connection verification

Verified on 4 October 2026 (Australia/Sydney).

Source: local `ads project 2-engines`, saved run `seven_v1_20260906`.
Only the output reader was exercised; engines were not imported, trained or executed.

| Check | Result |
|---|---|
| Python suite | 30 passed: 25 dashboard contract/HTTP/export checks and 5 existing ETL checks |
| Front-end transport/DTO suite | 5 passed |
| Saved engine snapshots | 60 passed: 1 latest + 8 test + 3 validation dates, each with 5 scenarios |
| Source preservation | All 95 engine Python/artifact files retained identical SHA-256 hashes during verification; engine checkout remained clean |
| Browser: source and scenario selection | Live / explicit demo, latest / test, primary / conservative verified |
| Browser: explorer | Search/detail synchronisation, empty-state clearing, filters, sorting and pagination verified |
| Browser: engine status | Seven connection cards, native status wording and parquet integrity visible |
| Browser: CSV export | HTTP attachment downloaded successfully; 100 merchant rows, 12 columns |
| Browser: responsive view | 390 × 844 viewport: no document-level horizontal overflow; tables scroll inside their container |
| Browser console | No errors or warnings observed |

The Python run reports one existing pandas FutureWarning in the ETL geography test;
that code was not changed. Verification concerns integration with saved outputs, not
model performance, retraining or production deployment.

Reproduction commands and the changeable adapter contract are in [README.md](README.md).
The local screenshot is under ignored `dashboard/.local/`; no merchant-level engine data
was embedded in tracked front-end assets or this verification record.

## Product integration update — 5 October 2026

| Check | Result |
|---|---|
| Python suite | 40 passed: 35 dashboard checks and 5 existing ETL checks |
| Frontend suite | 9 passed, including Risk binding mismatch, unaccepted high-band Confidence review, escaped source text and workflow transport |
| Saved-source replay | 120 snapshots passed: 60 legacy + 60 independently registered views of the same saved outputs; these are not two independently trained releases |
| Scenario comparison | All 12 dates in each adapter; common Risk binding, coherent source fingerprint, membership/revenue/HHI reconciliation |
| Source preservation | 113 engine Python/notebook/artifact files retained identical SHA-256 hashes |
| Latest Risk evidence | Selected 100: observed 0, unknown 100, source review prompts 0; no missing-to-zero risk conversion |
| Historical Risk evidence | 27 February 2022 selected 100: observed 100, unknown 0, source review prompts 49 |
| HTTP export | 100 rows × 20 columns; exported Risk bindings match the snapshot; formula guard retained |
| Browser independent registration | Registered run loads all seven engines, exact versions, shared Risk contract and source lineage |
| Browser scenario drill-through | Saved conservative comparison opens the corresponding portfolio with matching global scenario control |
| Browser Confidence | INSUFFICIENT remains visible; all 100 selected merchants remain in the inspection queue even with mostly high legacy bands |
| Browser mobile | 390 × 844 viewport; document client width equals scroll width (375 CSS px excluding scrollbar), scenario table scrolls within its 311px container |
| Browser Risk scope | Selected → eligible (3,961) → selected; counts reconcile and missing evidence remains unknown |

The complete workflow is saved-output replay and product integration. Engines were not
imported, retrained or modified. The independently registered bundle intentionally omits
evaluation until an evaluation-lineage contract exists; the legacy source retains its
existing validated outcome comparison. Current source outputs do not attest execution
of Risk constraints inside the Diversification/Portfolio producer algorithms.

## Independent engine audit — 5 October 2026

The [audit](ENGINE_AUDIT_2026-10-05.md) supersedes any interpretation that seven loaded
panels establish current producer execution. Independent reconciliation found no
differences across 535 checks over 12 dates/60 scenarios. Reviewed engine suites passed
61 tests, while current Risk policy and producer packaging retain documented defects.
After Dashboard repairs, 43 Python tests (38 Dashboard + five ETL) and nine frontend
tests pass. An actual GAM merchant file is rejected by the native-evidence adapter;
actual historical source reports portfolio code drift. Missing-file and empty-cutoff
Risk statuses propagate to both downstream views. Browser checks verify the changed
status/caveat text and desktop/narrow presentation. Engines were not modified.

Final replay after repairs: 120 snapshots pass (60 legacy and 60 registered views of
the same source), with shared bindings/scenario reconciliation intact and all 113
inspected source code/notebook/artifact files unchanged. Desktop and narrow screenshots
show saved-output status and unknown Risk correctly; historical 27 February 2022
switching yields 100 observed, zero unknown and 49 source prompts. No browser errors
or warnings were observed in this focused final check.
