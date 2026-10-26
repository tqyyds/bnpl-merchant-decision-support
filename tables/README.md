# Local data directories

Raw and generated data are excluded from this public repository. Restore authorised inputs under `tables/raw/course/` and official reference data under `tables/raw/external/`. ETL creates versioned `tables/staging/` and `tables/curated/` outputs; feature construction creates `tables/modeling/`.

See [`docs/REPRODUCING.md`](../docs/REPRODUCING.md) and [`docs/DATA_POLICY.md`](../docs/DATA_POLICY.md). The synthetic dashboard does not need any of these directories.
