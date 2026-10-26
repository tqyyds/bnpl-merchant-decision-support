import numpy as np
import pandas as pd
import pytest
import json
from pathlib import Path
from types import SimpleNamespace

from engines.portfolio import optimise
from engines.risk_labels import (
    LabelBuildContext,
    LabelContractError,
    assign_temporal_roles,
    build_merchant_loss_labels,
    build_order_fraud_labels,
    choose_maturity_window,
    finance_reconciliation,
    post_maturity_adjustment_rate,
    resolve_effective_events,
    transition_risk_state,
    validate_label_build_policy,
    validate_operational_risk_events,
)
from scripts.build_risk_labels import run as run_label_build


def context(**overrides):
    values = {
        "label_as_of": "2024-05-01T00:00:00Z",
        "label_generated_at": "2024-05-02T00:00:00Z",
        "data_as_of": "2024-05-01T00:00:00Z",
        "maturity_window_days": 90,
        "required_sources": ("fraud", "credit", "finance"),
        "complete_sources": ("fraud", "credit", "finance"),
        "coverage_snapshot_id": "coverage-1",
        "label_version": "labels-1",
        "source_snapshot_hash": "source-hash",
        "label_code_version": "code-1",
        "label_config_hash": "config-hash",
        "reconciliation_status": "PASS",
    }
    values.update(overrides)
    return LabelBuildContext(**values)


def orders():
    return pd.DataFrame({
        "order_id": ["o1", "o2", "o3"],
        "merchant_abn": ["00000000001", "00000000002", "00000000003"],
        "order_created_at": pd.to_datetime(["2024-01-10", "2024-01-12", "2024-04-15"], utc=True),
        "scored_at": pd.to_datetime(["2024-01-10", "2024-01-12", "2024-04-15"], utc=True),
        "authorised_at": pd.to_datetime(["2024-01-10", "2024-01-12", "2024-04-15"], utc=True),
        "gross_authorised_amount_aud": [500.0, 200.0, 100.0],
        "eligible": [True, True, True],
    })


def event(
    event_id,
    order_id="o1",
    merchant_abn="00000000001",
    event_type="FRAUD_LOSS",
    amount=500.0,
    source="fraud",
    record=None,
    revision=1,
    supersedes=None,
    original=None,
    case="case-1",
    component="principal-1",
    status="CONFIRMED",
    occurred="2024-02-01",
    available="2024-02-02",
):
    return {
        "event_id": event_id,
        "source_system": source,
        "source_record_id": record or event_id,
        "revision": revision,
        "supersedes_event_id": supersedes,
        "original_loss_event_id": original,
        "loss_case_id": case,
        "loss_component_id": component,
        "order_id": order_id,
        "merchant_abn": merchant_abn,
        "event_type": event_type,
        "case_status": status,
        "occurred_at": occurred,
        "available_at": available,
        "amount_aud": amount,
    }


def test_event_contract_and_explicit_effective_chain():
    rows = [
        event("e1", record="r1", revision=1, status="OPEN"),
        event("e2", record="r1", revision=2, supersedes="e1", amount=450, status="CONFIRMED", available="2024-02-03"),
    ]
    checked = validate_operational_risk_events(pd.DataFrame(rows))
    effective, quarantine = resolve_effective_events(checked, "2024-03-01")
    assert effective.event_id.tolist() == ["e2"]
    assert quarantine.empty
    with pytest.raises(LabelContractError):
        validate_operational_risk_events(pd.DataFrame(rows).assign(amount_aud=[-1, 450]))


def test_invalid_chain_is_quarantined_not_silently_ranked():
    rows = [
        event("a1", record="r1", revision=1),
        event("b1", record="r2", revision=1, order_id="o2", merchant_abn="00000000002", case="case-2"),
        event("a2", record="r1", revision=2, supersedes="b1", amount=400, available="2024-02-03"),
    ]
    effective, quarantine = resolve_effective_events(pd.DataFrame(rows), "2024-03-01")
    assert "a2" not in set(effective.event_id)
    assert set(quarantine.quarantine_reason) == {"INVALID_SUPERSESSION_CHAIN"}


