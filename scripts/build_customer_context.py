"""Generate candidate coverage/context and a latest-date merchant feature export; no model fitting."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.bnpl_analysis.common import clean_paths,load_config,read_partition,partition_date,save_json
from src.bnpl_analysis.time_split import snapshot_schedule,features_for_window,READ_COLUMNS
from src.bnpl_analysis.customer_context import context_for_window,CONTEXT_INPUTS
from src.run_artifacts import claim_run,finish_run,inventory,provenance


def build(root: Path):
    config = load_config(root)
    staging,_,files = clean_paths(root,config['cleaning_run_id'])
    destination = root/'tables/features/customer_context_v1'
    claim_run(destination)
    masters = pd.read_parquet(staging/'merchant_master.parquet')
    consumers = pd.read_parquet(staging/'consumers.parquet',columns=CONTEXT_INPUTS)
    consumer_fraud = pd.read_parquet(staging/'fraud/consumer_daily.parquet')
    merchant_fraud = pd.read_parquet(staging/'fraud/merchant_daily.parquet')
    first = {}
    partitions = {partition_date(path):path for path in files}
    for date,path in partitions.items():
        ids = read_partition(path,['merchant_abn']).merchant_abn.unique()
        for merchant in ids:
            first.setdefault(merchant,date)
    first_seen = pd.Series(first)
    schedule = snapshot_schedule(str(min(partitions).date()),str(max(partitions).date()),config)
    definitions = [*[(r.cutoff,r.split) for r in schedule.itertuples()],(max(partitions),'latest_export')]
    development = []
    context_fields = None
    for cutoff,split in definitions:
        start = cutoff-pd.Timedelta(days=config['history_days']-1)
        columns = list(dict.fromkeys([*READ_COLUMNS,'consumer_id']))
        history = pd.concat([read_partition(partitions[d],columns) for d in pd.date_range(start,cutoff)],ignore_index=True)
        context = context_for_window(history,masters,consumers,first_seen,cutoff,config['history_days'])
        assert len(context) == len(masters) and context.merchant_abn.is_unique
        assert not np.isinf(context.select_dtypes('number').to_numpy()).any()
        for column in context:
            if column.endswith('_coverage') or column.endswith('_gmv_hhi'):
                values = context[column].dropna()
                assert values.between(-1e-12,1+1e-12).all(),column
        assert context.loc[context.candidate_status.eq('no_observed_history'),'first_observed_order_asof'].isna().all()
        context_fields = list(context.columns)
        context.to_parquet(destination/f'context_{cutoff.date()}.parquet',index=False)
        # Only development-period distributions are reported for feature decisions.
        if split in ('train','validation'):
            development.append({'cutoff':str(cutoff.date()),'split':split,
                                **{str(k):int(v) for k,v in context.candidate_status.value_counts().items()}})
        if split == 'latest_export':
            core = features_for_window(history,masters,cutoff,config['history_days'],consumer_fraud,merchant_fraud)
            enriched = core.merge(context,on=['merchant_abn','cutoff'],validate='one_to_one')
            enriched = enriched.merge(masters[['merchant_abn','merchant_name']],on='merchant_abn',validate='one_to_one')
            enriched.to_parquet(destination/'merchant_features_latest.parquet',index=False)
            enriched.to_csv(destination/'merchant_features_latest.csv',index=False)
            assert len(enriched) == 4026
            missing_ids = first_seen.index.difference(masters.merchant_abn)
            unknown = pd.DataFrame({'merchant_abn':missing_ids})
            unknown['first_observed_order_asof'] = unknown.merchant_abn.map(first_seen)
            unknown['candidate_status'] = 'unresolved_missing_master'
            unknown['candidate_eligible_for_primary_model'] = False
            unknown.to_parquet(destination/'unknown_merchants_latest.parquet',index=False)
            unknown.to_csv(destination/'unknown_merchants_latest.csv',index=False)
        print(f'Context {cutoff.date()}: written; no merchant values printed',flush=True)
    report = {'status':'PASS','context_run_id':'customer_context_v1','cleaning_run_id':config['cleaning_run_id'],
              'snapshot_run_id':config['snapshot_run_id'],'context_columns':context_fields,
              'context_use':'descriptive_only_excluded_from_primary_predictors',
              'primary_predictor_count':46,'master_rows_per_cutoff':len(masters),
              'latest_export_cutoff':str(max(partitions).date()),'context_snapshots':len(definitions),
              'development_candidate_status_counts':development,
              'models_trained_by_this_workflow':False,'test_performance_evaluated':False,
              'provenance':provenance(root,config),'output_files':inventory(root,destination.glob('*.parquet'))}
    save_json(report,destination/'manifest.json')
    save_json(report,root/'reports/feature_qa/customer_context_v1.json')
    finish_run(destination)
    return report


if __name__ == '__main__':
    build(ROOT)
