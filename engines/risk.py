"""Native-grain evidence, never a fitted fraud classifier or monetary loss."""
import numpy as np
from .contracts import KEYS

def evaluate(x):
    fields=[k for k in x if any(s in k for s in ('signal','probability','entity_days'))]
    fields += ['hist_high_value_order_share','hist_high_value_gmv_share','hist_customer_hhi','hist_daily_gmv_cv']
    out=x[KEYS+fields].copy()
    for field in fields:
        if 'probability' in field and not x[field].dropna().between(0,1).all(): raise ValueError('v3 probability must be a fraction')
        out[f'{field}__percentile']=out.groupby('cutoff')[field].rank(method='average',pct=True)
    for kind in ('consumer','merchant'):
        count='hist_consumer_signal_entity_days' if kind=='consumer' else 'hist_merchant_signal_days'
        cov='hist_consumer_signal_coverage' if kind=='consumer' else 'hist_merchant_signal_calendar_coverage'
        rec=f'hist_{kind}_signal_recency_days'
        out[f'{kind}_evidence_reliability']=np.sqrt(x[cov]*np.exp(-x[rec]/28)).where(x[count].gt(0))
    for threshold in (.5,.8):
        # Nullable prompts: no evidence is unknown, never a negative fraud label.
        p=x[['hist_consumer_probability_max','hist_merchant_probability_max']].max(axis=1)
        out[f'review_prompt_{int(threshold*100)}']=p.ge(threshold).astype('boolean').mask(p.isna())
    out['composite_risk_score']=np.nan; out['predicted_loss_aud']=np.nan
    out['risk_status']='EVIDENCE_ONLY_NO_LOSS_LABELS'
    return out
