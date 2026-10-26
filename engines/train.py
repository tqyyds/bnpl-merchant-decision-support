"""Development-only candidate training. Never accesses test features or labels."""
import argparse
import json
import os
import pickle
from pathlib import Path
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from . import data
from .contracts import KEYS, FIELDS, TRAIN, VERSION, metric_rows, save, sha
from .revenue import Revenue, candidates

def mean(rows,key): return float(np.mean([r[key] for r in rows]))

def run(root,run_id):
    root=Path(root); dest=root/'artifacts/seven_engines'/run_id
    dest.mkdir(parents=True,exist_ok=False)
    save({'status':'IN_PROGRESS','test_labels_opened':False},dest/'state.json')
    x=data.features(root,'train'); v=data.features(root,'validation')
    y=data.labels(root,'train',x).target_revenue.to_numpy(); vy=data.labels(root,'validation',v).target_revenue.to_numpy()
    models={}; reports=[]; oof={}; validation={}
    for number,(kind,params) in enumerate(candidates()):
        name=kind+'_'+str(number); rows=[]; preds=[]
        for j in (3,4,5):
            fit=x.cutoff.lt(TRAIN[j]).to_numpy(); hold=x.cutoff.eq(TRAIN[j]).to_numpy()
            model=Revenue(kind,**params).fit(x.loc[fit],y[fit]); p=model.predict(x.loc[hold])
            f=x.loc[hold,KEYS+['hist_revenue_proxy']].copy(); f['target_revenue']=y[hold]; f['prediction']=p
            rows.extend(metric_rows(f)); preds.append(f)
        model=Revenue(kind,**params).fit(x,y); models[name]=model; oof[name]=pd.concat(preds)
        f=v[KEYS+['hist_revenue_proxy']].copy(); f['prediction']=model.predict(v); f['target_revenue']=vy
        validation[name]=f
        reports.append({'name':name,'kind':kind,'parameters':params,'train_oof':rows,'validation':metric_rows(f)})
        print(f'{name}: OOF NDCG={mean(rows,"ndcg"):.6f}',flush=True)
    # Select one hyperparameter configuration per family using train OOF only.
    selected=[]
    for family in ('trailing90','trailing28','ridge','hgb_log','hgb_poisson'):
        options=[r for r in reports if r['kind']==family]
        selected.append(sorted(options,key=lambda r:(-mean(r['train_oof'],'ndcg'),-mean(r['train_oof'],'oracle_capture'),r['name']))[0]['name'])
    save(reports,dest/'tabular_experiments.json')
    with (dest/'tabular_checkpoint.pkl').open('wb') as f: pickle.dump((models,reports,oof,validation,selected),f)
    s=data.sequence(root,x); vs=data.sequence(root,v)
    np.save(dest/'train_sequences.npy',s); np.save(dest/'validation_sequences.npy',vs)
    from .tcn import Ensemble
    parts=[]; evidence=[]
    for j in (3,4,5):
        fit=x.cutoff.lt(TRAIN[j]).to_numpy(); hold=x.cutoff.eq(TRAIN[j]).to_numpy()
        model=Ensemble().fit(x.loc[fit],y[fit],s[fit]); p=model.predict(x.loc[hold],s[hold])
        f=x.loc[hold,KEYS+['hist_revenue_proxy']].copy(); f['prediction']=p; f['target_revenue']=y[hold]; parts.append(f)
        evidence.append({'outer_cutoff':str(TRAIN[j].date()),'seeds':model.evidence})
        save(evidence,dest/'tcn_oof_training.json')
    model=Ensemble().fit(x,y,s); models['tcn']=model; oof['tcn']=pd.concat(parts)
    f=v[KEYS+['hist_revenue_proxy']].copy(); f['prediction']=model.predict(v,vs); f['target_revenue']=vy
    validation['tcn']=f; selected.append('tcn')
    reports.append({'name':'tcn','kind':'tcn','parameters':{'seeds':[30034,30035,30036]},'train_oof':metric_rows(oof['tcn']),'validation':metric_rows(f)})
    save(model.evidence,dest/'tcn_final_training.json')
    base=next(r for r in reports if r['kind']=='trailing90'); eligible=[]
    for r in reports:
        r['family_candidate']=r['name'] in selected
        r['replacement_gate']=r['family_candidate'] and mean(r['validation'],'ndcg')>=mean(base['validation'],'ndcg')+.001 and mean(r['validation'],'oracle_capture')>=mean(base['validation'],'oracle_capture') and sum(a['ndcg']>b['ndcg'] for a,b in zip(r['validation'],base['validation']))>=2
        if r['replacement_gate']: eligible.append(r)
    champion=sorted(eligible,key=lambda r:(-mean(r['validation'],'ndcg'),-mean(r['validation'],'oracle_capture'),r['name']))[0]['name'] if eligible else base['name']
    for name in selected:
        oof[name].to_parquet(dest/f'oof_{name}.parquet',index=False)
        validation[name].drop(columns='target_revenue').to_parquet(dest/f'validation_{name}.parquet',index=False)
    with (dest/'models.pkl').open('wb') as f: pickle.dump({k:models[k] for k in selected},f)
    result={'version':VERSION,'champion':champion,'candidates':reports,'final_fit':'six train cutoffs only','test_labels_opened':False,
        'model_sha256':sha(dest/'models.pkl'),'input_fields':FIELDS,'encoded_columns':{k:m.transformer.columns for k,m in models.items() if hasattr(m,'transformer')},
        'source_manifest_sha256':sha(data.source(root)/'manifest.json')}
    save(result,dest/'training.json'); save({'status':'TRAINED_NOT_FROZEN','test_labels_opened':False},dest/'state.json')
    print(f'Training complete; champion={champion}',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',default='.'); parser.add_argument('--run-id',required=True); args=parser.parse_args()
    with threadpool_limits(limits=4): run(args.root,args.run_id)
