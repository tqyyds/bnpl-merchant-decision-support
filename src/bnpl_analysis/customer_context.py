"""Descriptive customer-residence context, kept outside the 46 predictor allow-list."""
import numpy as np
import pandas as pd


AREA_FIELDS = {
    'median_household_income_weekly_aud': 'area_household_income',
    'population_18_39_share': 'area_age18_39_share',
    'irsd_score': 'area_irsd',
    'irsad_score': 'area_irsad',
}
CONTEXT_INPUTS = ['consumer_id','state','poa_code_2021','geo_match_status','seifa_match_status',*AREA_FIELDS]


def context_for_window(history, masters, consumers, first_seen, cutoff, history_days=90):
    """One row per master merchant, including inactive/no-history candidates.

    State/postcode are customer residence, never merchant location. Published 2021 area
    attributes have unverified historical availability and must not enter primary predictors.
    """
    cutoff = pd.Timestamp(cutoff)
    start = cutoff-pd.Timedelta(days=history_days-1)
    history = history.loc[pd.to_datetime(history.order_datetime).between(start,cutoff)].copy()
    history = history.loc[history.merchant_abn.isin(masters.merchant_abn)]
    pairs = history.groupby(['merchant_abn','consumer_id'],observed=True).dollar_value.sum().rename('customer_gmv').reset_index()
    pairs = pairs.merge(consumers[CONTEXT_INPUTS],on='consumer_id',how='left',validate='many_to_one',indicator=True)
    if pairs['_merge'].ne('both').any():
        raise ValueError('Observed customer is absent from cleaned consumer dimension')
    pairs = pairs.drop(columns='_merge')
    all_customers = pairs.groupby('merchant_abn',observed=True).size()
    all_gmv = pairs.groupby('merchant_abn',observed=True).customer_gmv.sum()
    result = masters[['merchant_abn']].copy().set_index('merchant_abn')
    observed = result.index.to_series().map(first_seen)
    # A source-wide earliest date cannot reveal a future first appearance at an earlier cutoff.
    result['first_observed_order_asof'] = pd.to_datetime(observed).where(pd.to_datetime(observed).le(cutoff))
    result['hist_days_since_first_observed_order'] = (cutoff-result.first_observed_order_asof).dt.days
    active = result.index.isin(all_customers.index)
    result['candidate_status'] = np.select(
        [active,result.first_observed_order_asof.notna()],
        ['active_history','inactive_recent_window'],default='no_observed_history')
    result['candidate_eligible_for_primary_model'] = active
    result['ctx_observed_customers'] = all_customers.reindex(result.index,fill_value=0)
    for source,status in [('geo_match_status','matched_poa'),('seifa_match_status','matched')]:
        name = 'geo' if source == 'geo_match_status' else 'seifa'
        matched = pairs.loc[pairs[source].eq(status)]
        numerator = matched.groupby('merchant_abn',observed=True).size().reindex(result.index,fill_value=0)
        gmv = matched.groupby('merchant_abn',observed=True).customer_gmv.sum().reindex(result.index,fill_value=0)
        result[f'ctx_{name}_customer_coverage'] = numerator/all_customers.reindex(result.index).replace(0,np.nan)
        result[f'ctx_{name}_gmv_coverage'] = gmv/all_gmv.reindex(result.index).replace(0,np.nan)
    matched = pairs.loc[pairs.geo_match_status.eq('matched_poa')]
    for field,name in [('state','state'),('poa_code_2021','poa')]:
        by_area = matched.groupby(['merchant_abn',field],observed=True).customer_gmv.sum()
        denominator = by_area.groupby(level='merchant_abn').transform('sum')
        shares = by_area/denominator.replace(0,np.nan)
        result[f'ctx_customer_{name}_gmv_hhi'] = shares.pow(2).groupby(level='merchant_abn').sum()
        result[f'ctx_customer_{name}_count'] = by_area.groupby(level='merchant_abn').size().reindex(result.index,fill_value=0)
    state_gmv = matched.groupby(['merchant_abn','state'],observed=True).customer_gmv.sum().reset_index()
    dominant = state_gmv.sort_values(['merchant_abn','customer_gmv','state'],ascending=[True,False,True]).drop_duplicates('merchant_abn')
    result['ctx_dominant_customer_state'] = dominant.set_index('merchant_abn').state
    for field,name in AREA_FIELDS.items():
        available = pairs.loc[pairs[field].notna()]
        grouped = available.groupby('merchant_abn',observed=True)
        result[f'ctx_{name}_customer_mean'] = grouped[field].mean()
        weighted = available.assign(weighted_value=available[field]*available.customer_gmv)
        result[f'ctx_{name}_gmv_mean'] = (
            weighted.groupby('merchant_abn',observed=True).weighted_value.sum()
            / grouped.customer_gmv.sum().replace(0,np.nan))
        count = grouped.size().reindex(result.index,fill_value=0)
        result[f'ctx_{name}_customer_coverage'] = count/all_customers.reindex(result.index).replace(0,np.nan)
    result['ctx_reference_year'] = 2021
    result['ctx_historical_availability_verified'] = False
    result['cutoff'] = cutoff
    return result.reset_index().sort_values('merchant_abn').reset_index(drop=True)
