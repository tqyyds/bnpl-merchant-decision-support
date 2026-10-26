# Seven-engine and Dashboard audit — 5 October 2026

**Needs revision. Coverage: Partial for current independent producers; the saved seven-engine replay was inspected across all available dates/scenarios.** Dashboard repairs were made and verified. Engine algorithms, historical artifacts and the original prototype were preserved.

The seven visible panels do not prove that seven current engines have executed together. The current product reads `seven_v1_20260906` from the sibling `ads project 2-engines` checkout. Its registered bundle is a second registration of the same outputs, not an independent run. Earlier descriptions of a complete workflow refer to this saved-output replay. They do not establish current producer execution or Risk participation in optimisation.

## Engine results

| Engine | Saved logic and Dashboard reconciliation | Remaining limitation |
|---|---|---|
| Revenue | Trailing-90-day revenue proxy × 28/90, merchant estimates and portfolio totals reconcile. | Latest outcomes are unavailable; this is estimated take-rate revenue, not profit. No retraining/performance certification. |
| Eligibility | Historical inclusion rules, reason codes and eligible prediction population reconcile. | Merchant master has retrospective/static assumptions; fully point-in-time metadata publication is not attested. |
| Confidence | Intervals and reliability reproduce the frozen calibration; Dashboard retains INSUFFICIENT. | Validation coverage by bin is approximately 91.7%, 67.4%, 81.6%; frozen acceptance fails. Test results cannot replace validation acceptance. |
| Risk | Native fraud evidence, nullable coverage and review thresholds reconcile. Latest selected 100 have 100 unknown evidence states. | No validated expected-loss model; GAM proxy outputs are not integrated. Unknown evidence is not zero risk. |
| Diversification | Saved revenue-weighted category HHI and exposure diagnostics reconcile. | Risk does not enter its calculation. The marginal field means hypothetical addition to the primary portfolio, including duplicate addition for existing members. |
| Strategic fit | Source correctly supplies NOT_CONFIGURED and neutral values. | No business policy is supplied; strategic fit does not influence the saved optimisation objective. |
| Portfolio/Profile | Saved membership, ranking, capacity, category caps and confidence caps reconcile across scenarios. | System does not activate the optional risk policy. Shared Risk bindings only enrich Dashboard views. |

## Prioritized problems and proposed fixes

1. **P1 — Risk is not in the decision chain.** `engines/system.py` merges native Risk into predictions, but calls `optimise` with existing scenario arguments that omit `risk_policy`. Diversification computes category/exposure concentration without Risk input. New independent Diversification explicitly excludes Risk; new Portfolio disables risk constraints. **Fix (Proposed):** establish one producer-owned Risk contract, join on merchant and decision cutoff, validate time/model/label/policy identities, then explicitly enable supported risk scenarios. Emit consumer execution attestations and resulting risk exposure. Keep proxy evidence distinct from validated loss inputs. Algorithms were not changed because this project is currently an integration window.

2. **P1 — New producer formats and GAM are not fully integrated.** New Revenue has `decision_cutoff`/`predicted_revenue`; Confidence has new interval/evidence semantics; Portfolio omits canonical scenario/rank; Strategy supplies policy identities outside the current DTO. Naming/renaming alone cannot establish semantic compatibility. GAM merchant probability outputs and their COMPLETE_PROXY_SHADOW manifest need a separate adapter. Remote `main2` producer scripts also import `engines.contracts`, `engines.course_fraud` and `engines.tail_risk` absent from that remote tree; this blocks a reproducible clean-clone risk pipeline. **Fix (Proposed):** repair producer packaging, provide native producer manifests, then add versioned semantic adapters and one coherent frozen run. Do not mix February proxy evidence into October decisions.

3. **P1 — Future Risk policy accepts unsupported time/version identities.** A synthetic 2022 decision with `risk_prediction_as_of=2099-01-01` and a policy requesting a different model version still returns OPTIMAL. `engines/risk_policy.py` checks uniform metadata within the frame but does not compare it with the cutoff/policy identity. **Fix (Proposed):** enforce the requested model/label identity and `prediction_as_of <= decision_cutoff`; add rejecting boundary cases. This path is not active in the saved authoritative run. Non-numeric loss input also escapes as ValueError rather than the advertised INVALID_RISK_INPUTS status (P2).

4. **P1 — File integrity was mistaken for semantic/producer lineage.** A real GAM parquet with correct SHA and dashboard-declared snapshot identity was previously accepted as native Risk while probability fields were projected away. **Fixed:** native Risk schema now rejects this actual GAM file; missing Risk files/cutoffs propagate MISSING_SOURCE/MISSING_AT_CUTOFF to both views. Manual bundle identities are disclosed as DASHBOARD_MANIFEST / NOT_ATTESTED. **Fix (Proposed):** stronger producer attestation must check native source/config/model/label/output manifests; file hashes alone cannot certify a coherent producer run.

