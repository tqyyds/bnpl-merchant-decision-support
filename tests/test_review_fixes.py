"""Regression tests for the review findings and feature boundary semantics."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from src.bnpl_analysis.time_split import features_for_window
from src.bnpl_analysis.eda import exploration_scope
from src.bnpl_analysis.baselines import run_baselines
from src.bnpl_analysis.feature_contract import feature_contract
from src.bnpl_analysis.feature_qa import validate_features
from src.bnpl_analysis.time_split import METADATA
from src.bnpl_etl import pipeline
from src.bnpl_etl.transforms import clean_consumer_geography
from src.run_artifacts import claim_run, finish_run, inventory, verify_baseline_freeze


def fixture():
    masters = pd.DataFrame({'merchant_abn': ['A', 'B'], 'merchant_category': ['home', 'sport'],
                           'revenue_level': ['A', 'B'], 'take_rate_pct': [2., 3.]})
    frame = pd.DataFrame({'merchant_abn': ['A']*3, 'user_id': [1, 1, 2],
                          'order_datetime': pd.to_datetime(['2022-01-20']*3),
                          'dollar_value': [10., 20., 40.]})
    native = pd.DataFrame({'user_id': [1, 2], 'order_datetime': pd.to_datetime(['2022-01-20']*2),
                           'fraud_probability': [20., 80.]})
    return masters, frame, native


def features(frame, masters, native):
    return features_for_window(frame, masters, pd.Timestamp('2022-01-30'), 90, native)


def test_latest_day_mean_is_row_order_invariant_and_not_order_weighted():
    masters, frame, native = fixture()
    expected = features(frame, masters, native)
    actual = features(frame.iloc[::-1], masters.iloc[::-1], native.iloc[::-1])
    pd.testing.assert_frame_equal(expected, actual)
    assert expected.loc[0, 'hist_consumer_probability_latest_day_mean'] == pytest.approx(.5)
    # Duplicating an order changes commercial volume, but not native fraud summaries.
    duplicate = features(pd.concat([frame, frame.iloc[:1]], ignore_index=True), masters, native)
    fraud = [c for c in expected if 'consumer_probability' in c or 'consumer_signal' in c]
    pd.testing.assert_frame_equal(expected[fraud], duplicate[fraud])


def test_latest_day_mean_respects_latest_date_and_future_signal_mutation():
    masters, frame, native = fixture()
    earlier = pd.DataFrame({'user_id': [3], 'order_datetime': pd.to_datetime(['2022-01-10']),
                           'fraud_probability': [99.]})
    extra = pd.DataFrame({'merchant_abn': ['A'], 'user_id': [3],
                          'order_datetime': pd.to_datetime(['2022-01-10']), 'dollar_value': [10.]})
    frame = pd.concat([frame, extra], ignore_index=True)
    native = pd.concat([native, earlier], ignore_index=True)
    expected = features(frame, masters, native)
    assert expected.loc[0, 'hist_consumer_probability_latest_day_mean'] == pytest.approx(.5)
    future = earlier.assign(order_datetime=pd.Timestamp('2022-01-31'), fraud_probability=100.)
    changed = features(frame, masters, pd.concat([native, future], ignore_index=True))
    pd.testing.assert_frame_equal(expected, changed)


def test_empty_and_single_order_windows_keep_schema_and_explicit_missingness():
    masters, frame, native = fixture()
    regular = features(frame, masters, native)
    empty = features(frame.iloc[:0], masters, native.iloc[:0])
    assert set(empty) == set(regular)
    assert not empty.eligible_history.any()
    assert empty.hist_gmv.eq(0).all()
    assert empty.hist_growth_28d.isna().all()
    assert empty.hist_customer_hhi.isna().all()
    one = features(frame.iloc[:1], masters, native).iloc[0]
    assert one.hist_amount_std != one.hist_amount_std  # sample std undefined for n=1
    assert one.hist_customer_hhi == 1
    assert one.hist_repeat_customer_rate == 0
    assert one.hist_no_previous28_activity == 1
    assert pd.isna(one.hist_growth_28d)


def test_consumer_staging_is_allow_listed():
    raw = pd.DataFrame({'consumer_id':[1], 'state':['VIC'], 'postcode':[3000],
                        'name':['synthetic'], 'address':['synthetic'], 'gender':['unknown'],
                        'unexpected_personal_field':['synthetic']})
    official = pd.DataFrame({'STATE':['VIC'], 'POSTCODE':['3000']})
    actual = clean_consumer_geography(raw, official)
    assert not {'name','address','gender','unexpected_personal_field'}.intersection(actual)
    assert actual.geo_match_status.item() == 'matched_poa'


def test_reference_manifest_does_not_claim_a_local_etl_run(tmp_path, monkeypatch):
    reference = tmp_path / 'reports/etl/v1_1_manifest.json'
    reference.parent.mkdir(parents=True)
    reference.write_text('{}')
    monkeypatch.setattr(pipeline, '_read_policy', lambda _: {})
    def reached_source_validation(_):
        raise RuntimeError('source verification reached')
    monkeypatch.setattr(pipeline, 'verify_sources', reached_source_validation)
    with pytest.raises(RuntimeError, match='source verification reached'):
        pipeline.run_pipeline(pipeline.PipelinePaths(tmp_path, 'v1_1'))


@pytest.mark.parametrize('completed', [False, True])
def test_existing_or_interrupted_runs_cannot_be_reclaimed(tmp_path, completed):
    directory = tmp_path / 'run'
    claim_run(directory)
    if completed:
        finish_run(directory)
    with pytest.raises(FileExistsError):
        claim_run(directory)


def test_existing_baseline_rejected_before_loading_data(tmp_path):
    (tmp_path/'config').mkdir()
    (tmp_path/'config/baseline_v1.json').write_text(json.dumps({
        'baseline_run_id':'demo','snapshot_run_id':'demo',
        'allowed_input_splits':['train','validation'],'ranking_k':100}))
    (tmp_path/'artifacts/demo').mkdir(parents=True)
    with pytest.raises(FileExistsError, match='Baseline run already exists'):
        run_baselines(tmp_path)


def test_frozen_artifact_tampering_is_detected(tmp_path):
    directory = tmp_path/'artifacts/demo'
    claim_run(directory)
    model = directory/'model.joblib'
    model.write_bytes(b'original')
    (directory/'model_contract.json').write_text(json.dumps({'input_files':[]}))
    (directory/'freeze.json').write_text(json.dumps({'output_files':inventory(tmp_path,[model])}))
    finish_run(directory)
    verify_baseline_freeze(tmp_path, 'demo')
    model.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='Frozen file changed'):
        verify_baseline_freeze(tmp_path, 'demo')


def test_eda_discloses_internal_validation_overlap():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root/'config/analysis_v1.json').read_text())
    actual = exploration_scope(config, '2021-02-28', '2022-10-26')
    assert actual['eda_label_period_overlap'] == {'train':True,'validation':True,'test':False}
    earlier = exploration_scope({**config,'eda_end':'2021-12-05'},'2021-02-28','2022-10-26')
    assert not earlier['eda_label_period_overlap']['validation']


def test_complete_feature_catalogue_and_qa_catch_formula_corruption():
    masters, frame, native = fixture()
    actual = features(frame, masters, native)
    actual = actual.loc[actual.eligible_history].copy()
    predictors = [name for name in actual if name not in METADATA]
    assert feature_contract()['predictor_count'] == len(predictors) == 46
    validate_features(actual, predictors)
    actual['hist_revenue_proxy'] += 1
    with pytest.raises(AssertionError):
        validate_features(actual, predictors)


@pytest.mark.parametrize('run_id', ['../escape','a/b','a\\b','', '..'])
def test_invalid_run_ids_rejected(run_id):
    with pytest.raises(ValueError):
        pipeline.PipelinePaths(Path('.'), run_id)
