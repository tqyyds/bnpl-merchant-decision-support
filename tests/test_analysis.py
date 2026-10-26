from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from src.bnpl_analysis.eda import historical_files
from src.bnpl_analysis.time_split import features_for_window, snapshot_schedule, targets_for_window, METADATA


CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'config/analysis_v1.json').read_text())


def masters():
    return pd.DataFrame({'merchant_abn': ['A', 'B'], 'merchant_category': ['home', 'sport'],
                         'revenue_level': ['A', 'B'], 'take_rate_pct': [2.0, 3.0]})


def transactions():
    return pd.DataFrame({'merchant_abn': ['A', 'A', 'A', 'A', 'X'], 'user_id': [1, 1, 2, 3, 5],
                         'order_datetime': pd.to_datetime(['2021-12-15', '2022-01-20', '2022-01-30', '2022-02-01', '2022-01-20']),
                         'dollar_value': [100., 200., 300., 9999., 500.],
                         'consumer_fraud_probability': [np.nan, 50., np.nan, 100., np.nan],
                         'merchant_fraud_probability': [np.nan]*5})


def test_schedule_chronological_and_complete():
    schedule = snapshot_schedule('2021-02-28', '2022-10-26', CONFIG)
    assert schedule.groupby('split').size().to_dict() == {'test': 8, 'train': 6, 'validation': 3}
    assert (schedule.label_start > schedule.history_end).all()
    assert ((schedule.history_end-schedule.history_start).dt.days == 89).all()
    assert ((schedule.label_end-schedule.label_start).dt.days == 27).all()
    assert schedule.query("split == 'train'").label_end.max() < schedule.query("split == 'validation'").label_start.min()
    assert schedule.query("split == 'validation'").label_end.max() < schedule.query("split == 'test'").label_start.min()
    assert schedule.query("split == 'validation'").label_end.max() == pd.Timestamp('2022-02-27')
    assert schedule.query("split == 'test'").label_start.min() == pd.Timestamp('2022-02-28')
    assert schedule.query("evaluation_role == 'primary_test'").cutoff.item() == pd.Timestamp('2022-02-27')
    assert schedule.query("split == 'test' and evaluation_role == 'robustness'").shape[0] == 7


def test_future_mutations_do_not_change_features():
    original = transactions()
    modified = original.copy()
    modified.loc[modified.order_datetime > '2022-01-30', 'dollar_value'] = 1e12
    left = features_for_window(original, masters(), pd.Timestamp('2022-01-30'), 90)
    right = features_for_window(modified, masters(), pd.Timestamp('2022-01-30'), 90)
    pd.testing.assert_frame_equal(left, right)
    assert left.loc[0, 'hist_gmv'] == 600
    assert left.loc[0, 'hist_unique_customers'] == 2
    assert left.loc[0, 'hist_repeat_customer_rate'] == .5
    assert left.loc[0, 'hist_consumer_probability_mean'] == .5
    assert np.isnan(left.loc[0, 'hist_merchant_probability_mean'])
    assert left.loc[0, 'hist_merchant_signal_calendar_coverage'] == 0
    assert not left.loc[1, 'eligible_history']
    assert set(left.merchant_abn) == {'A', 'B'}
    assert not any('future' in c or 'target' in c for c in left.columns if c not in METADATA)


def test_zero_future_activity_retained():
    daily = pd.DataFrame({'merchant_abn': ['A', 'A', 'X'], 'date': pd.to_datetime(['2022-01-30', '2022-02-01', '2022-02-01']), 'gmv': [1000., 100., 500.]})
    result = targets_for_window(daily, masters(), pd.Timestamp('2022-01-30'), 28)
    assert result.target_revenue.tolist() == [2., 0.]
    assert result.future_gmv.tolist() == [100., 0.]


def test_eda_excludes_later_partitions():
    paths = [Path(f'order_datetime={date}/part.parquet') for date in ['2022-02-27', '2022-02-28']]
    assert historical_files(paths, '2022-02-27') == paths[:1]


def test_development_targets_never_touch_protected_outcomes():
    schedule = snapshot_schedule('2021-02-28', '2022-10-26', CONFIG)
    development = schedule[~schedule['split'].eq('test')]
    protected = schedule[schedule['split'].eq('test')]
    assert development.label_end.max() < pd.Timestamp(CONFIG['protected_outcome_start'])
    assert protected.label_start.min() == pd.Timestamp(CONFIG['protected_outcome_start'])


def test_overlapping_targets_rejected():
    with pytest.raises(ValueError, match='must not overlap'):
        snapshot_schedule('2021-02-28', '2022-10-26', {**CONFIG, 'stride_days': 7})


def test_feature_window_excludes_pre_history_and_includes_endpoints():
    frame = pd.DataFrame({'merchant_abn': ['A']*4, 'user_id': [1, 2, 3, 4],
                         'order_datetime': pd.to_datetime(['2021-11-01', '2021-11-02', '2022-01-30', '2022-01-31']),
                         'dollar_value': [99999., 10., 20., 99999.],
                         'consumer_fraud_probability': [np.nan]*4,
                         'merchant_fraud_probability': [np.nan]*4})
    result = features_for_window(frame, masters(), pd.Timestamp('2022-01-30'), 90)
    assert result.loc[0, 'hist_gmv'] == 30
    assert result.loc[0, 'hist_orders'] == 2


def test_consumer_fraud_is_entity_day_not_order_weighted():
    frame = pd.DataFrame({
        'merchant_abn': ['A', 'A', 'A', 'A'],
        'user_id': [1, 1, 1, 2],
        'order_datetime': pd.to_datetime(['2022-01-20'] * 3 + ['2022-01-21']),
        'dollar_value': [10., 20., 30., 40.],
        'consumer_fraud_probability': [20., 20., 20., 80.],
        'merchant_fraud_probability': [np.nan] * 4,
    })
    consumer_native = pd.DataFrame({
        'user_id': [1, 2],
        'order_datetime': pd.to_datetime(['2022-01-20', '2022-01-21']),
        'fraud_probability': [20., 80.],
    })
    merchant_native = pd.DataFrame({
        'merchant_abn': ['A'],
        'order_datetime': pd.to_datetime(['2022-01-19']),
        'fraud_probability': [60.],
    })
    result = features_for_window(
        frame, masters(), pd.Timestamp('2022-01-30'), 90, consumer_native, merchant_native
    ).set_index('merchant_abn')
    assert result.loc['A', 'hist_customer_entity_days'] == 2
    assert result.loc['A', 'hist_consumer_signal_entity_days'] == 2
    assert result.loc['A', 'hist_consumer_probability_mean'] == pytest.approx(.5)
    assert result.loc['A', 'hist_consumer_signal_coverage'] == pytest.approx(1.0)
    assert result.loc['A', 'hist_merchant_probability_latest'] == pytest.approx(.6)
    assert result.loc['A', 'hist_merchant_signal_recency_days'] == 11
