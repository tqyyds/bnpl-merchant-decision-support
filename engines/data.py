"""Read-only v1.2/v3 adapters. Labels are accessed separately from predictors."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from src.bnpl_analysis.common import clean_paths, partition_date, read_partition
from src.bnpl_analysis.time_split import features_for_window, READ_COLUMNS
from .contracts import KEYS, CHANNELS, TRAIN, VALIDATION, TEST, unique, validate_revenue, sha, save

def source(root):
    path = Path(root)/'tables/modeling/rolling_90d_28d_v3'
    manifest = json.loads((path/'manifest.json').read_text())
    if manifest['protocol_version'] != 'rolling_snapshot_v3' or manifest['config']['cleaning_run_id'] != 'v1_2':
        raise ValueError('Only completed cleaning v1.2 and rolling v3 are accepted')
    if not (path/'_SUCCESS').exists(): raise ValueError('Unfinished source run')
    for item in manifest['output_files']:
        file=Path(root)/item['path']
        if not file.is_file() or file.stat().st_size!=item['bytes'] or sha(file)!=item['sha256']:
            raise ValueError(f'v3 source checksum mismatch: {item["path"]}')
    return path

def features(root, split, all_candidates=False):
    path = source(root)
    file = path/'all_candidates'/f'{split}_all_candidates.parquet' if all_candidates else path/f'{split}_features.parquet'
    frame = pd.read_parquet(file).sort_values(KEYS).reset_index(drop=True)
    unique(frame)
    if set(pd.to_datetime(frame.cutoff).unique()) != set({'train':TRAIN,'validation':VALIDATION,'test':TEST}[split]):
        raise ValueError('Unexpected cutoff schedule')
    if not all_candidates: validate_revenue(frame)
    return frame

def labels(root, split, x):
    y = pd.read_parquet(source(root)/f'{split}_labels.parquet')
    unique(y)
    out = x[KEYS].merge(y,on=KEYS,how='left',validate='one_to_one')
    if not np.isfinite(out.target_revenue).all() or not out.target_revenue.ge(0).all(): raise ValueError('Invalid labels')
    if not (pd.to_datetime(out.label_start)-pd.to_datetime(out.cutoff)).dt.days.eq(1).all(): raise ValueError('Invalid label start')
    if not (pd.to_datetime(out.label_end)-pd.to_datetime(out.cutoff)).dt.days.eq(28).all(): raise ValueError('Invalid label end')
    return out

def sequence(root, x):
    """Migrated from revenue engine 42d6b66; ordered to match tabular keys exactly."""
    _,_,files = clean_paths(Path(root),'v1_2')
    partitions = {partition_date(p):p for p in files}
    out = np.zeros((len(x),30,6),dtype=np.float32)
    for cutoff, group in x.groupby('cutoff',sort=True):
        dates = pd.date_range(pd.Timestamp(cutoff)-pd.Timedelta(days=29),cutoff)
        for step,date in enumerate(dates):
            if date not in partitions: raise ValueError(f'Missing source partition: {date}')
            f = read_partition(partitions[date],['merchant_abn','user_id','dollar_value'])
            daily = f.groupby('merchant_abn',observed=True).agg(daily_gmv=('dollar_value','sum'),daily_orders=('dollar_value','size'),daily_unique_customers=('user_id','nunique'))
            daily = daily.reindex(group.merchant_abn,fill_value=0)
            daily['daily_aov'] = (daily.daily_gmv/daily.daily_orders.replace(0,np.nan)).fillna(0)
            daily['daily_active'] = daily.daily_orders.gt(0).astype(int)
            daily['daily_revenue_proxy'] = daily.daily_gmv.to_numpy()*group.take_rate_pct.to_numpy()/100
            out[group.index.to_numpy(),step,:] = daily[CHANNELS].to_numpy()
        print(f'Sequences ready: {pd.Timestamp(cutoff).date()} / {len(group)} merchants',flush=True)
    if not np.isfinite(out).all() or (out<0).any(): raise ValueError('Invalid sequence values')
    return out

def latest(root):
    staging,_,files = clean_paths(Path(root),'v1_2')
    cutoff = pd.Timestamp('2022-10-26'); start = cutoff-pd.Timedelta(days=89)
    selected = [p for p in files if start <= partition_date(p) <= cutoff]
    if len(selected)!=90: raise ValueError('Incomplete latest history')
    history = pd.concat([read_partition(p,READ_COLUMNS) for p in selected],ignore_index=True)
    return features_for_window(history,pd.read_parquet(staging/'merchant_master.parquet'),cutoff,90,
        pd.read_parquet(staging/'fraud/consumer_daily.parquet'),pd.read_parquet(staging/'fraud/merchant_daily.parquet'))
