"""Train-only preprocessing and bounded tabular Revenue challengers."""
import warnings
import numpy as np
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from .contracts import CATEGORIES, NUMERIC, BINARY, FIELDS, validate_revenue

class Transform:
    def __init__(self, scale=False): self.scale=scale
    def fit(self,x):
        validate_revenue(x)
        self.empty = [k for k in NUMERIC if x[k].isna().all()]
        if self.empty: warnings.warn(f'All-missing training columns filled with fixed zero: {self.empty}')
        self.medians=x[NUMERIC].median().fillna(0)
        self.encoder=OneHotEncoder(handle_unknown='ignore',sparse_output=False,dtype=np.float64).fit(x[CATEGORIES])
        self.scaler=StandardScaler().fit(x[NUMERIC].fillna(self.medians))
        self.columns=NUMERIC+[f'{k}__missing' for k in NUMERIC]+[BINARY]+list(self.encoder.get_feature_names_out(CATEGORIES))
        return self
    def transform(self,x):
        validate_revenue(x)
        values=x[NUMERIC].fillna(self.medians).to_numpy()
        if self.scale: values=self.scaler.transform(x[NUMERIC].fillna(self.medians))
        return np.column_stack([values,x[NUMERIC].isna().astype(int),x[BINARY],self.encoder.transform(x[CATEGORIES])])

class Revenue:
    def __init__(self,kind,**params): self.kind,self.params=kind,params
    def fit(self,x,y):
        validate_revenue(x)
        if self.kind.startswith('trailing'): return self
        self.transformer=Transform(self.kind=='ridge').fit(x)
        if self.kind=='ridge': self.model=Ridge(**self.params)
        else: self.model=HistGradientBoostingRegressor(loss='poisson' if self.kind=='hgb_poisson' else 'squared_error',learning_rate=.05,min_samples_leaf=30,l2_regularization=1,early_stopping=False,random_state=30034,**self.params)
        target=y if self.kind=='hgb_poisson' else np.log1p(y)
        self.model.fit(self.transformer.transform(x),target)
        return self
    def predict(self,x):
        validate_revenue(x)
        if self.kind=='trailing90': return x.hist_revenue_proxy.to_numpy()*28/90
        if self.kind=='trailing28': return x.hist_gmv_last28.to_numpy()*x.take_rate_pct.to_numpy()/100
        p=self.model.predict(self.transformer.transform(x))
        if self.kind!='hgb_poisson': p=np.expm1(p)
        if not np.isfinite(p).all(): raise ValueError('Nonfinite Revenue prediction')
        return np.maximum(0,p)

def candidates():
    out=[('trailing90',{}),('trailing28',{})]+[('ridge',{'alpha':a}) for a in (1,10,100)]
    out += [(kind,{'max_leaf_nodes':leaves,'max_iter':iters}) for kind in ('hgb_log','hgb_poisson') for leaves in (15,31) for iters in (100,250)]
    return out
