import itertools
import numpy as np
import pandas as pd
import pytest
from engines.contracts import FIELDS, GROUPS, MAPPING, group_recommendations, metrics, ranked
from engines.confidence import Confidence, validation_checks
from engines.eligibility import evaluate
from engines.portfolio import optimise
from engines.strategy import evaluate as strategy
from engines.diversification import concentration

def frame(values):
    n=len(values)
    return pd.DataFrame({'merchant_abn':[str(i).zfill(11) for i in range(n)],'cutoff':pd.Timestamp('2021-06-20'),
        'prediction':values,'merchant_category':['a' if i%2 else 'b' for i in range(n)],'confidence_band':'high'})

def test_contract_mapping():
    assert len(FIELDS)==30 and len(MAPPING)==25 and len(GROUPS)==5
    assert all(not any(t in f for t in ('fraud','signal','probability','future','ctx_')) for f in FIELDS)

@pytest.mark.parametrize('values,capacity', [([0,0,0],2),([5,4,4,4],2),([.000001,0,0],2),([1,2],100),([0,0],0)])
def test_milp_lex_small_exhaustive(values,capacity):
    x=frame(values); selected,report=optimise(x,capacity=capacity)
    possible=[bits for bits in itertools.product([0,1],repeat=len(x)) if sum(bits)<=capacity]
    best=max(np.dot(values,bits) for bits in possible); tol=1e-6+1e-9*abs(best)
    optimal=[bits for bits in possible if abs(np.dot(values,bits)-best)<=tol]
    expected=max(optimal,key=lambda bits:(sum(bits),bits))
    assert report['status']=='OPTIMAL'
    assert selected==x.loc[np.asarray(expected)==1,'merchant_abn'].tolist()

def test_binary_constraints_and_continuous_relaxation_trap():
    x=frame([10,9,8,7]); ids,r=optimise(x,capacity=1.5)
    assert len(ids)==1 and r['revenue']==10  # Continuous relaxation could select 1.5 merchants.
    ids,r=optimise(x,capacity=3,category_cap=1)
    assert len(ids)==2 and r['revenue']==19
    x['confidence_band']='low'; ids,r=optimise(x,low_cap=0)
    assert len(ids)==0

def test_portfolio_invalid_and_timeout():
    with pytest.raises(ValueError): optimise(frame([1,2]),category_cap=-1)
    with pytest.raises(ValueError): optimise(frame([1,-1]))
    with pytest.raises(TimeoutError): optimise(frame([1,2]),time_limit=0)

def test_metrics_position_vs_set():
    x=frame([2,1]); x['target_revenue']=[1,2]
    a=metrics(x,k=2); x.prediction=[1,2]; b=metrics(x,k=2)
    assert a['realised_revenue']==b['realised_revenue'] and a['ndcg']<b['ndcg']

def test_group_tops_independent_of_global():
    x=frame(np.arange(60.)); x['merchant_category']=list(MAPPING)[0]
    x.loc[:14,'merchant_category']=list(GROUPS.values())[1][0]
    top=group_recommendations(x)
    assert len(top)==20 and top.merchant_abn.nunique()==20
    assert not set(top.merchant_abn)<=set(ranked(x,k=10).merchant_abn)
    x.loc[0,'merchant_category']='new unknown'
    with pytest.raises(ValueError): group_recommendations(x)

def confidence_inputs():
    x=frame(np.ones(1200)); x['hist_revenue_proxy']=np.tile(np.arange(400.),3)
    x['cutoff']=np.repeat(pd.to_datetime(['2021-06-20','2021-07-18','2021-08-15']),400)
    x['hist_orders']=100; x['hist_active_days']=90; x['hist_days_since_last_order']=0
    oof=x.copy(); oof['target_revenue']=oof.prediction
    return x,oof

def test_confidence_future_invariance_boundaries_and_fallback():
    x,oof=confidence_inputs(); c=Confidence().fit(x,oof)
    first=c.predict(x,x.prediction); changed=x.assign(target_revenue=np.arange(len(x))*1e9)
    pd.testing.assert_frame_equal(first,c.predict(changed,x.prediction))
    assert list(c.bins(c.edges))==list(range(len(c.edges)))
    x.hist_revenue_proxy=0; small=oof.iloc[:20].copy(); small.hist_revenue_proxy=0
    c=Confidence().fit(x,small)
    assert len(c.edges)==1 and all(r['fallback_global'] for r in c.calibration)