def test_order_labels_positive_mature_negative_and_immature_null():
    result = build_order_fraud_labels(orders(), pd.DataFrame([event("fraud-1")]), context())
    labels = result.labels.set_index("order_id")
    assert labels.loc["o1", "fraud_label"] == True
    assert labels.loc["o2", "fraud_label"] == False
    assert pd.isna(labels.loc["o3", "fraud_label"])
    assert labels.loc["o3", "label_status"] == "IMMATURE"
    assert labels.loc["o1", "scored_at"] == pd.Timestamp("2024-01-10", tz="UTC")


def test_order_negative_requires_complete_source_coverage():
    incomplete = context(complete_sources=("fraud", "credit"))
    labels = build_order_fraud_labels(orders().iloc[[1]], pd.DataFrame(columns=list(event("x").keys())), incomplete).labels
    assert labels.fraud_label.isna().all()
    assert labels.label_status.eq("SOURCE_COVERAGE_INCOMPLETE").all()


def test_explicit_final_reversal_removes_order_fraud_positive():
    ledger = pd.DataFrame([
        event("f1", amount=100),
        event("rv1", event_type="FRAUD_LOSS_REVERSAL", amount=100, source="finance",
              original="f1", component="principal-reversal", status="REVERSED",
              occurred="2024-03-01", available="2024-03-02"),
    ])
    result = build_order_fraud_labels(orders().iloc[[0]], ledger, context())
    assert result.quarantined_events.empty
    assert result.labels.iloc[0].fraud_label == False
    assert result.labels.iloc[0].label_status == "MATURE_NON_FRAUD"


def test_merchant_loss_deduplicates_overlap_and_returns_recovery_to_origin_cohort():
    ledger = pd.DataFrame([
        event("fraud-1", amount=500, source="fraud", record="fraud-loss"),
        event("credit-1", event_type="CREDIT_WRITE_OFF", amount=500, source="credit", record="credit-loss"),
        event("recovery-1", event_type="RECOVERY", amount=100, source="finance", record="recovery", original="fraud-1",
              component="recovery-1", occurred="2024-04-15", available="2024-04-16"),
    ])
    result = build_merchant_loss_labels(
        orders(), ledger, ["2024-01-01"], orders().merchant_abn, context(), ("FRAUD_LOSS", "CREDIT_WRITE_OFF")
    )
    labels = result.labels.set_index("merchant_abn")
    first = labels.loc["00000000001"]
    assert first.gross_fraud_loss_aud == 500
    assert first.gross_credit_loss_aud == 0
    assert first.recoveries_aud == 100
    assert first.net_loss_aud == 400
    assert first.net_loss_rate == .8
    third = labels.loc["00000000003"]
    assert third.future_orders == 0 and third.future_gmv_aud == 0 and third.net_loss_aud == 0
    assert pd.isna(third.net_loss_rate) and third.denominator_status == "NO_FUTURE_GMV"


def test_merchant_loss_requires_approved_priority_and_quarantines_negative_net():
    with pytest.raises(LabelContractError):
        build_merchant_loss_labels(orders(), pd.DataFrame([event("f1")]), ["2024-01-01"], orders().merchant_abn, context(), None)
    ledger = pd.DataFrame([
        event("f1", amount=50),
        event("r1", event_type="RECOVERY", amount=100, source="finance", original="f1", component="recovery"),
    ])
    result = build_merchant_loss_labels(orders(), ledger, ["2024-01-01"], orders().merchant_abn, context(), ("FRAUD_LOSS", "CREDIT_WRITE_OFF"))
    first = result.labels.set_index("merchant_abn").loc["00000000001"]
    assert first.label_status == "QUARANTINED"
    assert first.label_reason_code == "NEGATIVE_NET_LOSS"
    assert pd.isna(first.net_loss_aud)


def test_zero_gmv_with_loss_is_quarantined():
    zero = orders().iloc[[0]].copy(); zero["gross_authorised_amount_aud"] = 0.0
    result = build_merchant_loss_labels(zero, pd.DataFrame([event("f1", amount=1)]), ["2024-01-01"], zero.merchant_abn, context(), ("FRAUD_LOSS", "CREDIT_WRITE_OFF"))
    label = result.labels.iloc[0]
    assert label.label_status == "QUARANTINED"
    assert label.denominator_status == "INVALID_ZERO_GMV_WITH_LOSS"
    assert pd.isna(label.net_loss_rate)


