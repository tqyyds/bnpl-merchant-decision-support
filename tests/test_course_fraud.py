import numpy as np
import pandas as pd
import pytest

from engines.course_fraud import (
    CourseFraudModel,
    PointInTimeFraudFeatures,
    SigmoidCalibrator,
    aggregate_merchant_evidence,
    classification_metrics,
    deterministic_negative_sample,
    label_sensitivity_metrics,
    label_course_transactions,
    ranking_sensitivity,
    select_proxy_champion,
)


def transactions(day="2022-01-01", consumer=(False, False), merchant=(False, False)):
    return pd.DataFrame({
        "order_id": [f"{day}-a", f"{day}-b"],
        "order_datetime": pd.to_datetime([day, day]),
        "user_id": [1, 2],
        "merchant_abn": ["00000000001", "00000000001"],
        "dollar_value": [10.0, 30.0],
        "consumer_fraud_signal_present": consumer,
        "merchant_fraud_signal_present": merchant,
    })


def test_course_label_is_union_and_explicitly_not_final_adjudication():
    labelled = label_course_transactions(transactions(consumer=(True, False), merchant=(False, True)))
    assert labelled["is_fraud"].tolist() == [True, True]
    assert labelled["course_label_source"].tolist() == ["CONSUMER_DAY", "MERCHANT_DAY"]
    assert labelled["fraud_label_semantics"].eq("OBSERVED_COURSE_DELTA_NOT_FINAL_ADJUDICATION").all()
    assert labelled["consumer_day_match_multiplicity"].tolist() == [1, 0]
    assert labelled["merchant_day_match_multiplicity"].tolist() == [0, 2]


def test_single_match_variant_quarantines_propagated_matches():
    labelled = label_course_transactions(transactions(merchant=(True, True)), "SINGLE_MATCH_ONLY")
    assert labelled["is_fraud"].isna().all()
    assert not labelled["label_eligible"].any()


def test_point_in_time_builder_excludes_same_day_behaviour_and_labels():
    builder = PointInTimeFraudFeatures()
    categories = pd.Series({"00000000001": "books"})
    first = builder.transform_then_update(transactions(consumer=(True, False)), categories)
    assert first["consumer_txn_count_30d"].eq(0).all()
    assert first["merchant_txn_count_30d"].eq(0).all()
    second = builder.transform_then_update(transactions("2022-01-02"), categories)
    assert second["consumer_txn_count_30d"].eq(1).all()
    assert second["merchant_txn_count_30d"].eq(2).all()
    assert second["merchant_proxy_fraud_rate_90d"].eq(0.5).all()
    assert second["consumer_amount_zscore_available"].eq(0).all()


def test_batches_must_be_chronological():
    builder = PointInTimeFraudFeatures()
    categories = pd.Series({"00000000001": "books"})
    builder.transform_then_update(transactions(), categories)
    with pytest.raises(ValueError, match="strictly chronological"):
        builder.transform_then_update(transactions(), categories)


def test_negative_sampling_keeps_every_positive_and_restores_negative_weight():
    frame = pd.concat([transactions(consumer=(True, False))] * 10, ignore_index=True)
    frame["order_id"] = [f"o{i}" for i in range(len(frame))]
    labelled = label_course_transactions(frame)
    sampled, weights = deterministic_negative_sample(labelled, 0.5)
    assert set(labelled.loc[labelled.is_fraud, "order_id"]).issubset(set(sampled.order_id))
    assert np.all(weights[~sampled.is_fraud.to_numpy()] == 2.0)


def model_frame():
    rows = 40
    frame = pd.DataFrame({
        "order_id": [f"o{i}" for i in range(rows)],
        "is_fraud": [i % 5 == 0 for i in range(rows)],
        "merchant_category": ["A" if i % 2 else "B" for i in range(rows)],
    })
    for field in [
        "transaction_amount_log1p", "consumer_txn_count_30d_log1p",
        "consumer_active_days_30d", "consumer_avg_amount_30d_log1p", "consumer_amount_zscore_30d",
        "consumer_proxy_fraud_rate_90d", "merchant_txn_count_30d_log1p", "merchant_active_days_30d",
        "merchant_avg_amount_30d_log1p", "merchant_proxy_fraud_rate_90d",
        "consumer_amount_zscore_available",
    ]:
        frame[field] = np.arange(rows, dtype=float)
    frame.loc[0, "consumer_amount_zscore_30d"] = np.nan
    return frame


