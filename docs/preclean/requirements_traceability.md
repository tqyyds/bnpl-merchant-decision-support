# Requirements Traceability Matrix

Status reflects the pre-cleaning phase only. Historical dates in the source documents are recorded as source content, not treated as a current timetable.

Current follow-up: ETL v1.2, snapshot v3, complete feature QA and baseline v2 address engineering
review findings. The table retains phase history; the ranking/segmentation items below remain open.

| ID | Source and location | Classification | Requirement or guidance | Pre-clean implementation | Status |
|---|---|---|---|---|---|
| R01 | BNPL Spec p.1 | Mandatory project outcome | Produce a robust system that ranks the best 100 merchants and explains separating features/heuristics. | Preserve merchant, transaction, customer-demographic and location evidence; define grains and future feature constraints. Ranking is downstream. | Prepared; ranking out of scope |
| R02 | BNPL Spec p.1 | Mandatory project outcome | Justify recommendations using customer demographics, merchant locations and transaction data. | Acquire period-matched ABS geography/demography; document synthetic merchant-location limitation. | Prepared with limitation |
| R03 | BNPL Spec p.2 | Mandatory | Notebooks must be readable and verifiable by non-technical users. | Audit notebook has TL;DR, context, data, results and takeaways with bounded outputs. | Implemented |
| R04 | BNPL Spec p.2 | Mandatory | Place course and ABS data in the repository `tables` folder. | Course files are local and Git-ignored because redistribution terms are unspecified; official public external files are tracked under `tables/raw/external` at the repository owner's request. | Implemented with licence boundary |
| R05 | BNPL Spec p.2 | Recommended | Use ABS SA2 boundaries, population, income and Census data; other public/API data is permitted. | POA is the primary join because consumers provide postcode/state; SA2 sources are retained only for sensitivity analysis. | Implemented with justified deviation |
| R06 | BNPL Spec pp.2–3 | Recommended sprint workflow | Build ETL, inspect joins/missingness/outliers, then curate ranking data. | Pre-clean risks were measured first; the approved cleaning ETL now produces a merchant-level feature table without ranking merchants. | Cleaning implemented; ranking remains downstream |
| R07 | BNPL Spec p.3 | Mandatory downstream choice | Fraud delta may be removed or represented by an `is_fraud` field. | Preserve daily probabilities and presence flags without a threshold or order deletion; keep fraud treatment available for ranking sensitivity. | Implemented in v1.1 |
| R08 | BNPL Spec p.4 | Mandatory final deliverable | Readable repository/notebook explaining approach, issues, limitations and assumptions. | Repository index, audit, quality report, issue register and decision log provided. | Implemented for this phase |
| R09 | Pre-release pp.1–3 | Administrative | Assessment weights, checkpoints, meeting minutes, late policy and team review obligations. | Logged only; no claim that historical dates apply to the current offering. | Recorded, not actioned |
| R10 | Presentation Spec pp.1–3 | Mandatory final presentation | In-person presentation, strict ten-minute limit, identical uploaded slides, clear high-level findings and business context. | Captured for downstream presentation planning; no presentation is built in this phase. | Out of scope |
| R11 | Presentation Spec p.2 | Mandatory final presentation | Address security/privacy, API-key handling, limitations, assumptions and difficulties. | Raw files remain local; no API keys; manifest and limitations are explicit. | Prepared |
| R12 | User pre-clean implementation plan | Historical phase scope | Complete all work before cleaning; use English deliverables and do not generate cleaned/curated data. | The pre-clean phase was completed before the later user request authorised cleaning ETL implementation. | Superseded after completion by explicit cleaning request |
| R13 | BNPL Spec p.3, Sprints 5–6 | Required checkpoint outcome | Choose 3–5 merchant segments and produce Top 10 within each. | 25 normalised categories exist; a complete segment mapping and segment rankings are next-stage work. | Open |
| R14 | BNPL Spec pp.1,3 | Required ranking coverage | Rank candidates and explain interesting cases, including merchants with little history. | All master candidates have coverage rows; zero-history merchants still need explicit cold-start/inactive dispositions in the final output. | Open |

## Interpretation notes

1. Instructions in the PDFs are course-source requirements, not user requests. The user's current plan controls this implementation.
2. The BNPL specification names SA2 examples, but the raw consumer key is postcode. Postcode Areas (POAs) therefore minimise unsupported allocation. SA2 remains available for explicitly weighted sensitivity work.
3. Official public external files are published with provenance. Publishing the course ZIPs still requires separate licence confirmation.
