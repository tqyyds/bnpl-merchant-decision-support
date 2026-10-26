"""Explicit development -> freeze -> predict -> score state machine."""
import argparse
import json
import pickle
import subprocess
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from . import data, eligibility, risk, strategy, context
from .contracts import KEYS,VERSION,POLICY,MAPPING,CHANNELS,FIELDS,unique,ranked,group_recommendations,metrics,save,sha
from .confidence import Confidence,validation_checks,coverage
from .portfolio import optimise,SCENARIOS
from .diversification import portfolio_diagnostics,marginal_concentration

def now(): return datetime.now(timezone.utc).isoformat()

def inventory(paths,base):
    return {str(p.relative_to(base)).replace('\\','/'):sha(p) for p in sorted(paths) if p.is_file()}

def check_hashes(base,hashes):
    for file,digest in hashes.items():
        if sha(base/file)!=digest: raise ValueError(f'Frozen artifact modified: {file}')

def engine_output(out,engine,status='READY'):
    unique(out); out=out.copy(); out['engine_version']=VERSION+'/'+engine; out['policy_version']=POLICY
    if 'status' not in out: out['status']=status
    if 'reason_codes' not in out: out['reason_codes']='PASS'
    return out

def predict_system(root,destination,x,all_x,model,confidence,conservative=True):
    """No labels accepted. Save recommendations before any outcome scoring."""
    destination.mkdir(parents=True,exist_ok=False)
    masters=pd.read_parquet(root/'tables/staging/v1_2/merchant_master.parquet')
    decision=eligibility.evaluate(all_x,set(masters.merchant_abn))
    eligible_keys=decision.loc[decision.eligible,KEYS]
    if set(map(tuple,eligible_keys.to_numpy()))!=set(map(tuple,x[KEYS].to_numpy())): raise ValueError('Eligibility and model universe differ')
    p=model.predict(x,data.sequence(root,x)) if hasattr(model,'members') else model.predict(x)
    output=x.copy(); output['prediction']=p; output['course_group']=output.merchant_category.map(MAPPING)
    components={'revenue':x[KEYS].assign(prediction=p), 'eligibility':decision,'confidence':confidence.predict(x,p),
        'risk':risk.evaluate(x),'strategic_fit':strategy.evaluate(x)}
    for name in ('confidence','strategic_fit'):
        output=output.merge(components[name],on=KEYS,validate='one_to_one')
    risk_extras=[k for k in components['risk'] if k not in output or k in KEYS]
    output=output.merge(components['risk'][risk_extras],on=KEYS,validate='one_to_one')
    output=output.merge(masters[['merchant_abn','merchant_name']],on='merchant_abn',validate='many_to_one')
    context_by_date=context.build(root,sorted(output.cutoff.unique()))
    dispositions=[]; exposures=[]; selections=[]; diagnostics=[]; audits=[]; groups=group_recommendations(output)
    marginal=[]
    for cutoff,g in output.groupby('cutoff',sort=True):
        first,exposure=context_by_date[pd.Timestamp(cutoff)]; exposures.append(exposure)
        audit=all_x.loc[all_x.cutoff.eq(cutoff)].merge(decision,on=KEYS,validate='one_to_one')
        audit['first_observed_order_asof']=audit.merchant_abn.map(first)
        audit['candidate_disposition']=np.select([audit.eligible,audit.first_observed_order_asof.notna()],['eligible_recent_history','inactive_recent_window'],default='never_observed_asof')
        audit=audit.merge(masters[['merchant_abn','merchant_name']],on='merchant_abn',validate='one_to_one')
        unknown=first.loc[~first.index.isin(masters.merchant_abn)].rename_axis('merchant_abn').reset_index()
        unknown['cutoff']=cutoff; unknown['eligible']=False; unknown['candidate_disposition']='missing_master'; unknown['reason_codes']='MISSING_MASTER'
        dispositions.append(pd.concat([audit,unknown],ignore_index=True))
        for scenario,kwargs in SCENARIOS.items():
            if scenario=='conservative' and not conservative: continue
            ids,info=optimise(g,'lower' if scenario=='conservative' else 'prediction',**kwargs)
            if info['status']!='OPTIMAL':
                save(info,destination/f'solver_failure_{pd.Timestamp(cutoff).date()}_{scenario}.json')
                raise RuntimeError('Portfolio optimality not proven; inspect retained solver report')
            selected=g.loc[g.merchant_abn.isin(ids)].copy()
            selected=ranked(selected,'lower' if scenario=='conservative' else 'prediction',len(selected)).copy()
            selected['global_rank']=np.arange(1,len(selected)+1); selected['scenario']=scenario
            selections.append(selected)
            audits.append({'cutoff':str(pd.Timestamp(cutoff).date()),'scenario':scenario,**info})
            diagnostics.append({'cutoff':str(pd.Timestamp(cutoff).date()),'scenario':scenario,**portfolio_diagnostics(selected,exposure)})
            if scenario=='primary': marginal.append(marginal_concentration(g,selected))
        print(f'System predictions saved in memory: {pd.Timestamp(cutoff).date()}',flush=True)
    for name,component in components.items(): engine_output(component,name).to_parquet(destination/f'{name}.parquet',index=False)
    engine_output(pd.concat(marginal),'diversification').to_parquet(destination/'diversification.parquet',index=False)
    portfolios=pd.concat(selections,ignore_index=True)
    # Portfolio engine has one merchant-cutoff row; memberships are Boolean columns.
    membership=output[KEYS].copy()
    for scenario in portfolios.scenario.unique():
        ids=set(map(tuple,portfolios.loc[portfolios.scenario.eq(scenario),KEYS].to_numpy()))
        membership[f'selected_{scenario}']=[tuple(k) in ids for k in membership[KEYS].to_numpy()]
    engine_output(membership,'portfolio').to_parquet(destination/'portfolio.parquet',index=False)
    output.to_parquet(destination/'predictions.parquet',index=False); groups.to_parquet(destination/'group_top10.parquet',index=False)
    portfolios.to_parquet(destination/'portfolios.parquet',index=False)
    pd.concat(dispositions,ignore_index=True).to_parquet(destination/'candidate_dispositions.parquet',index=False)
    pd.concat(exposures,ignore_index=True).to_parquet(destination/'customer_exposures.parquet',index=False)
    save(audits,destination/'solver_audit.json'); save(diagnostics,destination/'diversification_summary.json')
    save({'created_utc':now(),'labels_opened':False,'files':inventory(destination.glob('*.parquet'),destination)},destination/'prediction_lock.json')
    return output

