"""Fail-closed contracts for future risk-budget portfolio scenarios."""
import numpy as np


LOSS_SCENARIOS = {
    "EXPECTED_LOSS": "predicted_net_loss_28d_aud",
    "CONSERVATIVE_LOSS_P95": "predicted_net_loss_28d_p95_aud",
}


class RiskPolicyError(ValueError):
    pass


def _finite_scalar(value):
    try:
        return bool(np.isfinite(value))
    except (TypeError, ValueError):
        return False


def portfolio_risk_constraints(frame, policy):
    """Return linear constraint rows for an explicitly enabled risk scenario.

    The caller converts ``RiskPolicyError`` to ``INVALID_RISK_INPUTS``. No
    missing value, version mismatch, or absent budget receives a fallback.
    """
    if not isinstance(policy, dict):
        raise RiskPolicyError("risk_policy must be a mapping")
    scenario = policy.get("loss_scenario")
    if scenario not in LOSS_SCENARIOS:
        raise RiskPolicyError("Unknown or missing loss_scenario")
    loss_field = LOSS_SCENARIOS[scenario]
    fields = {
        loss_field,
        "predicted_future_gmv_28d_aud",
        "risk_state",
        "risk_model_version",
        "risk_label_version",
        "risk_prediction_as_of",
    }
    missing = fields - set(frame)
    if missing:
        raise RiskPolicyError(f"Missing risk fields: {sorted(missing)}")
    if frame.empty:
        raise RiskPolicyError("Risk-constrained universe cannot be empty")
    if not frame.risk_state.eq("VALIDATED").all() or policy.get("risk_state") != "VALIDATED":
        raise RiskPolicyError("Risk state must be VALIDATED")
    for field in ("risk_model_version", "risk_label_version", "risk_prediction_as_of"):
        if frame[field].isna().any() or frame[field].nunique(dropna=False) != 1:
            raise RiskPolicyError(f"Inconsistent {field}")
    loss = frame[loss_field].to_numpy(dtype=float)
    gmv = frame.predicted_future_gmv_28d_aud.to_numpy(dtype=float)
    if not np.isfinite(loss).all() or (loss < 0).any():
        raise RiskPolicyError("Loss predictions must be finite and non-negative")
    if not np.isfinite(gmv).all() or (gmv <= 0).any():
        raise RiskPolicyError("Predicted GMV must be finite and positive")

    amount_budget = policy.get("max_total_expected_net_loss_aud")
    rate_budget = policy.get("max_expected_loss_rate")
    if amount_budget is None and rate_budget is None:
        raise RiskPolicyError("At least one authorised risk budget is required")
    rows, upper = [], []
    if amount_budget is not None:
        if not _finite_scalar(amount_budget) or amount_budget < 0:
            raise RiskPolicyError("Invalid total expected-loss budget")
        rows.append(loss); upper.append(float(amount_budget))
    if rate_budget is not None:
        if not _finite_scalar(rate_budget) or not 0 <= rate_budget <= 1:
            raise RiskPolicyError("Invalid expected-loss-rate budget")
        rows.append(loss - float(rate_budget) * gmv); upper.append(0.0)
    return {
        "rows": rows,
        "upper": upper,
        "loss": loss,
        "gmv": gmv,
        "loss_scenario": scenario,
        "amount_budget": amount_budget,
        "rate_budget": rate_budget,
        "risk_model_version": str(frame.risk_model_version.iloc[0]),
        "risk_label_version": str(frame.risk_label_version.iloc[0]),
        "risk_prediction_as_of": str(frame.risk_prediction_as_of.iloc[0]),
    }