def test_maturity_adjustment_and_governed_fallback():
    declared = pd.DataFrame({"order_id": ["a", "b"], "fraud_label": [False, False]})
    later = pd.DataFrame({"order_id": ["a", "b"], "fraud_label": [True, False]})
    assert post_maturity_adjustment_rate(declared, later, ("order_id",), ("fraud_label",)) == .5
    assert choose_maturity_window({90: .03, 120: .01, 150: 0}, .02) == (120, "PASS")
    assert choose_maturity_window({90: .03, 120: .025, 150: .021}, .02) == (None, "DEGRADED_LABEL_QUALITY")
    assert choose_maturity_window({90: 0}, None) == (None, "NOT_CONFIGURED")


def test_default_label_config_is_intentionally_not_activatable():
    policy = json.loads(Path("config/risk_label_contract_v1.json").read_text(encoding="utf-8"))
    with pytest.raises(LabelContractError):
        validate_label_build_policy(policy)
    policy.update({
        "approved_maturity_window_days": 90,
        "max_post_maturity_adjustment_rate": .01,
        "loss_classification_priority": ["FRAUD_LOSS", "CREDIT_WRITE_OFF"],
        "required_sources": ["fraud", "credit", "finance"],
        "finance_reconciliation_tolerance": {
            "max_absolute_difference_aud": 1.0,
            "max_relative_difference": .001,
        },
    })
    checked = validate_label_build_policy(policy)
    assert checked["required_sources"] == ("fraud", "credit", "finance")


def test_finance_reconciliation_is_calculated_from_totals():
    tolerance = {"max_absolute_difference_aud": 1.0, "max_relative_difference": .001}
    assert finance_reconciliation(100.5, 100, tolerance)["status"] == "PASS"
    assert finance_reconciliation(102, 100, tolerance)["status"] == "FAIL"
    with pytest.raises(LabelContractError):
        finance_reconciliation("not-a-number", 100, tolerance)


def test_label_release_cli_writes_hashed_immutable_outputs(tmp_path):
    order_path = tmp_path / "orders.parquet"
    event_path = tmp_path / "events.parquet"
    merchant_path = tmp_path / "merchants.parquet"
    coverage_path = tmp_path / "coverage.json"
    maturity_path = tmp_path / "maturity.json"
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "release"
    orders().to_parquet(order_path, index=False)
    pd.DataFrame([event("f1")]).to_parquet(event_path, index=False)
    pd.DataFrame({"merchant_abn": orders().merchant_abn}).to_parquet(merchant_path, index=False)
    coverage_path.write_text(json.dumps({
        "coverage_snapshot_id": "coverage-1",
        "required_sources": ["fraud", "credit", "finance"],
        "complete_sources": ["fraud", "credit", "finance"],
        "operational_net_loss_aud": 400.0,
        "finance_net_loss_aud": 400.0,
    }), encoding="utf-8")
    maturity_path.write_text(json.dumps({
        "maturity_validation_id": "maturity-1",
        "source_release_hashes": ["release-at-90", "later-release"],
        "adjustment_rates": {"90": .005, "120": 0.0, "150": 0.0},
    }), encoding="utf-8")
    policy = json.loads(Path("config/risk_label_contract_v1.json").read_text(encoding="utf-8"))
    policy.update({
        "approved_maturity_window_days": 90,
        "max_post_maturity_adjustment_rate": .01,
        "loss_classification_priority": ["FRAUD_LOSS", "CREDIT_WRITE_OFF"],
        "required_sources": ["fraud", "credit", "finance"],
        "finance_reconciliation_tolerance": {
            "max_absolute_difference_aud": 1.0,
            "max_relative_difference": .001,
        },
    })
    config_path.write_text(json.dumps(policy), encoding="utf-8")
    args = SimpleNamespace(
        orders=order_path, events=event_path, merchants=merchant_path,
        coverage=coverage_path, maturity_validation=maturity_path,
        config=config_path, output=output_path,
        label_version="labels-1", label_as_of="2024-05-01T00:00:00Z",
        data_as_of="2024-05-01T00:00:00Z", cutoff=["2024-01-01"],
    )
    manifest = run_label_build(args)
    assert manifest["activation_status"] == "LABEL_RELEASE_ONLY_NOT_MODEL_VALIDATED"
    assert (output_path / "_SUCCESS").exists()
    assert set(manifest["outputs"]) == {
        "order_fraud_labels.parquet", "merchant_loss_labels.parquet", "quarantined_risk_events.parquet"
    }
    with pytest.raises(FileExistsError):
        run_label_build(args)