def score_system(root,destination,split):
    lock=json.loads((destination/'prediction_lock.json').read_text()); check_hashes(destination,lock['files'])
    x=pd.read_parquet(destination/'predictions.parquet')
    # First and only outcome access in this function occurs AFTER the prediction lock.
    y=data.labels(root,split,x); labelled=x.merge(y[KEYS+['target_revenue']],on=KEYS,validate='one_to_one')
    portfolios=pd.read_parquet(destination/'portfolios.parquet'); groups=pd.read_parquet(destination/'group_top10.parquet')
    portfolio_metrics=[]; group_metrics=[]; baseline=__import__('engines.revenue',fromlist=['Revenue']).Revenue('trailing90')
    for cutoff,g in labelled.groupby('cutoff',sort=True):
        g=g.copy(); g['baseline_prediction']=baseline.predict(g)
        formal=portfolios.loc[portfolios.cutoff.eq(cutoff)&portfolios.scenario.eq('primary')]
        formal_actual=float(g.loc[g.merchant_abn.isin(formal.merchant_abn),'target_revenue'].sum()); formal_pred=float(formal.prediction.sum())
        for scenario in portfolios.scenario.unique():
            s=portfolios.loc[portfolios.cutoff.eq(cutoff)&portfolios.scenario.eq(scenario)]
            selected=g.loc[g.merchant_abn.isin(s.merchant_abn)]
            kwargs=SCENARIOS[scenario]
            oracle_ids,oracle_info=optimise(g,'target_revenue',**kwargs)
            base_ids,base_info=optimise(g,'baseline_prediction',**kwargs)
            if oracle_info['status']!='OPTIMAL' or base_info['status']!='OPTIMAL': raise RuntimeError('Comparison optimum not proven')
            oracle=float(g.loc[g.merchant_abn.isin(oracle_ids),'target_revenue'].sum())
            actual=float(selected.target_revenue.sum()); base_actual=float(g.loc[g.merchant_abn.isin(base_ids),'target_revenue'].sum())
            m=metrics(g,'lower' if scenario=='conservative' else 'prediction')
            portfolio_metrics.append({'cutoff':str(pd.Timestamp(cutoff).date()),'scenario':scenario,'candidate_rows':len(g),
                'selected':len(selected),'ranking_ndcg_at100_full_universe':m['ndcg'],'mae_aud':m['mae'],
                'realised_revenue_aud':actual,'oracle_capture_same_constraints':actual/oracle if oracle else 1.,
                'baseline_realised_same_constraints_aud':base_actual,'delta_vs_baseline_aud':actual-base_actual,
                'predicted_opportunity_cost_aud':formal_pred-float(selected.prediction.sum()),'realised_opportunity_cost_aud':formal_actual-actual,
                'selected_interval':coverage(selected),'oracle_solver':oracle_info,'baseline_solver':base_info})
        for group,gg in g.groupby('course_group',sort=True):
            top=groups.loc[groups.cutoff.eq(cutoff)&groups.course_group.eq(group)]
            selected=gg.loc[gg.merchant_abn.isin(top.merchant_abn)]; unselected=gg.loc[~gg.merchant_abn.isin(top.merchant_abn)]
            group_metrics.append({'cutoff':str(pd.Timestamp(cutoff).date()),'course_group':group,**metrics(gg,k=10),
                'shortfall':max(0,10-len(top)),'selected_interval':coverage(selected),
                'selected_median_history_revenue':float(selected.hist_revenue_proxy.median()),
                'selected_median_history_orders':float(selected.hist_orders.median()),
                'unselected_median_history_orders':float(unselected.hist_orders.median()) if len(unselected) else None,
                'selected_median_active_day_rate':float(selected.hist_active_day_rate.median()),
                'unselected_median_active_day_rate':float(unselected.hist_active_day_rate.median()) if len(unselected) else None,
                'unselected_median_history_revenue':float(unselected.hist_revenue_proxy.median()) if len(unselected) else None})
    result={'scored_at_utc':now(),'prediction_lock_sha256':sha(destination/'prediction_lock.json'),
        'portfolio_metrics':portfolio_metrics,'group_metrics':group_metrics,'interval_checks':validation_checks(labelled),
        'risk_coverage':[{'cutoff':str(pd.Timestamp(c).date()),'rows':len(g),
            'consumer_observed_share':float(g.hist_consumer_signal_missing.eq(0).mean()),
            'merchant_observed_share':float(g.hist_merchant_signal_missing.eq(0).mean()),
            'review_prompt_50_count':int(g.review_prompt_50.fillna(False).sum()),
            'review_prompt_80_count':int(g.review_prompt_80.fillna(False).sum()),
            'no_probability_evidence_count':int(g.review_prompt_50.isna().sum())} for c,g in labelled.groupby('cutoff')],
        'unsupported_metrics':['fraud classification performance','portfolio 90% joint income guarantee','causal uplift']}
    labelled.to_parquet(destination/'scored_predictions.parquet',index=False)
    save(result,destination/'evaluation.json'); return result

