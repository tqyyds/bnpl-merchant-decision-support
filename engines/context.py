"""As-of candidate dispositions and full-denominator customer catchment exposure."""
from pathlib import Path
import pandas as pd
from src.bnpl_analysis.common import clean_paths, read_partition, partition_date

def build(root,cutoffs):
    staging,_,files=clean_paths(Path(root),'v1_2')
    consumers=pd.read_parquet(staging/'consumers.parquet',columns=['consumer_id','state','geo_match_status'])
    if consumers.consumer_id.duplicated().any(): raise ValueError('Nonunique consumer dimension')
    region=consumers.set_index('consumer_id').state.where(consumers.set_index('consumer_id').geo_match_status.eq('matched_poa'),'UNKNOWN').fillna('UNKNOWN')
    cutoffs=list(pd.to_datetime(cutoffs)); totals={c:None for c in cutoffs}; first_seen={}
    for path in files:
        date=partition_date(path)
        if date>max(cutoffs): break
        relevant=[c for c in cutoffs if c-pd.Timedelta(days=89)<=date<=c]
        f=read_partition(path,['merchant_abn','consumer_id','dollar_value'] if relevant else ['merchant_abn'])
        for merchant in f.merchant_abn.unique(): first_seen.setdefault(merchant,date)
        if relevant:
            f['customer_region']=f.consumer_id.map(region).fillna('UNKNOWN')
            sums=f.groupby(['merchant_abn','customer_region']).dollar_value.sum()
            for c in relevant: totals[c]=sums if totals[c] is None else totals[c].add(sums,fill_value=0)
    result={}
    for c in cutoffs:
        exposure=totals[c].rename('exposure_gmv').reset_index(); exposure['cutoff']=c
        seen=pd.Series({k:v for k,v in first_seen.items() if v<=c},name='first_observed_order_asof')
        result[c]=(seen,exposure)
    return result
