"""Explainable reliability and empirical marginal intervals, not guarantees."""
import numpy as np
import pandas as pd
from .contracts import KEYS, ranked

def equal_cutoff_weights(frame):
    return 1/frame.groupby('cutoff').cutoff.transform('size').to_numpy()

def weighted_quantile(values,weights,q):
    order=np.argsort(values,kind='stable'); v=np.asarray(values)[order]; w=np.asarray(weights)[order]
    if len(v)==0 or not np.isfinite(v).all() or (w<=0).any(): raise ValueError('Invalid weighted quantile sample')
    return float(v[min(np.searchsorted(np.cumsum(w),q*w.sum(),side='left'),len(v)-1)])

class Confidence:
    def fit(self,train,oof):
        w=equal_cutoff_weights(train)
        self.edges=np.unique([weighted_quantile(train.hist_revenue_proxy,w,q) for q in (.25,.5,.75)])
        self.volume_p90=weighted_quantile(np.log1p(train.hist_orders),w,.9)
        residual=np.abs(np.log1p(oof.target_revenue)-np.log1p(oof.prediction))
        ow=equal_cutoff_weights(oof); self.global_q=weighted_quantile(residual,ow,.9)
        groups=self.bins(oof.hist_revenue_proxy); self.quantiles={}; self.calibration=[]
        for b in range(len(self.edges)+1):
            mask=groups==b; subset=oof.loc[mask]
            fallback=len(subset)<200 or subset.cutoff.nunique()<2
            q=self.global_q if fallback else weighted_quantile(residual[mask],equal_cutoff_weights(subset),.9)
            self.quantiles[b]=q
            self.calibration.append({'bin':b,'samples':len(subset),'cutoffs':int(subset.cutoff.nunique()),'fallback_global':fallback,'absolute_log_error_q90':q})
        return self
    def bins(self,historical_revenue):
        values=np.asarray(historical_revenue)
        if not np.isfinite(values).all() or (values<0).any(): raise ValueError('Invalid historical revenue for grouping')
        return np.searchsorted(self.edges,values,side='left')
    def predict(self,x,prediction,complete_partitions=90):
        out=x[KEYS].copy(); out['historical_revenue_bin']=self.bins(x.hist_revenue_proxy)
        q=out.historical_revenue_bin.map(self.quantiles).to_numpy()
        p=np.log1p(np.asarray(prediction)); out['lower']=np.maximum(0,np.expm1(p-q)); out['upper']=np.expm1(p+q)
        volume=np.minimum(np.log1p(x.hist_orders)/self.volume_p90,1) if self.volume_p90>0 else np.zeros(len(x))
        active=x.hist_active_days/90; fresh=np.exp(-x.hist_days_since_last_order/28)
        completeness=np.asarray(complete_partitions)/90
        if np.any(completeness<0) or np.any(completeness>1): raise ValueError('Invalid partition completeness')
        out['revenue_reliability']=(volume*active*fresh*completeness)**.25
        out['confidence_band']=np.select([out.revenue_reliability.isna(),out.revenue_reliability.ge(.8),out.revenue_reliability.ge(.5)],['unresolved','high','medium'],default='low')
        return out
    def manifest(self):
        return {'bin_field':'hist_revenue_proxy','edges':self.edges.tolist(),'boundary_rule':'right closed; duplicate edges merged',
            'volume_train_p90':self.volume_p90,'calibration':self.calibration,'global_q90':self.global_q,
            'interval_type':'90% empirical marginal interval; not a portfolio guarantee'}

def coverage(frame):
    covered=frame.target_revenue.between(frame.lower,frame.upper)
    return {'rows':len(frame),'coverage':float(covered.mean()) if len(frame) else None,
            'mean_width_aud':float((frame.upper-frame.lower).mean()) if len(frame) else None}

def validation_checks(frame):
    rows=[]
    for cutoff,g in frame.groupby('cutoff',sort=True):
        subsets={'all':g,'ordinary_top100':ranked(g),'conservative_top100':ranked(g,'lower')}
        subsets.update({f'historical_bin_{b}':v for b,v in g.groupby('historical_revenue_bin')})
        rows.extend({'cutoff':str(pd.Timestamp(cutoff).date()),'subset':name,**coverage(s)} for name,s in subsets.items())
    mean_all=np.mean([r['coverage'] for r in rows if r['subset']=='all'])
    insufficient=abs(mean_all-.9)>.05 or any(r['coverage']<.8 for r in rows if r['subset'] in ('all','conservative_top100'))
    return {'calibration_status':'INSUFFICIENT' if insufficient else 'EMPIRICALLY_ADEQUATE', 'conservative_scenario_calibrated':not insufficient,'rows':rows}
