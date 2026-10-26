"""Binary MILP with sequential revenue/cardinality/ID objectives."""
import time
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from .risk_policy import RiskPolicyError, portfolio_risk_constraints

ATOL=1e-6
RTOL=1e-9

def optimise(frame,score='prediction',capacity=100,category_cap=None,low_cap=None,time_limit=60,risk_policy=None):
    if frame.merchant_abn.duplicated().any(): raise ValueError('Duplicate merchant in portfolio universe')
    f=frame.sort_values('merchant_abn').reset_index(drop=True)
    revenue=f[score].to_numpy(dtype=float); n=len(f)
    if not np.isfinite(revenue).all() or (revenue<0).any(): raise ValueError('Invalid portfolio objective')
    if capacity<0 or (category_cap is not None and category_cap<0) or (low_cap is not None and low_cap<0): raise ValueError('Invalid capacity')
    if not n:
        if risk_policy is not None: return [],{'status':'INVALID_RISK_INPUTS','reason':'Risk-constrained universe cannot be empty'}
        return [],{'status':'OPTIMAL','revenue':0.,'count':0,'gap':0.,'lex_method':'empty'}
    rows=[np.ones(n)]; lower=[-np.inf]; upper=[capacity]
    if category_cap is not None:
        for category in sorted(f.merchant_category.unique()):
            rows.append(f.merchant_category.eq(category).to_numpy(dtype=float)); lower.append(-np.inf); upper.append(category_cap)
    if low_cap is not None:
        rows.append(f.confidence_band.isin(['low','unresolved']).to_numpy(dtype=float)); lower.append(-np.inf); upper.append(low_cap)
    risk = None
    if risk_policy is not None:
        try:
            risk = portfolio_risk_constraints(f, risk_policy)
        except RiskPolicyError as error:
            return [],{'status':'INVALID_RISK_INPUTS','reason':str(error)}
        for row,limit in zip(risk['rows'],risk['upper']):
            rows.append(row); lower.append(-np.inf); upper.append(limit)
    A=np.asarray(rows); lower=np.asarray(lower); upper=np.asarray(upper)
    bounds_lo=np.zeros(n); bounds_hi=np.ones(n); started=time.monotonic(); calls=0; last=None
    def solve(c,extra=(),lo=None,hi=None):
        nonlocal calls,last
        remaining=time_limit-(time.monotonic()-started)
        if remaining<=0: raise TimeoutError('Lexicographic MILP time budget exhausted')
        constraints=[LinearConstraint(A,lower,upper),*extra]
        calls+=1
        last=milp(c,integrality=np.ones(n,dtype=int),bounds=Bounds(bounds_lo if lo is None else lo,bounds_hi if hi is None else hi),
            constraints=constraints,options={'time_limit':remaining,'mip_rel_gap':0.})
        return last
    def checked(res):
        if res.x is None: return None
        rounded=np.rint(res.x)
        if np.max(np.abs(res.x-rounded))>1e-6 or (rounded<0).any() or (rounded>1).any() or (A@rounded>upper+1e-6).any():
            raise ValueError('Solver incumbent failed binary/feasibility validation')
        return rounded
    first=solve(-revenue); incumbent=checked(first)
    if incumbent is None or first.status!=0:
        return ([] if incumbent is None else f.loc[incumbent==1,'merchant_abn'].tolist()),{'status':'INFEASIBLE' if first.status==2 else 'NOT_PROVEN_OPTIMAL',
            'solver_status':int(first.status),'gap':None if getattr(first,'mip_gap',None) is None else float(first.mip_gap)}
    optimum=float(revenue@incumbent); tolerance=ATOL+RTOL*abs(optimum)
    lock=LinearConstraint(revenue,optimum-tolerance,optimum+tolerance)
    try:
        second=solve(-np.ones(n),[lock]); second_x=checked(second)
        if second.status!=0 or second_x is None: raise TimeoutError('Cardinality optimum not proven')
        count=int(second_x.sum()); incumbent=second_x
        count_lock=LinearConstraint(np.ones(n),count,count)
        # A unique feasible optimum needs no per-ID feasibility solves. Prove uniqueness
        # by forbidding the incumbent set while retaining BOTH locked objectives.
        alternative=solve(np.zeros(n),[lock,count_lock,LinearConstraint(incumbent,-np.inf,count-1)]) if count else None
        if count==0 or (alternative is not None and alternative.status==2):
            method='unique_optimum_proved'
        else:
            if alternative.status not in (0,2): raise TimeoutError('Uniqueness check timed out')
            method='sequential_id_feasibility'
            lo=np.zeros(n); hi=np.ones(n); selected=0
            for i in range(n):
                if selected==count: hi[i:]=0; break
                if n-i==count-selected: lo[i:]=1; selected=count; break
                if incumbent[i]==1:
                    lo[i]=1; selected+=1; continue  # Existing witness proves inclusion feasible.
                trial=lo.copy(); trial[i]=1
                result=solve(np.zeros(n),[lock,count_lock],trial,hi)
                if result.status==0:
                    incumbent=checked(result); lo[i]=1; selected+=1
                elif result.status==2: hi[i]=0
                else: raise TimeoutError('Lexicographic decision not proven')
            incumbent=lo
        value=float(revenue@incumbent)
        if abs(value-optimum)>tolerance+1e-7 or int(incumbent.sum())!=count: raise ValueError('Lexicographic stage damaged earlier objective')
        result={'status':'OPTIMAL','revenue':value,'primary_optimum':optimum,'count':count,'gap':float(first.mip_gap),
            'atol_aud':ATOL,'rtol':RTOL,'lock_tolerance_aud':tolerance,'solver_calls':calls,'lex_method':method}
    except TimeoutError as error:
        result={'status':'NOT_PROVEN_LEX_OPTIMAL','revenue':float(revenue@incumbent),'count':int(incumbent.sum()),
            'gap':None if getattr(last,'mip_gap',None) is None else float(last.mip_gap),'reason':str(error),'solver_calls':calls}
    if risk is not None:
        selected=incumbent==1; selected_loss=float(risk['loss']@incumbent); selected_gmv=float(risk['gmv']@incumbent)
        result['risk']={k:risk[k] for k in ('loss_scenario','amount_budget','rate_budget','risk_model_version','risk_label_version','risk_prediction_as_of')}
        result['risk'].update({'selected_loss_aud':selected_loss,'selected_gmv_aud':selected_gmv,
            'selected_loss_rate':selected_loss/selected_gmv if selected_gmv else None})
    return f.loc[incumbent==1,'merchant_abn'].tolist(),result

SCENARIOS={'primary':{},'category_max30':{'category_cap':30},'category_max20':{'category_cap':20},'low_confidence_max10':{'low_cap':10},'conservative':{}}
