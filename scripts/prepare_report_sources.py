"""Materialise auditable report-source tables and execute their original read queries.

Inputs are the frozen system's durable CSV / evaluation outputs, not an artifact snapshot.
This reporting adapter adds SQLite provenance required by the portable report reader.
Upstream Python metric/model lineage is preserved as source-file paths and checksums.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engines.contracts import save,sha

def run(root,run_id):
    folder=root/'deliverables'/run_id; path=folder/'artifact.json'; before=json.loads(path.read_text()); artifact=json.loads(path.read_text())
    evaluation=json.loads((root/'reports/engines'/run_id/'test_evaluation.json').read_text())
    queries={}; provenance={}
    with sqlite3.connect(folder/'report_sources.sqlite') as db:
        def source_table(name,frame): frame.to_sql(name,db,if_exists='replace',index=False)
        for tag in ('backtest','latest'):
            for suffix in ('overall_top100','five_groups_top10','all_candidate_dispositions'):
                name=tag+'_'+suffix
                f=pd.read_csv(folder/f'{name}.csv',dtype={'merchant_abn':str})
                source_table(name,f)
            queries[tag+'_top100']=f'SELECT * FROM {tag}_overall_top100 ORDER BY global_rank'
            provenance[tag+'_top100']=[folder/f'{tag}_overall_top100.csv']
            config=json.loads((root/'config/seven_engine_contract_v1.json').read_text())
            for i,group in enumerate(config['groups'],1):
                literal=group.replace("'","''")
                queries[f'{tag}_g{i}']=f"SELECT * FROM {tag}_five_groups_top10 WHERE course_group = '{literal}' ORDER BY group_rank"
                provenance[f'{tag}_g{i}']=[folder/f'{tag}_five_groups_top10.csv']
        source_table('frozen_portfolio_metrics',pd.DataFrame([{k:v for k,v in r.items() if k not in ('selected_interval','oracle_solver','baseline_solver')} for r in evaluation['portfolio_metrics']]))
        source_table('frozen_group_metrics',pd.DataFrame([{k:v for k,v in r.items() if k!='selected_interval'} for r in evaluation['group_metrics']]))
        source_table('frozen_interval_metrics',pd.DataFrame(evaluation['interval_checks']['rows']))
        source_table('course_mapping',pd.DataFrame([{'group':g,'category':c} for g,cs in config['groups'].items() for c in cs]))
        queries.update({'evaluation':'SELECT * FROM frozen_portfolio_metrics ORDER BY cutoff, scenario',
            'group_evaluation':'SELECT * FROM frozen_group_metrics ORDER BY cutoff, course_group',
            'coverage':'SELECT * FROM frozen_interval_metrics ORDER BY cutoff, subset',
            'mapping':'SELECT * FROM course_mapping ORDER BY "group", category',
            'disposition':"SELECT 'backtest' AS list, candidate_disposition AS disposition, COUNT(*) AS merchants FROM backtest_all_candidate_dispositions GROUP BY candidate_disposition UNION ALL SELECT 'latest' AS list, candidate_disposition AS disposition, COUNT(*) AS merchants FROM latest_all_candidate_dispositions GROUP BY candidate_disposition ORDER BY list, disposition"})
        for name in ('evaluation','group_evaluation','coverage'): provenance[name]=[root/'reports/engines'/run_id/'test_evaluation.json']
        provenance['mapping']=[root/'config/seven_engine_contract_v1.json']
        provenance['disposition']=[folder/'backtest_all_candidate_dispositions.csv',folder/'latest_all_candidate_dispositions.csv']
        training=json.loads((root/'reports/engines'/run_id/'training.json').read_text())
        source_table('validation_metrics',pd.DataFrame([{'model':c['name'],'cutoff':v['cutoff'],'ndcg':v['ndcg'],'oracle_capture':v['oracle_capture'],'mae':v['mae'],'replaces_baseline':int(c['replacement_gate'])}
            for c in training['candidates'] if c['family_candidate'] for v in c['validation']]))
        queries['models']=(root/'scripts/report_validation_query.sql').read_text()
        provenance['models']=[root/'reports/engines'/run_id/'training.json']
        for name,sql in queries.items():
            frame=pd.read_sql_query(sql,db)
            if name=='models':
                frame['ndcg_display']=frame.mean_validation_ndcg.map(lambda v:f'{v:.6f}')
                frame['replaces_baseline']=frame.replaces_baseline.astype(bool)
            old=pd.DataFrame(before['snapshot']['datasets'][name])
            # Compare all published values by a stable row identity before changing provenance.
            keys=['merchant_abn'] if 'merchant_abn' in frame else ['model'] if name=='models' else ['category'] if name=='mapping' else ['list','disposition'] if name=='disposition' else ['cutoff','scenario'] if name=='evaluation' else ['cutoff','course_group'] if name=='group_evaluation' else ['cutoff','subset']
            left=old.sort_values(keys).reset_index(drop=True); right=frame.sort_values(keys).reset_index(drop=True)
            assert set(left)==set(right) and len(left)==len(right),name
            for field in left:
                if pd.api.types.is_numeric_dtype(left[field]) and pd.api.types.is_numeric_dtype(right[field]):
                    np.testing.assert_allclose(left[field],right[field],rtol=1e-8,atol=1e-8,equal_nan=True,err_msg=f'{name}.{field}')
                else:
                    assert left[field].fillna('').astype(str).tolist()==right[field].fillna('').astype(str).tolist(),(name,field)
            artifact['snapshot']['datasets'][name]=json.loads(frame.to_json(orient='records'))
            for collection in (artifact['sources'],artifact['manifest']['sources']):
                source=next(s for s in collection if s['id']==name+'_source')
                source['query']={'sql':sql,'engine':'SQLite','language':'sql','database':'report_sources.sqlite',
                    'description':'Executed read/aggregation from durable frozen course-result files; Python engine lineage remains in the input files.',
                    'input_files':[{'path':str(p.relative_to(root)).replace('\\','/'),'sha256':sha(p)} for p in provenance[name]]}
    # Other narrative, block order, table definitions and chart are unchanged.
    assert before['manifest']['blocks']==artifact['manifest']['blocks']
    assert before['manifest']['tables']==artifact['manifest']['tables']
    assert before['manifest']['charts']==artifact['manifest']['charts']
    save(artifact,path)
    save({'status':'PASS','tables':len(queries),'all_published_values_reconciled':True,'only_report_source_and_equal_value_datasets_changed':True},folder/'report_source_validation.json')
    print('Report-source queries executed and reconciled with all original published rows')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--run-id',required=True); p.add_argument('--root',default='.'); a=p.parse_args(); run(Path(a.root).resolve(),a.run_id)
