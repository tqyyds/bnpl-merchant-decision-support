"""Development-only checks of the complete rolling predictor table."""
from pathlib import Path
import json

import numpy as np
import pandas as pd

from .common import load_config, save_json, markdown_table
from .feature_contract import feature_contract
from .time_split import METADATA
from src.run_artifacts import snapshot_manifest_path, file_hash


def validate_features(frame: pd.DataFrame, predictors: list[str], history_days: int = 90) -> None:
    if set(predictors) != {f['name'] for f in feature_contract()['fields']}:
        raise ValueError('Predictors do not match the complete v3 feature contract')
    if set(frame) != set(METADATA + predictors):
        raise ValueError('Feature schema differs from the declared contract')
    if frame.duplicated(['merchant_abn', 'cutoff']).any():
        raise ValueError('Duplicate merchant-cutoff keys')
    if not frame.eligible_history.all() or not frame.hist_orders.gt(0).all():
        raise ValueError('Model rows must have historical orders')
    if not frame.history_end.eq(frame.cutoff).all():
        raise ValueError('Feature cutoff differs from history end')
    if not (frame.history_end-frame.history_start).dt.days.eq(history_days-1).all():
        raise ValueError('Wrong history duration')
    numeric = frame[predictors].select_dtypes('number')
    if np.isinf(numeric.to_numpy()).any():
        raise ValueError('Infinite feature value')
    for field in feature_contract()['fields']:
        observed = frame[field['name']].dropna()
        if field['unit'] in ('share', 'boolean') and not observed.between(0,1).all():
            raise ValueError(f'Out-of-range fraction: {field["name"]}')
        if field['unit'] in ('AUD','count','days','AUD/day','ratio') and not observed.ge(0).all():
            raise ValueError(f'Negative nonnegative feature: {field["name"]}')
    checks = {
        'hist_revenue_proxy': frame.hist_gmv*frame.take_rate_pct/100,
        'hist_aov': frame.hist_gmv/frame.hist_orders,
        'hist_orders_per_customer': frame.hist_orders/frame.hist_unique_customers,
        'hist_gmv_per_active_day': frame.hist_gmv/frame.hist_active_days,
        'hist_active_day_rate': frame.hist_active_days/history_days,
        'hist_consumer_signal_coverage': frame.hist_consumer_signal_entity_days/frame.hist_customer_entity_days,
        'hist_merchant_signal_calendar_coverage': frame.hist_merchant_signal_days/history_days,
        'hist_growth_28d': frame.hist_gmv_last28/frame.hist_gmv_previous28.replace(0,np.nan)-1,
    }
    for base in ('hist_gmv','hist_orders','hist_unique_customers','hist_revenue_proxy'):
        checks[base+'_log1p'] = np.log1p(frame[base])
    for name, expected in checks.items():
        np.testing.assert_allclose(frame[name], expected, equal_nan=True, rtol=1e-9, atol=1e-9)
    assert frame.hist_unique_customers.le(frame.hist_orders).all()
    assert frame.hist_customer_entity_days.le(frame.hist_orders).all()
    assert frame.hist_consumer_signal_entity_days.le(frame.hist_customer_entity_days).all()
    assert frame.hist_active_days.between(1,history_days).all()
    assert frame.hist_days_since_last_order.between(0,history_days-1).all()
    assert frame.hist_no_previous28_activity.eq(frame.hist_gmv_previous28.eq(0)).all()
    assert frame.hist_amount_std.isna().eq(frame.hist_orders.lt(2)).all()
    for kind, count in [('consumer','hist_consumer_signal_entity_days'),('merchant','hist_merchant_signal_days')]:
        absent = frame[count].eq(0)
        assert frame[f'hist_{kind}_signal_missing'].eq(absent).all()
        for name in frame:
            if name.startswith(f'hist_{kind}_probability_') or name == f'hist_{kind}_signal_recency_days':
                assert frame[name].isna().eq(absent).all()


