"""Descriptive exposure diagnostics; customer residence is not merchant location."""
import numpy as np
import pandas as pd
from .contracts import KEYS

def concentration(values):
    values=np.asarray(values,dtype=float)
    if not np.isfinite(values).all() or (values<0).any(): raise ValueError('Invalid exposure weights')
    total=values.sum()
    if total==0: return {'hhi':None,'entropy':None,'effective_categories':None,'shares':[]}
    shares=values/total; positive=shares[shares>0]; entropy=float(-(positive*np.log(positive)).sum())
    return {'hhi':float(np.dot(shares,shares)),'entropy':entropy,'effective_categories':float(np.exp(entropy)),'shares':shares.tolist()}

def portfolio_diagnostics(frame,exposures=None):
    by=frame.groupby('merchant_category').prediction.sum()
    result={'category_predicted_revenue':concentration(by),'categories':by.index.tolist(),'geography_role':'customer catchment only'}
    if exposures is not None:
        selected=exposures.loc[exposures.merchant_abn.isin(frame.merchant_abn)]
        by_area=selected.groupby('customer_region').exposure_gmv.sum()
        result['customer_region_all_gmv_including_UNKNOWN']=concentration(by_area)
        result['customer_regions']=by_area.index.tolist()
    return result

def marginal_concentration(candidates,selected):
    """Change in category HHI from adding each merchant to an existing portfolio."""
    base=selected.groupby('merchant_category').prediction.sum(); before=concentration(base)['hhi'] or 0.
    output=candidates[KEYS].copy(); deltas=[]
    for row in candidates.itertuples():
        after=base.copy(); after.loc[row.merchant_category]=after.get(row.merchant_category,0)+row.prediction
        deltas.append((concentration(after)['hhi'] or 0.)-before)
    output['marginal_category_hhi']=deltas
    return output
