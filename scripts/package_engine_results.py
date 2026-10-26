"""Export aggregate public evidence and private actual course recommendations.

Run after the frozen system completes. HTML is packaged from canonical artifact.json
by the Data Analytics portable builder; this script never generates a second renderer.
"""
import argparse
import json
import platform
import sqlite3
import sys
import zipfile
from pathlib import Path
import importlib.metadata
import numpy as np
import pandas as pd
import nbformat

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engines.contracts import FIELDS,NUMERIC,CHANNELS,GROUPS,CATEGORIES,BINARY,SPECS,save,sha,ranked
from engines.system import check_hashes

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def rows(frame): return json.loads(frame.to_json(orient='records',date_format='iso'))

def sql_comparison(root,training):
    records=[{'model':c['name'],'cutoff':v['cutoff'],'ndcg':v['ndcg'],'oracle_capture':v['oracle_capture'],
        'mae':v['mae'],'replaces_baseline':int(c['replacement_gate'])} for c in training['candidates'] if c['family_candidate'] for v in c['validation']]
    with sqlite3.connect(':memory:') as connection:
        pd.DataFrame(records).to_sql('validation_metrics',connection,index=False)
        result=pd.read_sql_query((root/'scripts/report_validation_query.sql').read_text(),connection)
    result['replaces_baseline']=result.replaces_baseline.astype(bool)
    return rows(result)

def query_source(root,run_id):
    return {'sql':(root/'scripts/report_validation_query.sql').read_text(),'engine':'SQLite','language':'sql',
        'description':'Mean per-cutoff validation metrics for family-selected candidates; training.json is loaded into the in-memory validation_metrics table.',
        'tables_used':['validation_metrics'],'filters':['family_candidate=true; three pre-test validation cutoffs'],
        'metric_definitions':{'mean_validation_ndcg':'Equal-cutoff mean of linear-AUD-relevance NDCG@100','mean_validation_oracle_capture':'Equal-cutoff mean of realised selected income divided by same-universe oracle income'},
        'input_file':f'reports/engines/{run_id}/training.json'}

