import numpy as np
import pandas as pd
import pytest

from src.bnpl_analysis.customer_context import context_for_window


def inputs():
    masters = pd.DataFrame({'merchant_abn':['A','B','C']})
    history = pd.DataFrame({'merchant_abn':['A','A','A'], 'consumer_id':[1,1,2],
                           'order_datetime':pd.to_datetime(['2022-01-20']*3),
                           'dollar_value':[10.,20.,70.]})
    consumers = pd.DataFrame({'consumer_id':[1,2], 'state':['VIC','NSW'],
        'poa_code_2021':['3000','2000'], 'geo_match_status':['matched_poa']*2,
        'seifa_match_status':['matched']*2, 'median_household_income_weekly_aud':[100.,200.],
        'population_18_39_share':[.2,.4], 'irsd_score':[900.,1100.], 'irsad_score':[800.,1000.]})
    first = pd.Series({'A':pd.Timestamp('2022-01-20'),'B':pd.Timestamp('2021-01-01'),'C':pd.Timestamp('2022-06-01')})
    return masters,history,consumers,first


def test_context_preserves_inactive_and_no_history_candidates_and_weighting():
    masters,history,consumers,first = inputs()
    result = context_for_window(history,masters,consumers,first,pd.Timestamp('2022-01-30')).set_index('merchant_abn')
    assert result.candidate_status.tolist() == ['active_history','inactive_recent_window','no_observed_history']
    assert pd.isna(result.loc['C','first_observed_order_asof'])
    assert result.loc['A','ctx_area_household_income_customer_mean'] == 150
    assert result.loc['A','ctx_area_household_income_gmv_mean'] == 170
    assert result.loc['A','ctx_customer_state_gmv_hhi'] == pytest.approx(.3**2+.7**2)
    assert result.loc['A','ctx_dominant_customer_state'] == 'NSW'
    assert pd.isna(result.loc['B','ctx_geo_customer_coverage'])
    assert not result.ctx_historical_availability_verified.any()


def test_context_is_order_invariant_and_future_rows_do_not_change_features():
    masters,history,consumers,first = inputs()
    cutoff = pd.Timestamp('2022-01-30')
    expected = context_for_window(history,masters,consumers,first,cutoff)
    future = history.iloc[:1].assign(order_datetime=pd.Timestamp('2022-02-01'),dollar_value=1e12)
    actual = context_for_window(pd.concat([history.iloc[::-1],future]),masters,consumers,first,cutoff)
    pd.testing.assert_frame_equal(actual,expected)


def test_unmatched_context_does_not_impute_area_values_or_hide_coverage():
    masters,history,consumers,first = inputs()
    consumers.loc[1,['median_household_income_weekly_aud','population_18_39_share','irsd_score','irsad_score']] = np.nan
    consumers.loc[1,'geo_match_status'] = 'postcode_absent_nationally'
    consumers.loc[1,'seifa_match_status'] = 'not_geo_matched'
    result = context_for_window(history,masters,consumers,first,pd.Timestamp('2022-01-30')).iloc[0]
    assert result.ctx_geo_customer_coverage == .5
    assert result.ctx_geo_gmv_coverage == .3
    assert result.ctx_area_household_income_customer_mean == 100
    assert result.ctx_area_household_income_customer_coverage == .5


def test_context_rejects_broken_consumer_join():
    masters,history,consumers,first = inputs()
    with pytest.raises(ValueError,match='absent from cleaned consumer'):
        context_for_window(history,masters,consumers.iloc[:1],first,pd.Timestamp('2022-01-30'))