def develop(root,run):
    training=json.loads((run/'training.json').read_text()); champion=training['champion']
    with (run/'models.pkl').open('rb') as f: models=pickle.load(f)
    x=data.features(root,'train'); v=data.features(root,'validation'); all_v=data.features(root,'validation',True)
    calibrators={}; checks={}
    for name in models:
        c=Confidence().fit(x,pd.read_parquet(run/f'oof_{name}.parquet')); calibrators[name]=c
        p=pd.read_parquet(run/f'validation_{name}.parquet'); out=c.predict(v,p.prediction)
        out['prediction']=p.prediction.to_numpy(); out['target_revenue']=data.labels(root,'validation',v).target_revenue.to_numpy()
        checks[name]={'calibrator':c.manifest(),**validation_checks(out)}
    with (run/'confidence.pkl').open('wb') as f: pickle.dump(calibrators[champion],f)
    save(checks,run/'calibration.json')
    # Conservative scenario is a descriptive sensitivity even when calibration fails;
    # it is explicitly flagged and cannot be promoted to a reliable portfolio guarantee.
    predict_system(root,run/'validation_system',v,all_v,models[champion],calibrators[champion],True)
    result=score_system(root,run/'validation_system','validation')
    save({'status':'VALIDATED_NOT_FROZEN','test_labels_opened':False,'conservative_calibration':checks[champion]['calibration_status']},run/'state.json')
    return result