def test_linear_and_gam_are_distinct_and_missing_indicators_are_not_splined():
    frame = model_frame()
    baseline = CourseFraudModel(kind="logistic").fit(frame)
    model = CourseFraudModel(kind="spline_gam", n_knots=4).fit(frame)
    names = [name for name, _, _ in model.pipeline.named_steps["prepare"].transformers]
    assert "numeric_spline" in names
    assert "numeric_missing" in names
    assert baseline.model_name.startswith("course_fraud_proxy_logistic")
    assert model.model_name.startswith("course_fraud_proxy_spline_gam")
    probability = model.predict_proba(frame)
    report = classification_metrics(frame, probability, review_capacities=(0.1,))
    assert probability.shape == (len(frame),)
    assert np.logical_and(probability >= 0, probability <= 1).all()
    assert report["rows"] == len(frame)
    assert set(report["review_capacity"]["0.1000"]) == {"reviewed_rows", "probability_threshold", "precision", "recall"}


def test_spline_qa_falls_back_for_low_unique_high_zero_share_feature():
    frame = model_frame()
    frame["merchant_proxy_fraud_rate_90d"] = 0.0
    model = CourseFraudModel(kind="spline_gam").fit(frame)
    assert model.spline_qa["merchant_proxy_fraud_rate_90d"]["transform"] == "linear_fallback"


def test_history_proxy_rate_ablation_removes_both_features():
    frame = model_frame()
    model = CourseFraudModel(kind="spline_gam", include_history_proxy_rates=False).fit(frame)
    assert "consumer_proxy_fraud_rate_90d" not in model.model_features
    assert "merchant_proxy_fraud_rate_90d" not in model.model_features


def test_sigmoid_calibration_requires_independent_fit():
    calibrator = SigmoidCalibrator()
    with pytest.raises(ValueError, match="not been fitted"):
        calibrator.predict(np.array([0.2]))
    calibrated = calibrator.fit(np.array([0.1, 0.2, 0.8, 0.9]), np.array([0, 0, 1, 1])).predict(np.array([0.3]))
    assert 0 <= calibrated[0] <= 1


def test_label_sensitivity_excludes_ambiguous_rows_only_for_single_match():
    raw = pd.DataFrame({
        "order_id": ["consumer-exact", "merchant-a", "merchant-b", "negative"],
        "order_datetime": pd.to_datetime(["2022-01-01"] * 4),
        "user_id": [1, 2, 3, 4],
        "merchant_abn": ["00000000001", "00000000002", "00000000002", "00000000003"],
        "dollar_value": [10., 20., 30., 40.],
        "consumer_fraud_signal_present": [True, False, False, False],
        "merchant_fraud_signal_present": [False, True, True, False],
    })
    frame = label_course_transactions(raw)
    probability = np.array([0.8, 0.7, 0.6, 0.1])
    report = label_sensitivity_metrics(frame, probability, review_capacities=(0.5,))
    assert report["UNION_PROPAGATED"]["observed_fraud_rows"] == 3
    assert report["CONSUMER_ONLY"]["observed_fraud_rows"] == 1
    assert report["SINGLE_MATCH_ONLY"]["rows"] == 2


def test_proxy_champion_gate_is_validation_only_and_conservative():
    logistic = {"pr_auc": .20, "brier_score": .05, "review_capacity": {"0.0100": {"recall": .1}}}
    gam = {"pr_auc": .21, "brier_score": .051, "review_capacity": {"0.0100": {"recall": .2}}}
    assert select_proxy_champion(logistic, gam)[0] == "spline_gam"
    gam["brier_score"] = .06
    assert select_proxy_champion(logistic, gam)[0] == "logistic"


def test_ranking_sensitivity_never_calls_a_lambda_optimal():
    frame = pd.DataFrame({
        "merchant_abn": ["00000000001", "00000000002", "00000000003"],
        "prediction": [100., 90., 80.],
        "fraud_risk_evidence_percentile": [1., .2, .1],
    })
    selected, summary = ranking_sensitivity(frame, "prediction", lambdas=(0, .2), capacity=2)
    assert set(selected.risk_evidence_lambda) == {0, .2}
    assert summary.claim.eq("SENSITIVITY_NOT_OPTIMAL_POLICY").all()


def test_merchant_aggregation_keeps_net_loss_null_and_shadow_state():
    frame = pd.DataFrame({
        "order_id": ["a", "b", "c"],
        "merchant_abn": ["00000000001"] * 3,
        "order_datetime": pd.to_datetime(["2022-01-01", "2022-01-02", "2022-01-03"]),
        "dollar_value": [10.0, 20.0, 30.0],
        "is_fraud": [False, True, False],
        "predicted_course_fraud_probability": [0.1, 0.8, 0.2],
    })
    out = aggregate_merchant_evidence(frame, "2022-01-03", 0.5).iloc[0]
    assert out.historical_course_fraud_rate == pytest.approx(1 / 3)
    assert out.historical_course_fraud_amount_share == pytest.approx(1 / 3)
    assert out.amount_weighted_predicted_course_fraud_probability == pytest.approx((1 + 16 + 6) / 60)
    assert out.fraud_model_status == "PROXY_SHADOW"
    assert out.loss_model_status == "NOT_AVAILABLE"
    assert pd.isna(out.predicted_net_loss_28d_aud)
    assert pd.isna(out.predicted_loss_rate_28d)