def test_selected_subset_coverage_gate():
    x,oof=confidence_inputs(); c=Confidence().fit(x,oof); out=c.predict(x,x.prediction)
    out['prediction']=1.; out['target_revenue']=1.
    assert validation_checks(out)['calibration_status']=='INSUFFICIENT' # 100%, > 5pp off 90%
    out.loc[:119,'target_revenue']=10.
    assert not validation_checks(out)['conservative_scenario_calibrated']

def test_eligibility_all_failures_and_unknown_master():
    x=frame([0]*6).assign(hist_orders=[1,0,1,1,1,1],hist_active_days=[1,0,1,1,1,1],take_rate_pct=[2,2,0,101,np.inf,100])
    result=evaluate(x,set(x.merchant_abn)-{x.merchant_abn[0]})
    assert result.eligible.tolist()==[False,False,False,False,False,True]
    assert 'NO_RECENT_ORDERS;NO_ACTIVE_DAYS'==result.reason_codes.iloc[1]
    assert result.final_onboarding_eligible.isna().all()
    with pytest.raises(ValueError): evaluate(pd.concat([x,x]),set(x.merchant_abn))

def test_strategy_neutral_effective_and_conflicting():
    x=frame([1,2]); out=strategy(x)
    assert out.strategic_score.isna().all() and out.monetary_bonus_aud.eq(0).all()
    p={'name':'p','owner':'test','reason':'fixture only','effective_from':'2021-01-01','effective_to':'2021-12-31','weight':2,'field':'prediction','minimum':0,'maximum':2}
    assert strategy(x,[p]).strategic_score.tolist()==[.5,1.]
    with pytest.raises(ValueError): strategy(x,[p,p])
    p['effective_to']='2021-02-01'; assert strategy(x,[p]).strategic_score.isna().all()

def test_unknown_exposure_denominator():
    c=concentration([50,50]); assert c['hhi']==.5 and c['effective_categories']==2

def test_tcn_causal():
    import torch
    from engines.tcn import Block
    torch.manual_seed(1); model=Block(6,2).eval(); a=torch.rand(2,6,30); b=a.clone(); b[:,:,20:]+=10
    with torch.no_grad(): assert torch.equal(model(a)[:,:,:20],model(b)[:,:,:20])

def test_future_mutation_does_not_choose_groups_or_lists():
    x,oof=confidence_inputs(); c=Confidence().fit(x,oof)
    x['merchant_category']=list(MAPPING)[0]; x['target_revenue']=0.
    before=group_recommendations(x)[['merchant_abn','course_group','group_rank']]
    first=ranked(x).merchant_abn.tolist(); x.target_revenue=np.arange(len(x))*1e8
    assert first==ranked(x).merchant_abn.tolist()
    pd.testing.assert_frame_equal(before,group_recommendations(x)[['merchant_abn','course_group','group_rank']])

def test_fitted_transforms_preserve_binary_and_reject_data_errors():
    from pathlib import Path
    from engines import data
    from engines.revenue import Transform
    if not Path('tables/modeling/rolling_90d_28d_v3/_SUCCESS').exists(): pytest.skip('Restricted v3 data not installed')
    x=data.features('.','train').head(100).copy(); t=Transform(True).fit(x)
    a=t.transform(x); assert np.array_equal(a[:,t.columns.index('hist_no_previous28_activity')],x.hist_no_previous28_activity)
    x.loc[x.index[0],'hist_amount_std']=np.inf
    with pytest.raises(ValueError): t.transform(x)

def test_empty_column_and_unknown_static_category_encoder():
    from engines.revenue import Transform
    from engines import data
    from pathlib import Path
    if not Path('tables/modeling/rolling_90d_28d_v3/_SUCCESS').exists(): pytest.skip('Restricted v3 data not installed')
    x=data.features('.','train').head(3).copy()
    x.hist_orders=1; x.hist_orders_log1p=np.log1p(1); x.hist_amount_std=np.nan; x.hist_amount_cv=np.nan
    with pytest.warns(UserWarning,match='All-missing'): t=Transform().fit(x)
    assert t.medians['hist_amount_std']==0
    x.revenue_level='UNSEEN_VALID_TAG'; assert np.isfinite(t.transform(x)).all()
