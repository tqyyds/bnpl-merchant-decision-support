"""Read-only acceptance checks; publish only aggregate validation evidence."""
from __future__ import annotations

import importlib.metadata
import hashlib
import json
from pathlib import Path
import re
import sys
import argparse

import nbformat
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_etl_outputs import validate as validate_etl
from src.bnpl_analysis.common import clean_paths, load_config, partition_date, read_partition, save_json
from src.bnpl_analysis.time_split import METADATA, snapshot_schedule
from src.bnpl_analysis.baselines import ranking_metrics, top_k_stability
from src.run_artifacts import etl_manifest_path, snapshot_manifest_path, verify_baseline_freeze


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate(root: Path, config_path: Path | None = None,
             cleaning_run_id: str | None = None, baseline_config_path: Path | None = None) -> dict:
    if not __debug__:
        raise RuntimeError("Run validation without Python's -O option")
    config = load_config(root, config_path, cleaning_run_id)
    run_id = config['cleaning_run_id']
    etl = validate_etl(root, run_id)
    reference_id = config['cleaning_reference_run_id']
    accepted = json.loads((root / f'reports/etl/{reference_id}_manifest.json').read_text(encoding='utf-8'))
    reproduced = json.loads(etl_manifest_path(root, run_id).read_text(encoding='utf-8'))
    for key in ['source_checks', 'policy', 'outputs', 'transaction_contract']:
        assert accepted[key] == reproduced[key], f'Contributor reproduction mismatch: {key}'

    staging, _, files = clean_paths(root, run_id)
    masters = pd.read_parquet(staging / 'merchant_master.parquet')
    known = set(masters.merchant_abn)
    eda = json.loads((root / 'reports/eda' / config['analysis_run_id'] / 'summary.json').read_text(encoding='utf-8'))
    historical = [p for p in files if partition_date(p) <= pd.Timestamp(config['eda_end'])]
    assert eda['historical_orders'] == sum(pq.ParquetFile(p).metadata.num_rows for p in historical)
    assert eda['historical_days'] == len(historical)
    assert eda['end'] == config['eda_end']
    assert pd.Timestamp(eda['end']) < pd.Timestamp(config['protected_outcome_start'])

    manifest = json.loads(snapshot_manifest_path(root, config['snapshot_run_id']).read_text(encoding='utf-8'))
    assert manifest['config'] == config
    assert manifest['protocol_version'] == 'rolling_snapshot_v3'
    assert not manifest['model_trained'] and not manifest['preprocessing_fitted']
    assert manifest['eligible_history_enforced_in_model_files']
    assert manifest['native_fraud_grain_features']
    schedule = snapshot_schedule(str(partition_date(files[0]).date()), manifest['source_end'], config)
    assert (schedule.label_start > schedule.history_end).all()
    assert (schedule.label_start.iloc[1:].reset_index(drop=True) > schedule.label_end.iloc[:-1].reset_index(drop=True)).all()
    development = schedule.loc[~schedule.split.eq('test')]
    protected = schedule.loc[schedule.split.eq('test')]
    assert development.label_end.max() < pd.Timestamp(config['protected_outcome_start'])
    assert protected.label_start.min() == pd.Timestamp(config['protected_outcome_start'])
    assert protected.loc[protected.evaluation_role.eq('primary_test'), 'cutoff'].item() == pd.Timestamp(config['anchor_reference'])

    # Independent development-period reconciliation against cleaned daily partitions.
    # This deliberately uses the last validation cutoff and does not summarise test outcomes.
    spot = schedule.loc[schedule.split.eq('validation')].iloc[-1]
    partition_lookup = {partition_date(path): path for path in files}
    history = pd.concat([
        read_partition(partition_lookup[date], ['merchant_abn', 'user_id', 'order_datetime', 'dollar_value'])
        for date in pd.date_range(spot.history_start, spot.history_end)
    ], ignore_index=True)
    history = history.loc[history.merchant_abn.isin(known)]
    expected_features = history.groupby('merchant_abn', observed=True).agg(
        hist_gmv=('dollar_value', 'sum'),
        hist_orders=('dollar_value', 'size'),
        hist_unique_customers=('user_id', 'nunique'),
        hist_active_days=('order_datetime', 'nunique'),
    )
    local = root / 'tables/modeling' / config['snapshot_run_id']
    actual_all = pd.read_parquet(local / 'all_candidates' / 'validation_all_candidates.parquet')
    actual_all = actual_all.loc[actual_all.cutoff.eq(spot.cutoff)].set_index('merchant_abn')
    for column in expected_features:
        expected = actual_all.index.to_series().map(expected_features[column]).fillna(0).to_numpy()
        np.testing.assert_allclose(actual_all[column].to_numpy(), expected)

    label_frame = pd.concat([
        read_partition(partition_lookup[date], ['merchant_abn', 'dollar_value'])
        for date in pd.date_range(spot.label_start, spot.label_end)
    ], ignore_index=True)
    expected_gmv = label_frame.loc[label_frame.merchant_abn.isin(known)].groupby(
        'merchant_abn', observed=True
    ).dollar_value.sum()
    actual_labels = pd.read_parquet(local / 'validation_labels.parquet')
    actual_labels = actual_labels.loc[actual_labels.cutoff.eq(spot.cutoff)].set_index('merchant_abn')
    expected = actual_labels.index.to_series().map(expected_gmv).fillna(0).to_numpy()
    np.testing.assert_allclose(actual_labels.future_gmv.to_numpy(), expected)
    forbidden = {'merchant_abn', 'consumer_id', 'user_id', 'name', 'address', 'order_id',
                 'future_gmv', 'target_revenue', 'amount_tail_p99', 'amount_tail_p999'}
    assert not forbidden.intersection(manifest['predictor_columns'])
    assert all(c.startswith('hist_') or c in {'merchant_category', 'revenue_level', 'take_rate_pct'}
               for c in manifest['predictor_columns'])
    # Value-level checks remain confined to development files. Protected test
    # Parquet files are checked through footer metadata and schema only.
    total_rows = 0
    for summary in [value for value in manifest['splits'] if value['split'] != 'test']:
        split = summary['split']
        local = root / 'tables/modeling' / config['snapshot_run_id']
        x = pd.read_parquet(local / f'{split}_features.parquet')
        y = pd.read_parquet(local / f'{split}_labels.parquet')
        all_x = pd.read_parquet(local / 'all_candidates' / f'{split}_all_candidates.parquet')
        keys = ['merchant_abn', 'cutoff']
        assert not x.duplicated(keys).any() and not y.duplicated(keys).any() and not all_x.duplicated(keys).any()
        pd.testing.assert_frame_equal(x[keys], y[keys])
        assert set(x.merchant_abn).issubset(known)
        assert x.eligible_history.all()
        assert set(all_x.merchant_abn) == known
        assert all_x.groupby('cutoff').size().eq(len(masters)).all()
        assert len(x) == len(y) == summary['eligible_rows']
        assert len(all_x) == summary['candidate_rows']
        assert int((~all_x.eligible_history).sum()) == summary['excluded_no_history_rows']
        assert x.eligible_history.eq(x.hist_orders.gt(0)).all()
        assert all_x.eligible_history.eq(all_x.hist_orders.gt(0)).all()
        assert set(x.columns) == set(METADATA + manifest['predictor_columns'])
        assert set(y.columns) == {'merchant_abn', 'cutoff', 'label_start', 'label_end', 'future_gmv', 'target_revenue'}
        expected = schedule.loc[schedule.split.eq(split)]
        assert set(x.cutoff) == set(expected.cutoff)
        assert x.history_end.eq(x.cutoff).all()
        assert (x.history_end - x.history_start).dt.days.eq(config['history_days']-1).all()
        assert (y.label_start - y.cutoff).dt.days.eq(1).all()
        assert (y.label_end - y.cutoff).dt.days.eq(config['target_days']).all()
        assert (x.history_end < y.label_start).all()
        assert str(y.label_start.min().date()) == summary['first_label_date']
        assert str(y.label_end.max().date()) == summary['last_label_date']
        numeric = x[manifest['predictor_columns']].select_dtypes(include='number')
        assert not np.isinf(numeric.to_numpy(dtype=float)).any()
        assert np.isfinite(y[['future_gmv', 'target_revenue']].to_numpy()).all()
        assert y[['future_gmv', 'target_revenue']].ge(0).all().all()
        np.testing.assert_allclose(y.target_revenue, y.future_gmv*x.take_rate_pct/100)
        assert y.loc[y.future_gmv.eq(0), 'target_revenue'].eq(0).all()
        for kind, count_column in [
            ('consumer', 'hist_consumer_signal_entity_days'),
            ('merchant', 'hist_merchant_signal_days'),
        ]:
            no_signal = x[count_column].eq(0)
            assert x.loc[no_signal, f'hist_{kind}_probability_mean'].isna().all()
            observed = x[f'hist_{kind}_probability_mean'].dropna()
            assert observed.between(0, 1).all()
        assert x.hist_consumer_signal_entity_days.le(x.hist_customer_entity_days).all()
        assert x.hist_consumer_signal_coverage.between(0, 1).all()
        assert x.hist_merchant_signal_calendar_coverage.between(0, 1).all()
        total_rows += len(x)

    test_summary = next(value for value in manifest['splits'] if value['split'] == 'test')
    local = root / 'tables/modeling' / config['snapshot_run_id']
    test_feature_file = pq.ParquetFile(local / 'test_features.parquet')
    test_label_file = pq.ParquetFile(local / 'test_labels.parquet')
    assert test_feature_file.metadata.num_rows == test_summary['eligible_rows']
    assert test_label_file.metadata.num_rows == test_summary['eligible_rows']
    assert set(test_feature_file.schema.names) == set(METADATA + manifest['predictor_columns'])
    assert set(test_label_file.schema.names) == {
        'merchant_abn', 'cutoff', 'label_start', 'label_end', 'future_gmv', 'target_revenue'
    }

    baseline_config = json.loads((baseline_config_path or root / 'config/baseline_v1.json').read_text(encoding='utf-8'))
    baseline_id = baseline_config['baseline_run_id']
    baseline_dir = root / 'reports/baseline' / baseline_id
    baseline = json.loads((baseline_dir / 'metrics.json').read_text(encoding='utf-8'))
    contract = json.loads((baseline_dir / 'model_contract.json').read_text(encoding='utf-8'))
    assert baseline['snapshot_run_id'] == config['snapshot_run_id']
    verify_baseline_freeze(root, baseline_id)
    protocol = baseline['development_protocol']
    assert protocol['input_splits'] == ['train', 'validation']
    assert protocol['preprocessing_fit_split'] == 'train'
    assert protocol['selection_split'] == 'validation'
    assert not protocol['test_features_opened']
    assert not protocol['test_labels_opened']
    assert not protocol['test_evaluated']
    assert all(value['split'] in {'train', 'validation'} for value in baseline['input_files'])
    assert all('test_' not in value['path'] for value in baseline['input_files'])
    for value in baseline['input_files']:
        path = root / value['path']
        assert path.stat().st_size == value['bytes']
        assert sha256(path) == value['sha256']
    assert contract['selected_model'] == baseline['selection']['selected_model']
    assert contract['selection_status'] == 'validation_selected_not_tested'
    assert not contract['test_opened'] and not contract['test_evaluated']

    # Independently reproduce every aggregate validation metric from the local,
    # ignored validation prediction file. No protected rows are present here.
    predictions = pd.read_parquet(
        root / 'artifacts' / baseline['baseline_run_id'] / 'validation_predictions.parquet'
    )
    expected_metrics = {value['model']: value for value in baseline['aggregate_validation_metrics']}
    for model, expected in expected_metrics.items():
        column = f'prediction__{model}'
        reproduced_metrics = ranking_metrics(predictions, column, 100)
        comparisons = {
            'mean_ndcg_at_100': reproduced_metrics.ndcg_at_100.mean(),
            'mean_oracle_capture_at_100': reproduced_metrics.oracle_capture_at_100.mean(),
            'mean_spearman': reproduced_metrics.spearman.mean(),
            'mean_mae_aud': reproduced_metrics.mae.mean(),
            'mean_top_100_realised_revenue_aud': reproduced_metrics.top_100_realised_revenue_aud.mean(),
            'mean_top_100_jaccard_stability': top_k_stability(predictions, column, 100),
        }
        for name, actual in comparisons.items():
            np.testing.assert_allclose(actual, expected[name])
    ordered = sorted(
        baseline['aggregate_validation_metrics'],
        key=lambda value: (value['mean_ndcg_at_100'], value['mean_oracle_capture_at_100']),
        reverse=True,
    )
    assert ordered[0]['model'] == baseline['selection']['selected_model']

    notebook_checks = []
    for name in ['02_cleaned_data_eda.ipynb', '03_time_split.ipynb', '04_baseline_models.ipynb', '05_feature_quality.ipynb']:
        notebook = nbformat.read(root / 'notebooks' / name, as_version=4)
        nbformat.validate(notebook)
        cells = [c for c in notebook.cells if c.cell_type == 'code']
        assert cells and all(c.execution_count is not None for c in cells)
        textual = []
        for cell in cells:
            for output in cell.outputs:
                assert output.output_type != 'error'
                textual.append(output.get('text', ''))
                textual.extend(value for mime, value in output.get('data', {}).items()
                               if mime in {'text/plain', 'text/html', 'text/markdown'})
        # This checks output headings, not source column names or binary figure encodings.
        assert not re.search(r'\b(?:merchant_abn|consumer_id|user_id|order_id)\b', '\n'.join(textual))
        notebook_checks.append({'notebook': name, 'executed_code_cells': len(cells), 'errors': 0})

    return {
        'status': 'PASS', 'cleaning_run_id': run_id,
        'contributor_source_hashes_policies_contract_and_counts_match': True,
        'etl_validation': etl, 'historical_eda_rows_verified': eda['historical_orders'],
        'development_merchant_snapshot_rows_verified': total_rows,
        'protected_test_rows_footer_verified_without_value_access': test_summary['eligible_rows'],
        'predictor_count': len(manifest['predictor_columns']),
        'chronological_boundaries_key_alignment_and_protected_period_checked': True,
        'eligible_history_enforced': True,
        'native_fraud_grain_features_checked': True,
        'independent_validation_cutoff_reconciled': str(spot.cutoff.date()),
        'zero_targets_retained_and_missing_signals_preserved': True,
        'executed_notebooks': notebook_checks,
        'baseline_validation_selection_verified': baseline['selection']['selected_model'],
        'baseline_artifact_freeze_verified': True,
        'consumer_analysis_fields_minimised': True,
        'eda_internal_validation_overlap_disclosed': eda['eda_label_period_overlap']['validation'],
        'model_trained': True, 'holdout_target_values_published': False,
        'test_feature_values_opened_by_baseline_or_validation': False,
        'test_label_values_opened_by_baseline_or_validation': False,
        'limitations': [
            'Static master attributes and take rates are unversioned.',
            'Fraud signal event dates do not prove publication-time availability.',
            'Date separation is necessary but does not resolve these as-of assumptions.',
        ],
        'runtime_versions': {name: importlib.metadata.version(name) for name in
                             ['pandas', 'numpy', 'pyarrow', 'matplotlib', 'nbformat', 'nbclient', 'pytest', 'scikit-learn']},
        'python_version': sys.version.split()[0],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    parser.add_argument('--cleaning-run-id')
    parser.add_argument('--baseline-config', type=Path)
    args = parser.parse_args()
    result = validate(ROOT, args.config, args.cleaning_run_id, args.baseline_config)
    save_json(result, ROOT / 'reports/analysis_validation_v3.json')
    print(json.dumps(result, indent=2))