def build(root,run_id):
    run=root/'artifacts/seven_engines'/run_id
    if read(run/'state.json')['status']!='COMPLETE_MODELLING_AND_RECOMMENDATIONS': raise ValueError('System not complete')
    freeze=read(run/'freeze.json'); check_hashes(root,freeze['code']); check_hashes(run,freeze['artifacts'])
    training=read(run/'training.json'); evaluation=read(run/'test_system/evaluation.json'); calibration=read(run/'calibration.json')
    public=root/'reports/engines'/run_id; public.mkdir(parents=True,exist_ok=True)
    private=root/'deliverables'/run_id; private.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for candidate in training['candidates']:
        if candidate['family_candidate']:
            summaries.append({'model':candidate['name'],'mean_validation_ndcg':float(np.mean([r['ndcg'] for r in candidate['validation']])),
                'mean_validation_oracle_capture':float(np.mean([r['oracle_capture'] for r in candidate['validation']])),
                'mean_validation_mae_aud':float(np.mean([r['mae'] for r in candidate['validation']])),
                'replaces_baseline':candidate['replacement_gate']})
    summaries=sql_comparison(root,training)
    for file in ('training.json','tcn_oof_training.json','tcn_final_training.json','calibration.json','freeze.json','policies.json','state.json'):
        save(read(run/file),public/file)
    save(evaluation,public/'test_evaluation.json')
    save(read(run/'validation_system/evaluation.json'),public/'validation_evaluation.json')
    save(summaries,public/'model_comparison.json')
    versions={name:importlib.metadata.version(name) for name in ('numpy','pandas','scipy','scikit-learn','pyarrow','torch','pytest','nbformat','nbclient')}
    save({'python':platform.python_version(),'packages':versions,'hardware':'NVIDIA RTX 3070, CUDA; CPU inference', 'training_tcn_epochs':[s['selected_epochs'] for s in read(run/'tcn_final_training.json')]},public/'runtime.json')
    (root/'requirements-engines-lock.txt').write_text('\n'.join(f'{k}=={v}' for k,v in versions.items())+'\n',encoding='utf-8')

    title='BNPL merchant recommendations and frozen evaluation'
    blocks=[]; datasets={}; tables=[]; charts=[]; sources=[]
    def prose(identity,body): blocks.append({'id':identity,'type':'markdown','body':body})
    def table(identity,title,frame,columns,sort,source_path):
        datasets[identity]=rows(frame); sid=identity+'_source'
        sources.append({'id':sid,'label':title,'path':source_path})
        tables.append({'id':identity,'title':title,'dataset':identity,'sourceId':sid,'columns':columns,
            'defaultSort':{'field':sort,'direction':'asc'},'density':'spacious'})
        blocks.append({'id':identity+'_block','type':'table','tableId':identity})
    prose('title','# '+title)
    primary=next(r for r in evaluation['portfolio_metrics'] if r['cutoff']=='2022-02-27' and r['scenario']=='primary')
    prose('summary',f'## Technical summary\n\nThe frozen Revenue winner is **{training["champion"]}**. Three-seed TCN training is complete, but it did not pass the pre-specified validation replacement rule. '
        f'The 27 February 2022 Top-100 realised **AUD {primary["realised_revenue_aud"]:,.2f}** over the following 28 days, capturing **{primary["oracle_capture_same_constraints"]:.2%}** of the same-universe oracle. '
        'Actual course merchant records are listed below for the retrospective cutoff and 26 October 2022. Latest future income is unobservable. '
        '**Empirical intervals are insufficiently calibrated: conservative ranking is a sensitivity, not guaranteed portfolio income.**')
    prose('scope','## Read the income measures as proxies\n\nEach decision is a master merchant at a cutoff with at least one order and one active day during the preceding 90 inclusive days, plus a finite take rate in (0,100]. '
        'Income is GMV × take rate / 100 in AUD, not profit or net fraud-adjusted income. NDCG uses linear income relevance and position discounts; Top-100 income sums the selected set without position weights. '
        'Oracle capture compares with the best same-size, same-constraint eligible set using realised income. Static master attributes are assumed historically available. '
        'The primary cohort has 3,930 model rows and 96 excluded no-recent-history master candidates; all dispositions remain in the private CSVs.')
    prose('model_result','## Extra model complexity did not clear the selection gate\n\nThe bar chart shows mean NDCG across the three validation cutoffs. Exact values and oracle capture are retained in the table. '
        'TCN slightly improves capture over the run rate but has lower NDCG; the pre-agreed multi-metric rule therefore retains the baseline. This is not a significance test and there are only three validation dates.')
    comparison_frame=pd.DataFrame(summaries)
    comparison_frame['ndcg_display']=comparison_frame.mean_validation_ndcg.map(lambda v:f'{v:.6f}')
    table('models','Validation model comparison',comparison_frame,[
        {'field':'model','label':'Model'},{'field':'ndcg_display','label':'Mean NDCG@100'},
        {'field':'mean_validation_oracle_capture','label':'Mean oracle capture','format':'percent'},
        {'field':'mean_validation_mae_aud','label':'Mean MAE (AUD)','format':'number'}],'model',f'reports/engines/{run_id}/model_comparison.json')
    sources[-1]['query']=query_source(root,run_id)
    charts.append({'id':'model_chart','title':'Validation NDCG by model','type':'bar','dataset':'models','sourceId':'models_source',
        'encodings':{'x':{'field':'model','type':'nominal'},'y':{'field':'mean_validation_ndcg','type':'quantitative','label':'Mean NDCG@100'}},
        'options':{'orientation':'horizontal'}})
    blocks.append({'id':'model_chart_block','type':'chart','chartId':'model_chart'})
    prose('methods','## Training and evaluation are separated by time\n\nSix train cutoffs from June to November 2021 supply three expanding outer folds. Hyperparameters and preprocessing use only each training fold. '
        'For final TCN fitting, each seed trains on T1–T5 to choose epochs on T6, reinitialises, and fits all six train cutoffs for that saved count: 34, 42 and 20 epochs. Validation is never merged into final fitting. '
        'The complete system was validated and hashed before eight test predictions and selections were saved; only then were test labels opened. The latest recommendation uses the same frozen system. '
        'The main Revenue input contract has 30 fields; the TCN uses six daily channels over 30 days. Fraud, geography, merchant ID and future fields are excluded from Revenue.')
    overlaps=[]; disposition_summary=[]
    for tag,directory,cutoff in [('backtest','test_system','2022-02-27'),('latest','latest_system','2022-10-26')]:
        d=run/directory; check_hashes(d,read(d/'prediction_lock.json')['files'])
        prediction=pd.read_parquet(d/'predictions.parquet'); prediction=prediction.loc[prediction.cutoff.eq(pd.Timestamp(cutoff))]
        portfolio=pd.read_parquet(d/'portfolios.parquet'); overall=portfolio.loc[portfolio.cutoff.eq(pd.Timestamp(cutoff))&portfolio.scenario.eq('primary')].copy()
        group=pd.read_parquet(d/'group_top10.parquet'); group=group.loc[group.cutoff.eq(pd.Timestamp(cutoff))].copy()
        dispositions=pd.read_parquet(d/'candidate_dispositions.parquet'); dispositions=dispositions.loc[dispositions.cutoff.eq(pd.Timestamp(cutoff))]
        dispositions.to_csv(private/f'{tag}_all_candidate_dispositions.csv',index=False)
        for state,g in dispositions.groupby('candidate_disposition'):
            disposition_summary.append({'list':tag,'disposition':state,'merchants':len(g)})
        ordered=ranked(prediction,k=len(prediction)); global_rank={m:i+1 for i,m in enumerate(ordered.merchant_abn)}
        grouped=prediction.sort_values(['prediction','merchant_abn'],ascending=[False,True]).copy()
        grouped['group_rank']=grouped.groupby('course_group').cumcount()+1
        group_rank=grouped.set_index('merchant_abn').group_rank
        realised=None
        if tag=='backtest':
            scored=pd.read_parquet(d/'scored_predictions.parquet'); scored=scored.loc[scored.cutoff.eq(pd.Timestamp(cutoff))]
            realised=scored.set_index('merchant_abn').target_revenue
        def enrich(f):
            f=f.copy(); f['global_rank']=f.merchant_abn.map(global_rank); f['group_rank']=f.merchant_abn.map(group_rank)
            f['realised_28d_revenue_aud']=f.merchant_abn.map(realised) if realised is not None else np.nan
            f['future_outcome_status']='OBSERVED_BACKTEST_ONLY' if realised is not None else 'UNOBSERVABLE_FUTURE'
            f['recommendation_reason']=[f'Historical revenue AUD {r.hist_revenue_proxy:,.0f}; {int(r.hist_orders):,} orders; {int(r.hist_active_days)}/90 active days; revenue reliability {r.confidence_band}. '
                f'Consumer evidence coverage {r.hist_consumer_signal_coverage:.1%}; merchant evidence coverage {r.hist_merchant_signal_calendar_coverage:.1%}. Onboarding unresolved; synthetic ID.' for r in f.itertuples()]
            keep=['merchant_abn','merchant_name','merchant_category','course_group','global_rank','group_rank','prediction','hist_revenue_proxy',
                'hist_orders','hist_active_days','hist_consumer_signal_coverage','hist_merchant_signal_calendar_coverage','revenue_reliability','confidence_band',
                'lower','upper','realised_28d_revenue_aud','future_outcome_status','recommendation_reason']
            return f[keep]
        overall=enrich(overall); group=enrich(group)
        overall.to_csv(private/f'{tag}_overall_top100.csv',index=False); group.to_csv(private/f'{tag}_five_groups_top10.csv',index=False)
        if len(overall)!=100 or len(group)!=50 or not group.groupby('course_group').size().eq(10).all(): raise ValueError('Course recommendation count mismatch')
        overlap=len(set(overall.merchant_abn)&set(group.merchant_abn)); overlaps.append({'list':tag,'overall_count':100,'group_slots':50,'overlap_merchants':overlap})
        prose(tag+'_intro',f'## {"Backtest: 27 February 2022" if tag=="backtest" else "Latest recommendation: 26 October 2022"}\n\n'
            f'The overall Top-100 and five independent group Top-10 lists share **{overlap} merchants**. Group recommendations come from each complete eligible group, not the overall Top-100 subset. '
            +('Realised income below covers 28 February–27 March 2022 only.' if tag=='backtest' else '**Future 28-day outcomes are not in the source data. No realised income or latest forecast accuracy is claimed.**')+
            ' Names and identifiers are actual supplied course records, not independently verified real-world businesses. Open the adjacent CSV files for every field and the complete candidate dispositions.')
        cols=[{'field':'global_rank','label':'Global rank'},{'field':'merchant_name','label':'Merchant name'},{'field':'merchant_abn','label':'Synthetic ID'},
            {'field':'course_group','label':'Course group'},{'field':'prediction','label':'Predicted 28d AUD','format':'number'},
            {'field':'hist_revenue_proxy','label':'Historical 90d AUD','format':'number'},{'field':'confidence_band','label':'Reliability'},
            {'field':'recommendation_reason','label':'Reasons and limitations'}]
        if tag=='backtest': cols.insert(5,{'field':'realised_28d_revenue_aud','label':'Realised 28d AUD','format':'number'})
        table(tag+'_top100',tag.title()+' overall Top-100',overall,cols,'global_rank',f'deliverables/{run_id}/{tag}_overall_top100.csv')
        for i,(name,categories) in enumerate(GROUPS.items(),1):
            current=group.loc[group.course_group.eq(name)].sort_values('group_rank')
            population=prediction.loc[prediction.course_group.eq(name)]
            selected=population.loc[population.merchant_abn.isin(current.merchant_abn)]; other=population.loc[~population.merchant_abn.isin(current.merchant_abn)]
            prose(f'{tag}_g{i}_narrative',f'## {tag.title()} group {i}: {name}\n\nGrouped by operating activity, not future income. '
                f'Eligible group: {len(population):,} merchants. Selected median historical income is AUD {selected.hist_revenue_proxy.median():,.0f}, '
                f'versus AUD {other.hist_revenue_proxy.median():,.0f} for other group members; median orders are {selected.hist_orders.median():,.0f} versus {other.hist_orders.median():,.0f}. '
                'This comparison describes why a revenue-focused rule favours these merchants; it does not establish causal business quality. Group rank uses the same frozen model and ascending synthetic-ID tie break.')
            columns=[{'field':'group_rank','label':'Group rank'}]+cols
            table(f'{tag}_g{i}',f'{tag.title()} group {i} Top-10',current,columns,'group_rank',f'deliverables/{run_id}/{tag}_five_groups_top10.csv')
    prose('evaluation','## Revenue, coverage and constraint trade-offs remain distinct\n\nThe table covers the primary test and seven subsequent non-overlapping outcome windows. '
        'Repeated merchants and overlapping histories mean these are not independent experimental replications. Constrained comparisons use the same constraints for the historical baseline and oracle. '
        'A negative realised opportunity cost means the constraint happened to improve realised income; it is not forcibly converted into a loss. Conservative ranking uses lower bounds but conveys no joint probability guarantee.')
    eval_rows=pd.DataFrame([{k:v for k,v in r.items() if k not in ('selected_interval','oracle_solver','baseline_solver')} for r in evaluation['portfolio_metrics']])
    table('evaluation','Frozen test and robustness scenarios',eval_rows,[{'field':k,'label':label} for k,label in [
        ('cutoff','Cutoff'),('scenario','Scenario'),('realised_revenue_aud','Realised AUD'),('oracle_capture_same_constraints','Oracle capture'),
        ('delta_vs_baseline_aud','AUD vs same-constraint baseline'),('predicted_opportunity_cost_aud','Predicted opportunity cost AUD'),('realised_opportunity_cost_aud','Realised opportunity cost AUD')]],'cutoff',f'reports/engines/{run_id}/test_evaluation.json')
    prose('group_eval','## Group evaluation uses the complete eligible group\n\nEach group is evaluated against its own oracle Top-10, using the fixed activity-based mapping. '
        'These smaller lists fulfil a separate course requirement and are not combined to create the overall Top-100.')
    group_eval=pd.DataFrame([{k:v for k,v in r.items() if k!='selected_interval'} for r in evaluation['group_metrics']])
    table('group_evaluation','Group Top-10 test results',group_eval,[{'field':k,'label':label} for k,label in [('cutoff','Cutoff'),('course_group','Group'),('rows','Eligible merchants'),('ndcg','NDCG@10'),('realised_revenue','Realised AUD'),('oracle_capture','Group oracle capture')]],'cutoff',f'reports/engines/{run_id}/test_evaluation.json')
    prose('limits','## Uncertainty is material and onboarding remains unresolved\n\nIntervals are empirical marginal intervals, not portfolio coverage guarantees. '
        f'The selected model calibration status is **{calibration[training["champion"]]["calibration_status"]}**. '
        'Fraud observations are sparse and stop before later robustness windows; missing evidence does not mean low fraud risk. No verified fraud labels support classification metrics or predicted monetary loss. '
        'Customer geography describes catchment, not merchant location; UNKNOWN exposure stays in its denominator. Strategic fit is NOT_CONFIGURED with zero monetary bonus. '
        'A historical eligibility pass is not approval to onboard. Static merchant-tag availability is assumed, and synthetic ABNs must not be linked to ABR.')
    interval_rows=pd.DataFrame(evaluation['interval_checks']['rows'])
    table('coverage','Marginal interval coverage by selected subset',interval_rows,[{'field':k,'label':k.replace('_',' ').title()} for k in ['cutoff','subset','rows','coverage','mean_width_aud']],'cutoff',f'reports/engines/{run_id}/test_evaluation.json')
    table('disposition','Complete candidate disposition counts',pd.DataFrame(disposition_summary),[{'field':k,'label':k.title()} for k in ['list','disposition','merchants']],'list',f'deliverables/{run_id}/backtest_all_candidate_dispositions.csv')
    sources[-1]['query']={'description':'Count merchant records by as-of disposition in the backtest and latest private outputs.',
        'tables_used':[f'deliverables/{run_id}/backtest_all_candidate_dispositions.csv',f'deliverables/{run_id}/latest_all_candidate_dispositions.csv']}
    mapping=pd.DataFrame([{'group':group,'category':category} for group,categories in GROUPS.items() for category in categories])
    prose('mapping_rationale','## Five operating-activity groups cover all 25 categories\n\nHome/Garden covers domestic goods, decoration and related services; Fashion/Personal Care covers appearance and accessories; '
        'Digital/Technology covers computing, content and communications; Mobility/Outdoor covers transport equipment and outdoor supplies; Culture/Creative/Gifts/Office covers reading, making, leisure and stationery. '
        'This transparent fixed taxonomy is interpretive rather than an official ANZSIC crosswalk. Every exact normalised category occurs once; source spelling is retained. No test outcome selected these groups.')
    table('mapping','Exact category-to-group mapping',mapping,[{'field':'group','label':'Group'},{'field':'category','label':'Exact normalised category'}],'group','engines/contracts.py')
    prose('next','## Next steps and open questions\n\nProvide this actual report and its CSVs to the tutor through the approved private submission channel. Do not publicly upload merchant-level data. '
        'Before any real onboarding decision, obtain provider compliance decisions and real loss labels. Future work may validate time-stamped merchant attributes, recalibrate intervals using new outcomes, '
        'and evaluate a newly versioned model on genuinely new test dates. Do not retune on this test and still call it untouched. The 26 October recommendation remains a forecast with no observable future result.')
    artifact={'surface':'report','manifest':{'version':1,'surface':'report','title':title,'blocks':blocks,'tables':tables,'charts':charts,'sources':sources},
        'snapshot':{'version':1,'status':'ready','datasets':datasets},'sources':sources}
    save(artifact,private/'artifact.json')
    save({'audience':'technical','delivery':'offline HTML','chart_contract':{'question':'Did a challenger meet the validation selection gate?', 'family':'comparison bar','rows':6,'palette':'single-root preferred','source':'model_comparison.json'},
        'tables_reason':'Actual names, ranked lists, exact group/category lookup, and audit metrics require exact rows.',
        'structure':'Technical summary; definitions before measures; model findings; methods; actual recommendations; evaluation; uncertainty; mapping; next steps/open questions',
        'overlap':overlaps,'html_qa':'Run canonical portable builder; report its receipt.'},private/'report_notes.json')
    (private/'README.txt').write_text('PRIVATE COURSE SUBMISSION\nOpen report.html directly; no Python, training, server or internet required.\nCSVs contain actual course merchant records. Keep synthetic merchant IDs as strings when importing.\nBacktest: 27 February 2022; outcomes: 28 February to 27 March.\nLatest: 26 October 2022; future outcome UNOBSERVABLE.\nAll candidate dispositions are included, including missing master and no recent history.\nDo not upload this folder or ZIP to public GitHub.\n',encoding='utf-8')
    # Reproducible report notebook loads saved aggregate evidence, never labels or names.
    nb=nbformat.v4.new_notebook(); nb.metadata.kernelspec={'display_name':'Python 3','language':'python','name':'python3'}
    nb.cells=[nbformat.v4.new_markdown_cell('# Frozen seven-engine evaluation\n\n## TL;DR\nThe Revenue winner remains the 90-day run rate. TCN has been trained and tested in validation, not adopted. Actual recommendations are in the private tutor package.'),
        nbformat.v4.new_markdown_cell('## Context and methods\nRead saved aggregate evidence only. Six training cutoffs; three validation dates; primary test followed by seven robustness windows. Full system and predictions were frozen before test labels were opened.'),
        nbformat.v4.new_markdown_cell('## Key assumptions\nIncome is a take-rate proxy, static master attributes are assumed as-of, intervals lack joint guarantees, and no fraud loss labels or real onboarding decisions are available.'),
        nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nimport pandas as pd\nroot = Path.cwd()\nif root.name == 'notebooks': root = root.parent\nreport = root / 'reports/engines/"+run_id+"'\ncomparison = pd.DataFrame(json.loads((report / 'model_comparison.json').read_text()))\ncomparison"),
        nbformat.v4.new_markdown_cell('## Results\nCompare positional ranking and set income separately. Test rows are saved evaluations, not a trigger for new predictions or training.'),
        nbformat.v4.new_code_cell("e = json.loads((report / 'test_evaluation.json').read_text())\nportfolio = pd.DataFrame(e['portfolio_metrics'])\nportfolio[['cutoff','scenario','realised_revenue_aud','oracle_capture_same_constraints','realised_opportunity_cost_aud']]"),
        nbformat.v4.new_code_cell("groups = pd.DataFrame(e['group_metrics'])\nassert len(groups) == 40\nassert portfolio.query(\"scenario == 'primary'\").shape[0] == 8\nassert portfolio.selected.eq(100).all()\npd.DataFrame(e['interval_checks']['rows']).head(12)"),
        nbformat.v4.new_markdown_cell('## Takeaways\nInspect actual HTML/CSV lists without rerunning training. Retain calibration warnings and missing fraud evidence. Any future model changes need a new evaluation period.')]
    nbformat.write(nb,root/'notebooks/07_frozen_engine_evaluation.ipynb')
    print(f'Private artifact and CSVs prepared: {private}',flush=True)

