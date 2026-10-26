"""Frozen input, temporal and course segmentation contracts."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from src.bnpl_analysis.feature_contract import SPECS

VERSION = 'seven_engines_v1'
POLICY = 'course_five_groups_v1'
KEYS = ['merchant_abn', 'cutoff']
TRAIN = pd.to_datetime(['2021-06-20','2021-07-18','2021-08-15','2021-09-12','2021-10-10','2021-11-07'])
VALIDATION = pd.to_datetime(['2021-12-05','2022-01-02','2022-01-30'])
TEST = pd.date_range('2022-02-27', periods=8, freq='28D')
FIELDS = [k for k in SPECS if not any(t in k for t in ('signal', 'probability', 'entity_days'))]
CHANNELS = ['daily_gmv','daily_orders','daily_unique_customers','daily_aov','daily_active','daily_revenue_proxy']
CATEGORIES = ['merchant_category','revenue_level']
BINARY = 'hist_no_previous28_activity'
NUMERIC = [k for k in FIELDS if k not in CATEGORIES + [BINARY]]
NULLABLE = {'hist_aov','hist_amount_median','hist_amount_std','hist_repeat_customer_rate','hist_customer_hhi','hist_daily_gmv_cv','hist_orders_per_customer','hist_gmv_per_active_day','hist_days_since_last_order','hist_amount_cv','hist_growth_28d'}
GROUPS = {
 'Home, Garden & Decorative Arts': [
  'antique shops - sales, repairs, and restoration services','art dealers and galleries',
  'equipment, tool, furniture, and appliance rent al and leasing','florists supplies, nursery stock, and flowers',
  'furniture, home furnishings and equipment shops, and manufacturers, except appliances','lawn and garden supply outlets, including nurseries'],
 'Fashion, Personal Care & Accessories': [
  'health and beauty spas','jewelry, watch, clock, and silverware shops','opticians, optical goods, and eyeglasses','shoe shops','watch, clock, and jewelry repair shops'],
 'Digital, Technology & Communications': [
  'cable, satellite, and other pay television and radio services','computer programming , data processing, and integrated systems design services',
  'computers, computer peripheral equipment, and software','digital goods: books, movies, music','telecom'],
 'Mobility & Outdoor': ['bicycle shops - sales and service','motor vehicle supplies and new parts','tent and awning shops'],
 'Culture, Creative, Gifts & Office': ['artist supply and craft shops','books, periodicals, and newspapers','gift, card, novelty, and souvenir shops',
  'hobby, toy and game shops','music shops - musical instruments, pianos, and sheet music','stationery, office supplies and printing and writing paper']}
MAPPING = {category: group for group, categories in GROUPS.items() for category in categories}
assert len(FIELDS) == 30 and len(MAPPING) == sum(map(len, GROUPS.values())) == 25

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(8*1024*1024): h.update(chunk)
    return h.hexdigest()

def save(value, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')

def unique(frame):
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError('Null/duplicate merchant-cutoff key')
    if not frame.merchant_abn.astype(str).str.fullmatch(r'\d{11}').all():
        raise ValueError('Merchant IDs must be canonical 11-digit synthetic strings')

def validate_revenue(frame):
    unique(frame)
    if set(FIELDS) - set(frame): raise ValueError('Incomplete 30-field Revenue contract')
    if frame[CATEGORIES].isna().any().any(): raise ValueError('Missing required master attributes')
    unknown = set(frame.merchant_category) - set(MAPPING)
    if unknown: raise ValueError(f'Unmapped categories: {sorted(unknown)}')
    values = frame[NUMERIC + [BINARY]].astype(float)
    if np.isinf(values.to_numpy()).any(): raise ValueError('Non-finite raw Revenue value')
    if values[[k for k in values if k not in NULLABLE]].isna().any().any(): raise ValueError('Unexpected raw null')
    if (values.drop(columns='hist_growth_28d') < 0).any().any(): raise ValueError('Illegal negative value')
    if not frame.take_rate_pct.between(0,100,inclusive='right').all(): raise ValueError('Invalid take rate')
    if not frame[BINARY].isin([0,1]).all(): raise ValueError('Invalid binary value')
    if not frame.hist_orders.ge(1).all(): raise ValueError('No-history rows cannot enter a model')
    structural = {'hist_amount_std':frame.hist_orders.lt(2),'hist_amount_cv':frame.hist_orders.lt(2),
                  'hist_growth_28d':frame.hist_gmv_previous28.eq(0)}
    for field in NULLABLE:
        permitted=structural.get(field,pd.Series(False,index=frame.index))
        if (frame[field].isna() & ~permitted).any(): raise ValueError(f'Unexpected non-structural null: {field}')
    if not frame.hist_active_days.between(1,90).all() or not frame.hist_days_since_last_order.between(0,89).all():
        raise ValueError('Activity outside inclusive 90-day history')
    for field in ('hist_gmv','hist_orders','hist_unique_customers','hist_revenue_proxy'):
        if not np.allclose(frame[field+'_log1p'],np.log1p(frame[field]),rtol=1e-10,atol=1e-10): raise ValueError('Log formula mismatch')
    if 'history_start' in frame and not (pd.to_datetime(frame.cutoff)-pd.to_datetime(frame.history_start)).dt.days.eq(89).all():
        raise ValueError('Wrong inclusive historical window')

def ranked(frame, score='prediction', k=100):
    return frame.sort_values([score,'merchant_abn'], ascending=[False,True], kind='stable').head(k)

def group_recommendations(frame):
    unique(frame)
    result = frame.copy(); result['course_group'] = result.merchant_category.map(MAPPING)
    if result.course_group.isna().any(): raise ValueError('Unmapped course category')
    outputs = []
    for (_, _), group in result.groupby(['cutoff','course_group'], sort=True):
        top = ranked(group, k=10).copy(); top['group_rank'] = np.arange(1,len(top)+1); outputs.append(top)
    return pd.concat(outputs,ignore_index=True) if outputs else result

def metrics(frame, score='prediction', k=100):
    top = ranked(frame, score, k); oracle = ranked(frame, 'target_revenue', k)
    discounts = 1/np.log2(np.arange(2,len(top)+2))
    ideal = float(np.dot(oracle.target_revenue, discounts))
    actual = float(top.target_revenue.sum()); best = float(oracle.target_revenue.sum())
    return {'rows':len(frame), 'selected':len(top), 'ndcg':float(np.dot(top.target_revenue,discounts)/ideal) if ideal else 1.,
            'realised_revenue':actual, 'oracle_capture':actual/best if best else 1.,
            'mae':float(np.mean(np.abs(frame[score]-frame.target_revenue)))}

def metric_rows(frame, score='prediction', k=100):
    return [{'cutoff':str(pd.Timestamp(c).date()), **metrics(g,score,k)} for c,g in frame.groupby('cutoff',sort=True)]
