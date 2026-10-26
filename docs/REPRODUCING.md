# Reproduction

## Public demonstration

From the repository root, run `python -m http.server 8767 --bind 127.0.0.1 --directory dashboard`, then visit `http://127.0.0.1:8767/?demo=1`. This uses only the Python standard library and invented records. No API credentials or course input files are needed.

## Synthetic verification

```bash
python -m pip install -r requirements-test.txt
python -m pip install "torch>=2.2,<3" --index-url https://download.pytorch.org/whl/cpu
python -m pytest -q
node --test tests/test_dashboard_client.mjs
python scripts/check_public_release.py
```

Python 3.12 and Node 22 are used in CI. The synthetic suite exercises data transformations, snapshot time boundaries, modelling interfaces, optimiser constraints, source validation and frontend contracts. CPU Torch is needed for the causal-convolution invariant check; CI does not train the full model. Two checks requiring restricted rolling-feature files are skipped in a clean public checkout.

## Authorised local data workflow

The original registered input paths are documented in [`docs/preclean/source_manifest.json`](preclean/source_manifest.json). Restore the four restricted course archives only if you have independent access authorisation. Obtain public reference files from their official publishers using `scripts/download_external_data.ps1`. Downloaded content stays ignored; source hashes are checked before processing.

```bash
python -m pip install -r requirements-modeling.txt
python -m src.bnpl_etl.cli --validate-sources-only
python -m src.bnpl_etl.cli --run-id v1_2
python scripts/validate_etl_outputs.py --run-id v1_2
python scripts/run_cleaned_analysis.py --stage all
python scripts/run_feature_qa.py
python scripts/build_customer_context.py
```

Use a matching official PyTorch CPU/CUDA installation to train the TCN. The historical exact environment in `requirements-engines-lock.txt` is retained as provenance; it is not a portable dependency file for every machine. Do not install its CUDA wheel on an unsupported platform.

Once authorised inputs have passed validation, create a **new unique run ID** for training and follow the fixed development → freeze → test sequence:

```bash
python -m engines.train --run-id my_new_run
python -m engines.system develop --run-id my_new_run
python -m engines.system freeze --run-id my_new_run
python -m engines.system test --run-id my_new_run
python scripts/verify_engine_results.py --run-id my_new_run
```

Test scoring deliberately opens protected test labels after predictions are saved. It is not part of the public demo or CI. Never overwrite a frozen run or choose model/policy settings based on its test outcomes.

## Local dashboard bridge

When saved outputs exist in this checkout:

```bash
python -m dashboard.server --engine-root .
```

Visit `http://127.0.0.1:8766/`. An external authorised checkout may also be supplied with `--engine-root /path/to/checkout`. Configuration and semantic compatibility are documented in [`dashboard/README.md`](../dashboard/README.md).

Notebook sources are published with outputs and execution counts removed. Running them requires local dependencies and data. Earlier detailed workflow documents preserve their original dated scope; this guide is the entry point for the public edition.
