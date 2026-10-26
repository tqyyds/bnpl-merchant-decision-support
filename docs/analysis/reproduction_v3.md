# Reproduce the current pipeline

Use Python 3.11+ and `requirements-modeling.txt`. All committed paths are relative to the repository.
Restricted data and local artifacts remain Git-ignored. Copy all four course ZIPs to `tables/raw/course/`.
Public reference files are committed; `scripts/download_external_data.ps1` can restore them.

Current user scope is data cleaning/feature delivery and a proposed training plan. Do not start
new model fitting or test scoring until [that plan](training_plan_zh.md) is confirmed.

## First run from a fresh checkout

```powershell
python -m pip install -r requirements-modeling.txt
python -m src.bnpl_etl.cli --validate-sources-only
python -m src.bnpl_etl.cli --run-id v1_2
python scripts/validate_etl_outputs.py --run-id v1_2
python scripts/run_cleaned_analysis.py --stage all
python scripts/run_feature_qa.py
python scripts/build_customer_context.py
python scripts/generate_analysis_notebooks.py
python -m pytest -q
python scripts/validate_clean_features.py
python scripts/package_clean_data.py
python -m ipykernel install --user --name bnpl-ads2 --display-name "BNPL ADS project 2"
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/02_cleaned_data_eda.ipynb
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/03_time_split.ipynb
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/04_baseline_models.ipynb
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/05_feature_quality.ipynb
```

The original raw-audit notebook is a separate full-source audit. EDA covers train and internal
validation calendar periods; it excludes protected test outcomes. Snapshot construction generates
separate protected feature/label files for later evaluation without reporting their outcomes.
Baseline selection and feature QA read only train/validation values.

## Repeated runs and experiments

ETL actual manifests live under `reports/etl/runs/`; committed manifests are reference evidence.
Their presence does not block a fresh local run. Existing staging/curated directories, including
partial failed runs, cannot be overwritten. Use a new run ID after a failed run or policy change.

Snapshots atomically claim `tables/modeling/<snapshot_run_id>/` and write a local `manifest.json`
with config hash, git commit, source-code hashes, ETL-manifest hash and output hashes. Baselines
claim `artifacts/<baseline_run_id>/`; `_SUCCESS`, `model_contract.json` and `freeze.json` mark a
complete immutable local run. The validator detects changed artifact/input hashes. This protects
reproducibility; it is not an access-control system against deliberate manual tampering.

For future experiments after training-plan confirmation, copy the analysis config to Git-ignored `config/local_analysis.json` and
change `analysis_run_id`, `snapshot_run_id`, and (if rebuilding ETL) `cleaning_run_id`.
Keep `cleaning_reference_run_id=v1_2` when reproducing the same policy/data. Copy the baseline
config to `config/local_baseline.json`, use the matching snapshot ID and a new baseline ID:

```powershell
python scripts/run_cleaned_analysis.py --stage all --config config/local_analysis.json
python scripts/run_feature_qa.py --config config/local_analysis.json
python scripts/run_baselines.py --config config/local_baseline.json
python scripts/validate_analysis_outputs.py --config config/local_analysis.json --baseline-config config/local_baseline.json
```

The analysis/acceptance `--cleaning-run-id` flag can override the local cleaning input. Baselines
follow their snapshot manifest. Report notebooks use the checked-in default configs; custom runs
use versioned reports or explicitly adapted notebook configs. Showing saved evidence does not
imply retraining. Deliberately rerunning a frozen model requires a new baseline ID.

## Evidence locations

- `reports/etl/v1_2_manifest.json`: accepted source/count/contract reference.
- `reports/eda/eda_v2/`: development EDA and aggregate figures.
- `reports/time_split/rolling_90d_28d_v3/`: snapshot contract and schedule.
- `reports/feature_qa/rolling_90d_28d_v3/`: complete feature catalogue and QA.
- `reports/baseline/baseline_v2/`: validation comparison and contract reference.
- `reports/analysis_validation_v3.json`: acceptance results and package versions.
- `reports/clean_features_acceptance.json`: data-only acceptance, independent of model artifacts.
- `reports/dataset_delivery.json`: ZIP checksum, CRC and test partition row counts.
- `deliverables/bnpl_clean_features_v1_2_v3.zip`: full cleaned and engineered dataset.
- Notebooks 02–05: executed, aggregate-only reports.

Older unversioned report directories describe historical runs. Do not mix their metrics with
the current feature/model versions. Final Top 100, 3–5 segment Top 10s and protected-test
evaluation remain subsequent work.