def package(root,run_id):
    folder=root/'deliverables'/run_id
    if not (folder/'report.html').is_file(): raise ValueError('Verified report.html is required')
    digest={p.name:sha(p) for p in folder.iterdir() if p.is_file() and p.name!='package_manifest.json'}
    save({'restricted_course_records':True,'files':digest},folder/'package_manifest.json')
    zip_path=root/'deliverables'/f'{run_id}_tutor.zip'
    if zip_path.exists(): raise FileExistsError('Do not overwrite a tutor package')
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(folder.iterdir()):
            if p.is_file(): archive.write(p,p.name)
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None: raise ValueError('Tutor ZIP CRC failed')
    save({'zip_name':zip_path.name,'sha256':sha(zip_path),'bytes':zip_path.stat().st_size,'crc':'PASS','private_only':True},root/'reports/engines'/run_id/'tutor_package_receipt.json')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',default='.'); p.add_argument('--run-id',required=True); p.add_argument('--package',action='store_true'); p.add_argument('--repair-report-provenance',action='store_true'); a=p.parse_args()
    root=Path(a.root).resolve()
    if a.repair_report_provenance:
        path=root/'deliverables'/a.run_id/'artifact.json'; artifact=read(path)
        comparison=sql_comparison(root,read(root/'reports/engines'/a.run_id/'training.json'))
        data_frame=pd.DataFrame(comparison); data_frame['ndcg_display']=data_frame.mean_validation_ndcg.map(lambda v:f'{v:.6f}')
        artifact['snapshot']['datasets']['models']=rows(data_frame)
        for collection in (artifact['sources'],artifact['manifest']['sources']):
            for source in collection:
                if source['id']=='models_source': source['query']=query_source(root,a.run_id)
        save(artifact,path); save(comparison,root/'reports/engines'/a.run_id/'model_comparison.json')
    else:
        (package if a.package else build)(root,a.run_id)