5. **P1 — Historical execution and current code were conflated.** Frozen source hashes show the current `engines/portfolio.py` differs from the saved run. **Fixed:** the app shows SAVED_OUTPUT_REPLAY, changed filenames, and CURRENT_CODE_DIFFERS_FROM_FROZEN_RUN. Connection cards say Output loaded; shared Risk is explicitly a Dashboard evidence interface with engine consumption not attested. Confidence failure and unknown Risk remain visible. **Fix (Proposed):** before claiming a current full run, enforce frozen model/manifest hashes during test/latest execution as well as cleaned-input hashes (the saved run's present hashes match, but the execution code does not enforce the retained modeling-manifest hash).

## Scope and retained evidence

- Independent calculation script: ignored `dashboard/.local/engine_audit_20261005.py`; aggregate result `engine-independent-audit.json`. All 12 dates and 60 scenarios: 535 checks with no differences. Checks recompute revenue, eligibility, confidence, native Risk flags, strategic neutrality, rankings, membership, caps, HHI and displayed totals from retained source rows. These are reconciliation checks, not a probability of correctness.
- Source engine tests: 61 passed across seven-engine, review-fix and risk-label suites. Reviewed forward time OOF construction, train-only preprocessing and revenue exclusion of fraud fields; no direct label leakage found in those inspected paths. Fraud publication delay and point-in-time master authority remain unverified.
- Frozen inventory: 612 cleaned inputs and five model/policy artifacts match retained hashes; output locks match all three splits; 22 of 23 frozen code files match the current checkout. `engines/portfolio.py` differs. New `risk_policy.py` is outside the historical freeze.
- Repaired Dashboard: 43 Python tests (38 Dashboard + five existing ETL), nine frontend tests, actual incompatible GAM rejection, actual legacy execution metadata, and browser desktop/narrow inspection. Full saved-source replay is recorded in VERIFICATION.md.
- Browser checks inspect source status, code drift, latest unknown Risk, shared interface disclaimers, historical window switching and narrow layout. Existing unaffected view/CSV checks from the product integration were retained. Repeated merchant/group presentation is sampled; every possible control combination was not exhaustively rendered.
- No models were retrained. Global optimality was not independently re-solved for every constrained scenario; saved solver audits and existing synthetic exhaustive solver tests support the inspected selections. No independent new producer pipeline was executed.

Sources: sibling checkout commit `13a597190da83f93eb16308fbbf487dfb270dcf2`, saved run `artifacts/seven_engines/seven_v1_20260906`; frozen source records in `freeze.json`; current sibling `engines/system.py:41–70`, `engines/risk_policy.py:49–53`, `engines/diversification.py:14–29`, `engines/portfolio.py:10–30`. New producer packaging/formats were inspected in the repository's remote `main2` tree, separately from the sibling saved run.

## Acceptance for completing integration

1. Restore clean-clone producer dependencies and publish producer-owned versioned output manifests.
2. Define distinct native-evidence, proxy-shadow and validated-loss Risk profiles with time, model, label and policy gates.
3. Wire Risk explicitly into Diversification and Portfolio/Profile execution; require consumer attestations rather than Dashboard-derived bindings.
4. Add semantic adapters for all new independent engines, including scenario/rank and policy identity; reject incompatible snapshots.
5. Execute a coherent frozen run; reconcile all engine populations and run rejecting time/version/missingness cases, then verify Dashboard and export against those exact outputs.

The scorecards below use scoped components/questions, not test counts. `0 / N` means no remaining observed defect; it does not assert every item was completely verified. Categories overlap and cannot be summed into an accuracy percentage.

### Dashboard best practices and quality

| Category | Observed defects | Assessment |
|---|---|---|
| Dashboard usefulness and completeness | 3 / 9 | Saved-output inspection works. Current producer execution, Risk decision integration and GAM integration remain missing. |
| Analytical clarity | 0 / 6 | Historical replay, unknown evidence, failed Confidence acceptance and engine consumption limitations are explicit. |
| Visual and interaction consistency | 0 / 6 | Changed Risk/source panels checked on desktop and 390px viewport; unaffected views reuse prior product acceptance. Repetitive rows and filter combinations are sampled. |

### Analytical correctness and robustness

| Category | Observed defects | Assessment |
|---|---|---|
| Source authority and confidence | 2 / 9 | Frozen saved sources reconcile. Dashboard-declared bundles lack producer attestation; GAM needs its own contract. Point-in-time metadata publication remains unverified. Partial review: 1 scoped item has incomplete or stale evidence (Eligibility). |
| SQL/value accuracy | 1 / 8 | Seven saved engine outputs reconcile across 12 dates/60 scenarios. Future Risk policy has a reproduced time/version gate defect; model performance is not certified. |
| Within-chart agreement | 0 / 3 | Overview, Risk and scenario totals/labels reconcile. Repeated group marks are sampled. |
| Complete source details | 0 / 3 | Three source surfaces disclose output integrity, shared Risk bindings and saved scenario identities; producer attestations remain separately documented. |
| Cross-artifact consistency | 4 / 9 | Saved outputs agree; Risk is absent from Diversification/Portfolio execution and new producer/GAM semantics are not integrated. |
| Data-quality controls | 3 / 10 | Missingness and native-schema repairs verified. Future Risk gates, producer lineage and model freeze enforcement need revision. |
| Conclusion support | 0 / 7 | Seven engine interpretations remain conditional on saved outputs; Confidence is insufficient and native Risk is not validated loss. |
