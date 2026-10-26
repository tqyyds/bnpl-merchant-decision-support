"""Optional, date-effective, documented MCDA policies; neutral by default."""
import numpy as np
import pandas as pd
from .contracts import KEYS

def evaluate(x,policies=None):
    out=x[KEYS].copy(); out['strategic_score']=np.nan; out['monetary_bonus_aud']=0.; out['strategic_excluded']=False
    out['strategic_status']='NOT_CONFIGURED'; policies=policies or []
    for policy in policies:
        required={'name','owner','reason','effective_from','effective_to','weight','field','minimum','maximum'}
        if not required<=set(policy) or not policy['owner'] or not policy['reason']: raise ValueError('Incomplete policy provenance')
        if policy['weight']<0 or policy['maximum']<=policy['minimum']: raise ValueError('Invalid MCDA scale/weight')
        if pd.Timestamp(policy['effective_to'])<pd.Timestamp(policy['effective_from']): raise ValueError('Invalid policy interval')
    for cutoff,group in x.groupby('cutoff'):
        active=[p for p in policies if pd.Timestamp(p['effective_from'])<=cutoff<=pd.Timestamp(p['effective_to'])]
        if len({p['name'] for p in active})!=len(active): raise ValueError('Conflicting overlapping policy versions')
        total=sum(p['weight'] for p in active)
        if active and total<=0: raise ValueError('Active weights sum to zero')
        if not active: continue
        score=sum(((group[p['field']]-p['minimum'])/(p['maximum']-p['minimum'])).clip(0,1)*p['weight']/total for p in active)
        out.loc[group.index,'strategic_score']=score
        out.loc[group.index,'strategic_status']=np.where(score.notna(),'CONFIGURED','UNRESOLVED')
    return out
