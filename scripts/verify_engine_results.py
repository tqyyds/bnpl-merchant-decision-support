"""Independent, read-only audit of frozen predictions, lists and aggregate metrics."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engines.contracts import KEYS,GROUPS,MAPPING,save,sha
from engines.system import check_hashes

def run(root,run_id):
    p=root/'artifacts/seven_engines'/run_id
    load=lambda f:json.loads(f.read_text())
    freeze=load(p/'freeze.json'); check_hashes(root,freeze['code']); check_hashes(p,freeze['artifacts'])
    seeds=load(p/'tcn_final_training.json')
    assert [r['seed'] for r in seeds]==[30034,30035,30036]
    for seed in seeds:
        assert len(seed['epoch_selection_train_cutoffs'])==5 and len(seed['refit_cutoffs'])==6
        assert seed['epoch_selection_cutoff']=='2021-11-07' and seed['refit_rows']==23537
        best=max(seed['early_stop_trace'],key=lambda r:r['early_stop_ndcg'])
        assert best['epoch']==seed['selected_epochs']==len(seed['refit_trace'])
    checks=[]
    for stage,count in [('validation_system',3),('test_system',8),('latest_system',1)]:
        d=p/stage; lock=load(d/'prediction_lock.json'); check_hashes(d,lock['files'])
        x=pd.read_parquet(d/'predictions.parquet'); groups=pd.read_parquet(d/'group_top10.parquet'); selected=pd.read_parquet(d/'portfolios.parquet')
        dispositions=pd.read_parquet(d/'candidate_dispositions.parquet')
        assert x.cutoff.nunique()==count and not x.duplicated(KEYS).any()
        assert groups.groupby(['cutoff','course_group']).size().eq(10).all()
        assert set(groups.course_group)==set(GROUPS)
        assert not selected.duplicated(KEYS+['scenario']).any()
        assert selected.groupby(['cutoff','scenario']).size().eq(100).all()
        assert dispositions.loc[dispositions.candidate_disposition.ne('missing_master')].groupby('cutoff').size().eq(4026).all()
        assert (pd.to_datetime(dispositions.first_observed_order_asof.dropna())<=dispositions.loc[dispositions.first_observed_order_asof.notna(),'cutoff']).all()
        assert not dispositions.duplicated(KEYS).any()
        for cutoff,g in x.groupby('cutoff'):
            expected=g.sort_values(['prediction','merchant_abn'],ascending=[False,True]).head(100)
            actual=selected.loc[selected.cutoff.eq(cutoff)&selected.scenario.eq('primary')]
            assert set(expected.merchant_abn)==set(actual.merchant_abn)
            for group,gg in g.groupby('course_group'):
                want=gg.sort_values(['prediction','merchant_abn'],ascending=[False,True]).head(10)
                got=groups.loc[groups.cutoff.eq(cutoff)&groups.course_group.eq(group)]
                assert got.merchant_abn.tolist()==want.merchant_abn.tolist()
            np.testing.assert_allclose(g.prediction,g.hist_revenue_proxy*28/90,rtol=1e-12)
            # Independent formula checks for the accepted 90-day winner.
            np.testing.assert_allclose(g.hist_revenue_proxy,g.hist_gmv*g.take_rate_pct/100,rtol=1e-12)
        for component in ('revenue','eligibility','risk','confidence','strategic_fit','diversification','portfolio'):
            f=pd.read_parquet(d/f'{component}.parquet')
            assert not f.duplicated(KEYS).any()
            assert set(KEYS+['engine_version','policy_version','status','reason_codes'])<=set(f)
        if stage!='latest_system':
            e=load(d/'evaluation.json'); assert pd.Timestamp(lock['created_utc'])<pd.Timestamp(e['scored_at_utc'])
            if stage=='test_system': assert pd.Timestamp(freeze['frozen_utc'])<pd.Timestamp(lock['created_utc'])
            scored=pd.read_parquet(d/'scored_predictions.parquet')
            assert scored.target_revenue.ge(0).all() and not scored.target_revenue.isna().any()
            for row in e['portfolio_metrics']:
                a=selected.loc[selected.cutoff.eq(pd.Timestamp(row['cutoff']))&selected.scenario.eq(row['scenario'])]
                y=scored.loc[scored.cutoff.eq(pd.Timestamp(row['cutoff']))].set_index('merchant_abn').target_revenue
                np.testing.assert_allclose(row['realised_revenue_aud'],y.loc[a.merchant_abn].sum(),rtol=1e-12)
        else:
            assert x.cutoff.eq(pd.Timestamp('2022-10-26')).all()
            assert 'target_revenue' not in x and not (d/'evaluation.json').exists()
        checks.append({'stage':stage,'cutoffs':count,'model_rows':len(x),'group_slots':len(groups),'portfolio_slots':len(selected),'status':'PASS'})
    assert checks[0]['model_rows']==11872 and checks[1]['model_rows']==31444
    result={'assessment':'Share with caveats','status':'PASS','checks':checks,
        'required_caveats':['insufficient empirical interval calibration','no portfolio joint guarantee','synthetic ABN and unverified static as-of attributes','no real fraud losses or onboarding approval','latest future income unavailable'],
        'read_only_audit':True,'freeze_sha256':sha(p/'freeze.json')}
    save(result,root/'reports/engines'/run_id/'independent_validation.json'); print(result)

if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('--run-id',required=True); a.add_argument('--root',default='.'); args=a.parse_args(); run(Path(args.root).resolve(),args.run_id)
