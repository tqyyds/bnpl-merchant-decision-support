"""Historical eligibility only; real onboarding checks remain unknown."""
import numpy as np
import pandas as pd
from .contracts import KEYS, VERSION, POLICY, unique

def evaluate(frame, master_ids):
    unique(frame); out=frame[KEYS].copy()
    rules={'MISSING_MASTER':~frame.merchant_abn.isin(master_ids),
           'NO_RECENT_ORDERS':~frame.hist_orders.ge(1), 'NO_ACTIVE_DAYS':~frame.hist_active_days.ge(1),
           'INVALID_TAKE_RATE':~(np.isfinite(frame.take_rate_pct)&frame.take_rate_pct.gt(0)&frame.take_rate_pct.le(100))}
    out['eligible']=~pd.DataFrame(rules).any(axis=1)
    out['reason_codes']=[';'.join(k for k,v in rules.items() if bool(v.iloc[i])) or 'PASS' for i in range(len(frame))]
    out['status']=np.where(out.eligible,'HISTORICALLY_ELIGIBLE','INELIGIBLE')
    out['final_onboarding_eligible']=pd.array([pd.NA]*len(out),dtype='boolean')
    out['registry_status']='UNAVAILABLE_SYNTHETIC_ABN'
    out['engine_version']=VERSION; out['policy_version']=POLICY
    return out