def test_temporal_roles_require_mature_history_and_protect_last_six_windows():
    cutoffs = pd.date_range("2022-01-01", periods=24, freq="28D", tz="UTC")
    labels = pd.DataFrame({
        "cutoff": cutoffs,
        "label_start": cutoffs + pd.Timedelta(days=1),
        "label_end": cutoffs + pd.Timedelta(days=28),
        "is_mature": True,
        "label_status": "MATURE",
    })
    result = assign_temporal_roles(labels)
    assert result.iloc[-6:-3].split.eq("validation").all()
    assert result.iloc[-3:].split.eq("test").all()
    assert result.iloc[:-6].split.eq("train").all()


def test_temporal_roles_drop_overlapping_windows_from_latest_anchor():
    cutoffs = pd.date_range("2022-01-01", periods=25, freq="28D", tz="UTC")
    cutoffs = cutoffs.insert(len(cutoffs) - 1, cutoffs[-2] + pd.Timedelta(days=7))
    labels = pd.DataFrame({
        "cutoff": cutoffs,
        "label_start": cutoffs + pd.Timedelta(days=1),
        "label_end": cutoffs + pd.Timedelta(days=28),
        "is_mature": True,
        "label_status": "MATURE",
    })
    result = assign_temporal_roles(labels).sort_values("label_start")
    assert (result.label_start.iloc[1:].reset_index(drop=True) > result.label_end.iloc[:-1].reset_index(drop=True)).all()


def test_merchant_universe_preserves_candidates_with_no_orders_anywhere():
    universe = ["00000000001", "00000000009"]
    result = build_merchant_loss_labels(
        orders().iloc[[0]], pd.DataFrame([event("f1")]), ["2024-01-01"], universe,
        context(), ("FRAUD_LOSS", "CREDIT_WRITE_OFF"),
    )
    missing = result.labels.set_index("merchant_abn").loc["00000000009"]
    assert missing.future_orders == 0 and missing.net_loss_aud == 0
    assert missing.denominator_status == "NO_FUTURE_GMV"


def test_duplicate_recovery_component_is_quarantined():
    duplicate = pd.DataFrame([
        event("f1", amount=100),
        event("r1", event_type="RECOVERY", amount=10, source="finance", original="f1", component="recovery"),
        event("r2", event_type="RECOVERY", amount=10, source="ledger", original="f1", component="recovery"),
    ])
    result = build_merchant_loss_labels(
        orders(), duplicate, ["2024-01-01"], orders().merchant_abn,
        context(required_sources=("fraud", "finance", "ledger"), complete_sources=("fraud", "finance", "ledger")),
        ("FRAUD_LOSS", "CREDIT_WRITE_OFF"),
    )
    first = result.labels.set_index("merchant_abn").loc["00000000001"]
    assert first.label_reason_code == "DUPLICATE_ECONOMIC_COMPONENT"


def test_recovery_must_match_originating_case_and_order():
    ledger = pd.DataFrame([
        event("f1", amount=100),
        event("r1", event_type="RECOVERY", amount=10, source="finance", original="f1",
              component="recovery", case="wrong-case"),
    ])
    result = build_merchant_loss_labels(
        orders(), ledger, ["2024-01-01"], orders().merchant_abn,
        context(), ("FRAUD_LOSS", "CREDIT_WRITE_OFF"),
    )
    first = result.labels.set_index("merchant_abn").loc["00000000001"]
    assert first.label_reason_code == "INVALID_RECOVERY_ORIGIN"