def freeze(root,run):
    if json.loads((run/'state.json').read_text())['status']!='VALIDATED_NOT_FROZEN': raise ValueError('Full validation required')
    tests=subprocess.run([__import__('sys').executable,'-m','pytest','tests/test_seven_engines.py','-q'],cwd=root,capture_output=True,text=True)
    if tests.returncode: raise RuntimeError(tests.stdout+tests.stderr)
    code=list((root/'engines').glob('*.py'))+list((root/'src/bnpl_analysis').glob('*.py'))+list((root/'tests').glob('test_seven_engines.py'))
    policies={'version':POLICY,'mapping':MAPPING,'revenue_fields':FIELDS,'sequence_channels':CHANNELS,'scenarios':SCENARIOS,
        'strategy':'NOT_CONFIGURED','test_use':'score once after prediction locks; no post-test tuning',
        'conservative':'descriptive conservative ranking scenario; calibration warning retained; no joint guarantee'}
    save(policies,run/'policies.json')
    model_files=[run/k for k in ('models.pkl','confidence.pkl','training.json','calibration.json','policies.json')]
    source_files=list((root/'tables/staging/v1_2').rglob('*.parquet'))
    save({'frozen_utc':now(),'test_labels_opened':False,'code':inventory(code,root),'artifacts':inventory(model_files,run),'cleaned_sources':inventory(source_files,root),
        'source_manifest_sha256':sha(data.source(root)/'manifest.json'),'development_test_output':tests.stdout},run/'freeze.json')
    save({'status':'FROZEN','test_labels_opened':False},run/'state.json')

def test_and_latest(root,run):
    freeze_record=json.loads((run/'freeze.json').read_text()); check_hashes(root,freeze_record['code']); check_hashes(run,freeze_record['artifacts']); check_hashes(root,freeze_record['cleaned_sources'])
    if (run/'test_system').exists(): raise ValueError('Test artifacts already exist; never silently rescore')
    with (run/'models.pkl').open('rb') as f: models=pickle.load(f)
    with (run/'confidence.pkl').open('rb') as f: confidence=pickle.load(f)
    champion=json.loads((run/'training.json').read_text())['champion']; model=models[champion]
    x=data.features(root,'test'); all_x=data.features(root,'test',True)
    predict_system(root,run/'test_system',x,all_x,model,confidence,True)
    save({'status':'TEST_PREDICTIONS_LOCKED','test_labels_opened':False},run/'state.json')
    evaluation=score_system(root,run/'test_system','test')
    save({'status':'TEST_SCORED','test_labels_opened':True,'test_scored_at_utc':evaluation['scored_at_utc']},run/'state.json')
    all_latest=data.latest(root); latest=all_latest.loc[all_latest.eligible_history].reset_index(drop=True)
    predict_system(root,run/'latest_system',latest,all_latest,model,confidence,True)
    save({'status':'COMPLETE_MODELLING_AND_RECOMMENDATIONS','test_labels_opened':True,'latest_future_outcome':'UNOBSERVABLE'},run/'state.json')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('stage',choices=['develop','freeze','test']); p.add_argument('--root',default='.'); p.add_argument('--run-id',required=True); a=p.parse_args()
    root=Path(a.root).resolve(); run=root/'artifacts/seven_engines'/a.run_id
    {'develop':develop,'freeze':freeze,'test':test_and_latest}[a.stage](root,run)
