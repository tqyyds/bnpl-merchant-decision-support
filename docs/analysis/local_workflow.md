# Local EDA and time-split workflow

This page records the historical v1.1/v2 workflow. For current v1.2 cleaning, v3 snapshots,
baseline v2 and notebook execution, follow [reproduction_v3.md](reproduction_v3.md).

## PyCharm

Open this repository folder as the **ADS project 2** project. Create a project-local virtual
environment (for example `.venv`) and install `requirements-modeling.txt`; select that interpreter in
PyCharm. The `.idea` and virtual-environment directories are local and Git-ignored.

The scripts can run from PyCharm Community Edition's Python run configuration or terminal.
The executed notebooks can also be opened with Jupyter; notebook support depends on the IDE edition.

## Data location

The committed default points to the accepted `v1_1` cleaning run. A contributor can select a
different completed local run with `--cleaning-run-id` without editing committed configuration.
`tables/staging`, `tables/curated` and `tables/modeling` are generated, Git-ignored directories.
Contributors may redirect them locally with filesystem links when storage is limited, but committed
configuration and documentation must not depend on a machine-specific drive or absolute path.

The cleaned-data validator must pass before EDA. The old `data/gold` outputs from an earlier trial
are not used by this analysis.

## Commands (from repository root)

```powershell
python -m pip install -r requirements-modeling.txt
python -m src.bnpl_etl.cli --run-id v1_1
python scripts/validate_etl_outputs.py --run-id v1_1
python scripts/run_cleaned_analysis.py --stage eda --cleaning-run-id v1_1
python scripts/run_cleaned_analysis.py --stage split --cleaning-run-id v1_1
python scripts/run_baselines.py
python scripts/generate_analysis_notebooks.py
python -m pytest -q
python -m ipykernel install --user --name bnpl-ads2 --display-name "BNPL ADS project 2"
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/02_cleaned_data_eda.ipynb
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/03_time_split.ipynb
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/04_baseline_models.ipynb
python scripts/validate_analysis_outputs.py
```

Do not repeat the cleaning command if that run ID already completed. It intentionally refuses
overwrites. Reuse the valid cleaned data, or pass another completed run with
`--cleaning-run-id <run_id>`; do not commit a machine-specific run ID.

## Printed / visual results

- `reports/eda/README.md`: aggregate historical findings and charts.
- `notebooks/02_cleaned_data_eda.ipynb`: executed EDA presentation.
- `reports/time_split/README.md`: rolling snapshot dates, engineered feature families and leakage safeguards.
- `notebooks/03_time_split.ipynb`: executed split checks, with no labels printed.
- `reports/baseline/README.md`: aggregate validation-only baseline comparison.
- `notebooks/04_baseline_models.ipynb`: executed baseline comparison; no merchant rows or test outcomes.
- `reports/baseline/model_contract.json`: validation-selected specification frozen before test access.
- `docs/analysis/tcn_v6_transfer_assessment.md`: latest V6 compatibility assessment.
- `reports/analysis_validation.json`: independent acceptance checks and package versions.

The notebook generator is `scripts/generate_analysis_notebooks.py`. It creates report notebooks
that reuse existing analysis reports or run the corresponding stage if missing. To deliberately
refresh the analysis, rerun the analysis script before executing the notebooks.

## Future operational risk-label release

This workflow is inactive for the course data. Never pass the course consumer/merchant
`fraud_probability` files as events or labels. It requires separately governed operational inputs:

- canonical orders with payment-authorisation decision time, authorisation time, gross authorised
  AUD amount, eligibility, `order_id`, and `merchant_abn`;
- append-only risk events satisfying the fields and version rules in
  [risk_label_and_loss_design.md](risk_label_and_loss_design.md);
- an explicit eligible merchant universe, including merchants with no future orders;
- a source-coverage snapshot with required/complete sources and operational/Finance net-loss totals;
- a maturity-validation snapshot with its ID, source release hashes, and measured 90/120/150-day
  post-maturity adjustment rates; and
- a reviewed `config/local_risk_label_contract.json` copied from the checked-in fail-closed template.

The local config must contain owner-approved values for the selected maturity window, maximum
post-maturity adjustment rate, loss-classification priority, required sources, and Finance
reconciliation tolerance. Model acceptance thresholds and portfolio budgets remain null until their
separate governance decisions. The release command rejects null build decisions, incomplete source
coverage, maturity evidence inconsistent with the selected window, failed reconciliation, and an
existing destination.

```powershell
python scripts/build_risk_labels.py `
  --orders tables/work/risk_labels/orders.parquet `
  --events tables/work/risk_labels/operational_risk_events.parquet `
  --merchants tables/work/risk_labels/merchant_universe.parquet `
  --coverage tables/work/risk_labels/coverage_snapshot.json `
  --maturity-validation tables/work/risk_labels/maturity_validation.json `
  --config config/local_risk_label_contract.json `
  --output tables/modeling/risk_labels/<label_version> `
  --label-version <label_version> `
  --label-as-of <UTC_timestamp> `
  --data-as-of <UTC_timestamp> `
  --cutoff <YYYY-MM-DD>
```

Repeat `--cutoff` for multiple non-overlapping cohorts. A successful release contains
`order_fraud_labels.parquet`, `merchant_loss_labels.parquet`,
`quarantined_risk_events.parquet`, a hashed `manifest.json`, and `_SUCCESS`. Its manifest status is
`LABEL_RELEASE_ONLY_NOT_MODEL_VALIDATED`; generation does not move the risk engine into `SHADOW` or
`VALIDATED`.

## Course fraud proxy GAM

The course proxy path is separate from the unavailable operational loss-label path. It uses only
the fraud source coverage through 27 February 2022 and permanently emits `PROXY_SHADOW` /
`EVIDENCE_ONLY_NO_LOSS_LABELS`. Run it as a module so the repository package is on `sys.path`:

```powershell
python -m scripts.train_course_fraud_proxy `
  --root . `
  --run-id <new_run_id> `
  --config config/course_fraud_model_v1.json
```

See [course_fraud_proxy_gam.md](course_fraud_proxy_gam.md) for the split, model, calibration,
ablation, label-sensitivity and reporting contracts. Never treat transactions after the proxy source
coverage end as negative evaluation examples.

## Publication boundary

Allowed: analysis code, methodology, executed aggregate-only notebooks, aggregate statistics and
figures. Excluded: source ZIPs, customer/merchant-level tables, feature/label Parquet files, model
checkpoints, IDE configuration and local ETL manifests. Inspect notebook outputs and Git's staged
file list before every push. Do not publish raw `.head()` outputs or named merchant rankings.