def test_target_risk_state_transitions_require_explicit_gates():
    shadow_gates = {
        "mature_labels_available": True,
        "label_quality_pass": True,
        "models_versioned": True,
        "thresholds_preregistered": True,
    }
    assert transition_risk_state("EVIDENCE_ONLY_NO_MATURE_LABELS", "SHADOW", shadow_gates) == "SHADOW"
    with pytest.raises(LabelContractError):
        transition_risk_state("EVIDENCE_ONLY_NO_MATURE_LABELS", "VALIDATED", shadow_gates)
    validation = {"protected_evaluation_pass": True, "governance_approved": True,
                  "label_quality_pass": True, "model_quality_pass": True}
    assert transition_risk_state("SHADOW", "VALIDATED", validation) == "VALIDATED"
    assert transition_risk_state("VALIDATED", "DEGRADED_MODEL_QUALITY", {"model_quality_pass": False}) == "DEGRADED_MODEL_QUALITY"


def risk_frame():
    frame = pd.DataFrame({
        "merchant_abn": ["00000000001", "00000000002", "00000000003"],
        "prediction": [10.0, 9.0, 8.0],
        "merchant_category": ["a", "a", "b"],
        "confidence_band": ["high", "high", "high"],
        "predicted_net_loss_28d_aud": [9.0, 1.0, 1.0],
        "predicted_net_loss_28d_p95_aud": [12.0, 2.0, 2.0],
        "predicted_future_gmv_28d_aud": [100.0, 100.0, 100.0],
        "risk_state": ["VALIDATED"] * 3,
        "risk_model_version": ["risk-v1"] * 3,
        "risk_label_version": ["labels-v1"] * 3,
        "risk_prediction_as_of": ["2024-05-01"] * 3,
    })
    return frame


def risk_policy(**overrides):
    policy = {
        "risk_state": "VALIDATED",
        "loss_scenario": "EXPECTED_LOSS",
        "max_total_expected_net_loss_aud": 2.0,
        "max_expected_loss_rate": None,
    }
    policy.update(overrides)
    return policy


def test_portfolio_expected_loss_budget_is_hard_and_reported():
    selected, report = optimise(risk_frame(), capacity=2, risk_policy=risk_policy())
    assert selected == ["00000000002", "00000000003"]
    assert report["status"] == "OPTIMAL"
    assert report["risk"]["selected_loss_aud"] == 2
    assert report["risk"]["selected_loss_rate"] == .01


def test_portfolio_loss_rate_uses_ratio_of_totals():
    selected, report = optimise(
        risk_frame(), capacity=2,
        risk_policy=risk_policy(max_total_expected_net_loss_aud=None, max_expected_loss_rate=.02),
    )
    assert selected == ["00000000002", "00000000003"]
    assert report["risk"]["selected_loss_aud"] <= .02 * report["risk"]["selected_gmv_aud"]


@pytest.mark.parametrize("mutation", [
    {"risk_state": "SHADOW"},
    {"risk_label_version": ["labels-v1", "labels-v2", "labels-v1"]},
    {"predicted_net_loss_28d_aud": [np.nan, 1, 1]},
])
def test_portfolio_risk_inputs_fail_closed(mutation):
    frame = risk_frame()
    for field, value in mutation.items(): frame[field] = value
    selected, report = optimise(frame, risk_policy=risk_policy())
    assert selected == [] and report["status"] == "INVALID_RISK_INPUTS"


def test_portfolio_requires_authorised_budget_and_distinguishes_p95():
    _, missing = optimise(risk_frame(), risk_policy=risk_policy(max_total_expected_net_loss_aud=None))
    assert missing["status"] == "INVALID_RISK_INPUTS"
    selected, report = optimise(
        risk_frame(), capacity=2,
        risk_policy=risk_policy(loss_scenario="CONSERVATIVE_LOSS_P95", max_total_expected_net_loss_aud=4),
    )
    assert selected == ["00000000002", "00000000003"]
    assert report["risk"]["loss_scenario"] == "CONSERVATIVE_LOSS_P95"


def test_non_numeric_risk_budget_fails_closed():
    selected, report = optimise(
        risk_frame(), risk_policy=risk_policy(max_total_expected_net_loss_aud="not-a-number")
    )
    assert selected == [] and report["status"] == "INVALID_RISK_INPUTS"


def test_empty_risk_universe_fails_closed():
    empty = risk_frame().iloc[0:0]
    selected, report = optimise(empty, risk_policy=risk_policy())
    assert selected == [] and report["status"] == "INVALID_RISK_INPUTS"