def run_feature_qa(root: Path, config: dict | None = None) -> dict:
    config = config or load_config(root)
    local = root/'tables/modeling'/config['snapshot_run_id']
    if not (local/'_SUCCESS').exists():
        raise ValueError('Completed snapshot run required')
    manifest = json.loads(snapshot_manifest_path(root, config['snapshot_run_id']).read_text(encoding='utf-8'))
    predictors = manifest['predictor_columns']
    profiles, near_constants, correlations, coverage, frames = [], [], [], [], {}
    for split in ('train','validation'):
        path = local/f'{split}_features.parquet'
        entry = next(e for e in manifest['output_files'] if e['path'] == path.relative_to(root).as_posix())
        if file_hash(path) != entry['sha256']:
            raise ValueError('Input features changed after snapshot completion')
        frame = pd.read_parquet(path)
        validate_features(frame, predictors, config['history_days'])
        frames[split] = frame
        for cutoff, group in frame.groupby('cutoff'):
            date = str(cutoff.date())
            coverage.append({'split':split,'cutoff':date,'rows':len(group),
                             'consumer_signal_missing_pct':float(group.hist_consumer_signal_missing.mean()*100),
                             'merchant_signal_missing_pct':float(group.hist_merchant_signal_missing.mean()*100)})
            for name in predictors:
                col = group[name]
                row = {'split':split,'cutoff':date,'feature':name,'null_pct':float(col.isna().mean()*100),
                       'distinct_nonnull':int(col.nunique())}
                if pd.api.types.is_numeric_dtype(col):
                    row['zero_pct'] = float(col.eq(0).mean()*100)
                    for q in (.01,.5,.99):
                        value = col.quantile(q)
                        row[f'q{q}'] = float(value) if pd.notna(value) else None
                profiles.append(row)
                if col.nunique() <= 1:
                    near_constants.append({'split':split,'cutoff':date,'feature':name})
            corr = group[predictors].select_dtypes('number').corr(method='spearman')
            for i, left in enumerate(corr):
                for right in list(corr)[i+1:]:
                    value = corr.loc[left,right]
                    if pd.notna(value) and abs(value) >= .98:
                        correlations.append({'split':split,'cutoff':date,'left':left,'right':right,'spearman':float(value)})
    drift = []
    for name in predictors:
        train, val = frames['train'][name], frames['validation'][name]
        row = {'feature':name,'train_null_pct':float(train.isna().mean()*100),
               'validation_null_pct':float(val.isna().mean()*100),
               'missingness_change_pp':float((val.isna().mean()-train.isna().mean())*100)}
        if pd.api.types.is_numeric_dtype(train):
            row.update({f'{label}_median':float(series.median()) if series.notna().any() else None
                        for label,series in [('train',train),('validation',val)]})
        drift.append(row)
    output = root/'reports/feature_qa'/config['snapshot_run_id']
    summary = {'status':'PASS','snapshot_run_id':config['snapshot_run_id'],'predictor_count':len(predictors),
               'development_rows':sum(map(len,frames.values())), 'test_feature_or_label_values_read':False,
               'coverage_by_cutoff':coverage,'profiles':profiles,'near_constant_features':near_constants,
               'high_correlation_pairs':correlations,'train_validation_drift':drift,
               'interpretation':'Coverage drift and correlation are diagnostics, not automatic feature deletion or measured fraud rates.'}
    save_json(summary, output/'summary.json')
    contract = feature_contract()
    save_json(contract, output/'feature_contract.json')
    catalogue = pd.DataFrame(contract['fields'])[['name','formula','unit','missing_rule','availability']]
    (output/'feature_catalogue.md').write_text('# Rolling feature contract v3\n\nAll 46 predictors use merchant × cutoff grain. Train-only preprocessing; no target fields.\n\n'+markdown_table(catalogue),encoding='utf-8')
    text = f'''# Feature QA v3 — development only

All {len(predictors)} predictors passed schema, time-window, range, missingness and derived-formula
checks across {summary['development_rows']:,} development rows. Test values were not opened.

Consumer latest is the equal-user mean on the latest observed day. Empty risk evidence remains
missing; a missingness flag is not a fraud label. Full-period P99 flags and ABS context are excluded.

## Coverage by decision date

{markdown_table(pd.DataFrame(coverage).round(3))}

## Interpretation

Merchant fraud is extremely sparse; coverage differs by cutoff. Consumer coverage drift must be
considered when interpreting all-feature versus no-fraud results. `summary.json` includes all 46
feature profiles at each of nine development dates, near-constant fields, absolute Spearman
correlations >=0.98 and train/validation missingness and median comparisons. These descriptive
checks are not significance tests or evidence that any correlated predictor should be deleted.
The complete formula, unit, availability and missing-value rules are in `feature_catalogue.md`.
'''
    (output/'README.md').write_text(text,encoding='utf-8')
    return summary
