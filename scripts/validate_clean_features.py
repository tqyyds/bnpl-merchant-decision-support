"""Acceptance gate for data delivery, independent of model artifacts or fitting."""
from pathlib import Path
import json
import sys

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.validate_etl_outputs import validate as validate_etl
from src.bnpl_analysis.common import load_config,save_json
from src.bnpl_analysis.feature_qa import run_feature_qa
from src.run_artifacts import snapshot_manifest_path,file_hash


def validate(root):
    config = load_config(root)
    etl = validate_etl(root,config['cleaning_run_id'])
    quality = run_feature_qa(root,config)
    local = root/'tables/modeling'/config['snapshot_run_id']
    manifest = json.loads(snapshot_manifest_path(root,config['snapshot_run_id']).read_text(encoding='utf-8'))
    for entry in manifest['output_files']:
        path = root/entry['path']
        assert file_hash(path) == entry['sha256']
    # Protected test values are not scored or explored; footer/schema only here.
    for row in manifest['splits']:
        x,y = [pq.ParquetFile(local/f"{row['split']}_{kind}.parquet") for kind in ('features','labels')]
        assert x.metadata.num_rows == y.metadata.num_rows == row['eligible_rows']
        assert not {'name','address','gender','target_revenue','future_gmv'}.intersection(x.schema.names)
    context = root/'tables/features/customer_context_v1'
    assert (context/'_SUCCESS').exists()
    context_manifest = json.loads((context/'manifest.json').read_text(encoding='utf-8'))
    for entry in context_manifest['output_files']:
        path = root/entry['path']
        assert file_hash(path) == entry['sha256']
    latest = pq.ParquetFile(context/'merchant_features_latest.parquet')
    unknown = pq.ParquetFile(context/'unknown_merchants_latest.parquet')
    assert latest.metadata.num_rows == 4026 and unknown.metadata.num_rows == 396
    assert not {'name','address','gender','target_revenue','future_gmv'}.intersection(latest.schema.names)
    assert set(manifest['predictor_columns']).issubset(latest.schema.names)
    assert not any(name.startswith('ctx_') for name in manifest['predictor_columns'])
    # Check complete all-candidate status/keys at each DEVELOPMENT cutoff only.
    checked = 0
    for row in context_manifest['development_candidate_status_counts']:
        frame = pd.read_parquet(context/f"context_{row['cutoff']}.parquet")
        core = pd.read_parquet(local/'all_candidates'/f"{row['split']}_all_candidates.parquet")
        core = core.loc[core.cutoff.eq(pd.Timestamp(row['cutoff']))]
        merged = core.merge(frame,on=['merchant_abn','cutoff'],validate='one_to_one')
        assert len(merged) == len(core) == len(frame) == 4026
        assert merged.eligible_history.eq(merged.candidate_eligible_for_primary_model).all()
        assert merged.hist_unique_customers.eq(merged.ctx_observed_customers).all()
        assert not merged.ctx_historical_availability_verified.any()
        checked += len(frame)
    result = {'status':'PASS','etl':etl,'primary_predictors':quality['predictor_count'],
              'development_feature_rows_checked':quality['development_rows'],
              'development_context_rows_checked':checked,'context_snapshots':context_manifest['context_snapshots'],
              'latest_merchant_rows':4026,'latest_columns':len(latest.schema.names),
              'unresolved_merchants':396,'models_fitted':False,'test_performance_evaluated':False,
              'test_feature_label_values_opened_by_this_validator':False}
    save_json(result,root/'reports/clean_features_acceptance.json')
    return result


if __name__ == '__main__':
    print(json.dumps(validate(ROOT),indent=2))
