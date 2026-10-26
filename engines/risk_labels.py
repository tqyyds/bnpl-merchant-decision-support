"""Future production risk-label contracts.

This module deliberately has no adapter for the course fraud-probability files. Those
files are evidence features, not outcomes. The pure builders here accept only the
append-only operational contract defined in the risk label design document.
"""
from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd


EVENT_TYPES = {
    "FRAUD_LOSS",
    "FRAUD_LOSS_REVERSAL",
    "CREDIT_WRITE_OFF",
    "CREDIT_WRITE_OFF_REVERSAL",
    "FEE",
    "RECOVERY",
}
CASE_STATUSES = {"OPEN", "DISPUTED", "CONFIRMED", "REVERSED", "CLOSED_NON_FRAUD"}
TERMINAL_CASE_STATUSES = {"CONFIRMED", "REVERSED", "CLOSED_NON_FRAUD"}
TARGET_RISK_STATES = {
    "EVIDENCE_ONLY_NO_MATURE_LABELS",
    "SHADOW",
    "VALIDATED",
    "DEGRADED_LABEL_QUALITY",
    "DEGRADED_MODEL_QUALITY",
}

EVENT_FIELDS = {
    "event_id", "source_system", "source_record_id", "revision", "supersedes_event_id",
    "original_loss_event_id", "loss_case_id", "loss_component_id", "order_id",
    "merchant_abn", "event_type", "case_status", "occurred_at", "available_at", "amount_aud",
}
ORDER_FIELDS = {
    "order_id", "merchant_abn", "order_created_at", "scored_at", "authorised_at",
    "gross_authorised_amount_aud", "eligible",
}


class LabelContractError(ValueError):
    """A structural or governance requirement prevents label generation."""


@dataclass(frozen=True)
class LabelBuildContext:
    label_as_of: pd.Timestamp
    label_generated_at: pd.Timestamp
    data_as_of: pd.Timestamp
    maturity_window_days: int
    required_sources: tuple[str, ...]
    complete_sources: tuple[str, ...]
    coverage_snapshot_id: str
    label_version: str
    source_snapshot_hash: str
    label_code_version: str
    label_config_hash: str
    reconciliation_status: str = "NOT_RUN"

    def __post_init__(self):
        for name in ("label_as_of", "label_generated_at", "data_as_of"):
            value = pd.Timestamp(getattr(self, name))
            if value.tzinfo is None:
                value = value.tz_localize("UTC")
            else:
                value = value.tz_convert("UTC")
            object.__setattr__(self, name, value)
        if self.maturity_window_days not in (90, 120, 150):
            raise LabelContractError("maturity_window_days must be an approved 90/120/150-day candidate")
        if self.label_as_of > self.data_as_of or self.label_generated_at < self.data_as_of:
            raise LabelContractError("Invalid point-in-time build timestamps")
        if not self.required_sources or not all(self.required_sources):
            raise LabelContractError("required_sources must be explicitly configured")
        if not all((self.coverage_snapshot_id, self.label_version, self.source_snapshot_hash,
                    self.label_code_version, self.label_config_hash)):
            raise LabelContractError("Incomplete label reproducibility metadata")

    @property
    def missing_sources(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.required_sources) - set(self.complete_sources)))

    @property
    def source_coverage_complete(self) -> bool:
        return not self.missing_sources


@dataclass
class LabelBuildResult:
    labels: pd.DataFrame
    quarantined_events: pd.DataFrame
    quality: dict


def _finite_scalar(value) -> bool:
    try:
        return bool(np.isfinite(value))
    except (TypeError, ValueError):
        return False


def _require(frame: pd.DataFrame, fields: Iterable[str], name: str) -> None:
    missing = set(fields) - set(frame.columns)
    if missing:
        raise LabelContractError(f"{name} missing fields: {sorted(missing)}")


def _utc(values: pd.Series, field: str) -> pd.Series:
    converted = pd.to_datetime(values, utc=True, errors="coerce")
    if converted.isna().any():
        raise LabelContractError(f"{field} contains invalid timestamps")
    return converted


def validate_operational_risk_events(events: pd.DataFrame) -> pd.DataFrame:
    """Validate immutable event versions without choosing an effective version."""
    _require(events, EVENT_FIELDS, "operational_risk_events")
    out = events.copy()
    if out.empty:
        return out
    required_non_null = EVENT_FIELDS - {"supersedes_event_id", "original_loss_event_id"}
    if out[list(required_non_null)].isna().any().any():
        raise LabelContractError("Operational event required fields contain nulls")
    if out.event_id.duplicated().any():
        raise LabelContractError("event_id must be globally unique")
    version_key = ["source_system", "source_record_id", "revision"]
    if out.duplicated(version_key).any():
        raise LabelContractError("Duplicate operational event version key")
    numeric_revision = pd.to_numeric(out.revision, errors="coerce")
    if numeric_revision.isna().any() or (numeric_revision < 0).any() or not np.equal(numeric_revision % 1, 0).all():
        raise LabelContractError("revision must be a non-negative integer")
    out["revision"] = numeric_revision.astype("int64")
    unknown_types = set(out.event_type) - EVENT_TYPES
    unknown_statuses = set(out.case_status) - CASE_STATUSES
    if unknown_types or unknown_statuses:
        raise LabelContractError(f"Unknown event types/statuses: {sorted(unknown_types | unknown_statuses)}")
    if not out.merchant_abn.astype(str).str.fullmatch(r"\d{11}").all():
        raise LabelContractError("merchant_abn must be a canonical 11-digit string")
    amount = pd.to_numeric(out.amount_aud, errors="coerce")
    if not np.isfinite(amount).all() or (amount < 0).any():
        raise LabelContractError("amount_aud must be finite and non-negative")
    out["amount_aud"] = amount.astype(float)
    out["occurred_at"] = _utc(out.occurred_at, "occurred_at")
    out["available_at"] = _utc(out.available_at, "available_at")
    if (out.available_at < out.occurred_at).any():
        raise LabelContractError("available_at cannot precede occurred_at")
    identifiers = set(out.event_id.astype(str))
    if out.supersedes_event_id.dropna().astype(str).isin(identifiers).sum() != out.supersedes_event_id.notna().sum():
        raise LabelContractError("supersedes_event_id must reference an event in the ledger")
    if (out.event_id.astype(str) == out.supersedes_event_id.astype(str)).any():
        raise LabelContractError("An event cannot supersede itself")
    needs_origin = out.event_type.isin({"FRAUD_LOSS_REVERSAL", "CREDIT_WRITE_OFF_REVERSAL", "RECOVERY"})
    if out.loc[needs_origin, "original_loss_event_id"].isna().any():
        raise LabelContractError("Reversals and recoveries require original_loss_event_id")
    return out


def resolve_effective_events(events: pd.DataFrame, label_as_of) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resolve explicit version chains as known at ``label_as_of``.

    Invalid chains and competing terminal case states are returned in quarantine;
    they are never resolved by a largest-revision shortcut.
    """
    checked = validate_operational_risk_events(events)
    as_of = pd.Timestamp(label_as_of)
    as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
    visible = checked.loc[checked.available_at.le(as_of)].copy()
    effective, quarantined = [], []
    for _, group in visible.groupby(["source_system", "source_record_id"], sort=True, dropna=False):
        group = group.sort_values("revision", kind="stable")
        reason = None
        if group.revision.duplicated().any():
            reason = "DUPLICATE_VISIBLE_REVISION"
        elif group.available_at.tolist() != sorted(group.available_at.tolist()):
            reason = "NON_MONOTONIC_VERSION_AVAILABILITY"
        else:
            rows = list(group.itertuples())
            if pd.notna(rows[0].supersedes_event_id):
                reason = "MISSING_VERSION_CHAIN_ROOT"
            for previous, current in zip(rows, rows[1:]):
                if str(current.supersedes_event_id) != str(previous.event_id):
                    reason = "INVALID_SUPERSESSION_CHAIN"
                    break
        if reason:
            bad = group.copy(); bad["quarantine_reason"] = reason; quarantined.append(bad)
        else:
            effective.append(group.iloc[[-1]])
    resolved = pd.concat(effective, ignore_index=True) if effective else visible.iloc[0:0].copy()
    quarantine = pd.concat(quarantined, ignore_index=True) if quarantined else visible.iloc[0:0].assign(quarantine_reason=pd.Series(dtype="object"))

    if not resolved.empty:
        conflict_cases = []
        for case_id, case in resolved.groupby("loss_case_id", sort=False):
            terminal = case.loc[case.case_status.isin(TERMINAL_CASE_STATUSES)]
            statuses = set(terminal.case_status)
            if len(statuses) <= 1:
                continue
            reversed_rows = terminal.loc[terminal.case_status.eq("REVERSED")]
            confirmed_ids = set(terminal.loc[terminal.case_status.eq("CONFIRMED"), "event_id"].astype(str))
            valid_reversal_transition = (
                statuses == {"CONFIRMED", "REVERSED"}
                and reversed_rows.event_type.isin({"FRAUD_LOSS_REVERSAL", "CREDIT_WRITE_OFF_REVERSAL"}).all()
                and reversed_rows.original_loss_event_id.astype(str).isin(confirmed_ids).all()
            )
            if not valid_reversal_transition:
                conflict_cases.append(case_id)
        if conflict_cases:
            bad = resolved.loc[resolved.loss_case_id.isin(conflict_cases)].copy()
            bad["quarantine_reason"] = "COMPETING_TERMINAL_CASE_STATES"
            quarantine = pd.concat([quarantine, bad], ignore_index=True)
            resolved = resolved.loc[~resolved.loss_case_id.isin(conflict_cases)].copy()

    visible_ids = set(visible.event_id.astype(str))
    orphan = resolved.original_loss_event_id.notna() & ~resolved.original_loss_event_id.astype(str).isin(visible_ids)
    if orphan.any():
        bad = resolved.loc[orphan].copy(); bad["quarantine_reason"] = "ORIGINAL_LOSS_NOT_VISIBLE_AS_OF"
        quarantine = pd.concat([quarantine, bad], ignore_index=True)
        resolved = resolved.loc[~orphan].copy()
    return resolved.reset_index(drop=True), quarantine.reset_index(drop=True)


def _validate_orders(orders: pd.DataFrame) -> pd.DataFrame:
    _require(orders, ORDER_FIELDS, "orders")
    out = orders.copy()
    if out.order_id.isna().any() or out.order_id.duplicated().any():
        raise LabelContractError("order_id must be non-null and unique")
    if not out.merchant_abn.astype(str).str.fullmatch(r"\d{11}").all():
        raise LabelContractError("Order merchant_abn must be a canonical 11-digit string")
    for field in ("order_created_at", "scored_at", "authorised_at"):
        out[field] = _utc(out[field], field)
    if (out.scored_at > out.authorised_at).any():
        raise LabelContractError("scored_at cannot follow authorised_at")
    amount = pd.to_numeric(out.gross_authorised_amount_aud, errors="coerce")
    if not np.isfinite(amount).all() or (amount < 0).any():
        raise LabelContractError("gross_authorised_amount_aud must be finite and non-negative")
    out["gross_authorised_amount_aud"] = amount.astype(float)
    if not out.eligible.isin([True, False]).all():
        raise LabelContractError("eligible must be Boolean")
    return out


def _match_events(events: pd.DataFrame, orders: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    order_map = orders.set_index("order_id").merchant_abn.astype(str)
    matched = events.order_id.isin(order_map.index)
    merchant_matches = events.merchant_abn.astype(str).eq(events.order_id.map(order_map))
    ok = matched & merchant_matches
    quarantine = events.loc[~ok].copy()
    if not quarantine.empty:
        quarantine["quarantine_reason"] = np.where(matched.loc[~ok], "ORDER_MERCHANT_MISMATCH", "ORPHAN_ORDER_ID")
    return events.loc[ok].copy(), quarantine


def _audit_columns(context: LabelBuildContext, rows: int) -> dict:
    return {
        "label_as_of": [context.label_as_of] * rows,
        "label_generated_at": [context.label_generated_at] * rows,
        "data_as_of": [context.data_as_of] * rows,
        "source_coverage_complete": [context.source_coverage_complete] * rows,
        "required_sources": [context.required_sources] * rows,
        "missing_sources": [context.missing_sources] * rows,
        "coverage_snapshot_id": [context.coverage_snapshot_id] * rows,
        "label_version": [context.label_version] * rows,
        "source_snapshot_hash": [context.source_snapshot_hash] * rows,
        "label_code_version": [context.label_code_version] * rows,
        "label_config_hash": [context.label_config_hash] * rows,
    }


def build_order_fraud_labels(orders: pd.DataFrame, events: pd.DataFrame, context: LabelBuildContext) -> LabelBuildResult:
    """Build nullable eventual-confirmed-fraud labels at order grain."""
    orders = _validate_orders(orders)
    resolved, chain_quarantine = resolve_effective_events(events, context.label_as_of)
    matched, match_quarantine = _match_events(resolved, orders)
    quarantine = pd.concat([chain_quarantine, match_quarantine], ignore_index=True)

    reversed_ids = set(matched.loc[matched.event_type.eq("FRAUD_LOSS_REVERSAL"), "original_loss_event_id"].dropna().astype(str))
    confirmed = matched.loc[
        matched.event_type.eq("FRAUD_LOSS")
        & matched.case_status.eq("CONFIRMED")
        & ~matched.event_id.astype(str).isin(reversed_ids)
    ]
    confirmed_by_order = confirmed.groupby("order_id").occurred_at.min()

    labels = orders[["order_id", "merchant_abn", "order_created_at", "scored_at"]].copy()
    labels["observation_end"] = context.label_as_of
    labels["maturity_at"] = labels.scored_at + pd.to_timedelta(context.maturity_window_days, unit="D")
    confirmed_lookup = confirmed_by_order.to_dict()
    labels["confirmed_at"] = pd.to_datetime(
        [confirmed_lookup.get(order_id, pd.NaT) for order_id in labels.order_id], utc=True
    )
    positive = labels.confirmed_at.notna()
    mature = labels.maturity_at.le(context.label_as_of)
    labels["fraud_label"] = pd.Series(pd.NA, index=labels.index, dtype="boolean")
    labels.loc[positive, "fraud_label"] = True
    negative = ~positive & mature & context.source_coverage_complete
    labels.loc[negative, "fraud_label"] = False
    labels["label_status"] = np.select(
        [positive, ~np.full(len(labels), context.source_coverage_complete), ~mature],
        ["CONFIRMED_FRAUD", "SOURCE_COVERAGE_INCOMPLETE", "IMMATURE"],
        default="MATURE_NON_FRAUD",
    )
    labels["label_reason_code"] = labels.label_status
    labels["order_match_status"] = "EXACT"
    for field, values in _audit_columns(context, len(labels)).items():
        labels[field] = values
    quality = {
        "rows": len(labels),
        "positive": int(labels.fraud_label.eq(True).sum()),
        "negative": int(labels.fraud_label.eq(False).sum()),
        "unresolved": int(labels.fraud_label.isna().sum()),
        "quarantined_events": len(quarantine),
        "source_coverage_complete": context.source_coverage_complete,
    }
    return LabelBuildResult(labels, quarantine, quality)


def _loss_components(events: pd.DataFrame, priority: tuple[str, ...]) -> tuple[dict, str | None]:
    if set(priority) != {"FRAUD_LOSS", "CREDIT_WRITE_OFF"}:
        raise LabelContractError("Approved loss_classification_priority must contain fraud and credit exactly once")
    positives = events.loc[events.event_type.isin({"FRAUD_LOSS", "CREDIT_WRITE_OFF"})].copy()
    retained = []
    for _, group in positives.groupby(["loss_case_id", "loss_component_id"], sort=False):
        if group.amount_aud.nunique() != 1:
            return {}, "CONFLICTING_COMPONENT_AMOUNTS"
        kinds = set(group.event_type)
        chosen_kind = next(kind for kind in priority if kind in kinds)
        chosen = group.loc[group.event_type.eq(chosen_kind)]
        if len(chosen) != 1:
            return {}, "DUPLICATE_ECONOMIC_COMPONENT"
        retained.append(chosen.iloc[0])
    kept = pd.DataFrame(retained) if retained else positives.iloc[0:0]
    kept_ids = set(kept.event_id.astype(str))
    original = events.set_index(events.event_id.astype(str), drop=False)
    for kind in ("FEE", "RECOVERY"):
        subset = events.loc[events.event_type.eq(kind)]
        if subset.duplicated(["loss_case_id", "loss_component_id"], keep=False).any():
            return {}, "DUPLICATE_ECONOMIC_COMPONENT"
    fraud = float(kept.loc[kept.event_type.eq("FRAUD_LOSS"), "amount_aud"].sum())
    credit = float(kept.loc[kept.event_type.eq("CREDIT_WRITE_OFF"), "amount_aud"].sum())
    for reversal_type, original_type in (("FRAUD_LOSS_REVERSAL", "FRAUD_LOSS"), ("CREDIT_WRITE_OFF_REVERSAL", "CREDIT_WRITE_OFF")):
        for row in events.loc[events.event_type.eq(reversal_type)].itertuples():
            ref = str(row.original_loss_event_id)
            if ref not in original.index or original.loc[ref].event_type != original_type:
                return {}, "INVALID_REVERSAL_ORIGIN"
            if original.loc[ref].loss_case_id != row.loss_case_id or original.loc[ref].order_id != row.order_id:
                return {}, "INVALID_REVERSAL_ORIGIN"
            if ref not in kept_ids:
                continue  # The governed priority classified this overlapping principal away.
            if original_type == "FRAUD_LOSS": fraud -= float(row.amount_aud)
            else: credit -= float(row.amount_aud)
    if fraud < -1e-9 or credit < -1e-9:
        return {}, "REVERSAL_EXCEEDS_GROSS_LOSS"
    fees = float(events.loc[events.event_type.eq("FEE"), "amount_aud"].sum())
    recoveries_frame = events.loc[events.event_type.eq("RECOVERY")]
    for row in recoveries_frame.itertuples():
        ref = str(row.original_loss_event_id)
        if ref not in original.index:
            return {}, "INVALID_RECOVERY_ORIGIN"
        origin = original.loc[ref]
        if origin.loss_case_id != row.loss_case_id or origin.order_id != row.order_id:
            return {}, "INVALID_RECOVERY_ORIGIN"
    recoveries = float(recoveries_frame.amount_aud.sum())
    result = {
        "gross_fraud_loss_aud": max(0.0, fraud),
        "gross_credit_loss_aud": max(0.0, credit),
        "fees_aud": fees,
        "recoveries_aud": recoveries,
    }
    result["net_loss_aud"] = fraud + credit + fees - recoveries
    return result, None


def build_merchant_loss_labels(
    orders: pd.DataFrame,
    events: pd.DataFrame,
    cutoffs: Iterable,
    merchant_universe: Iterable[str],
    context: LabelBuildContext,
    loss_classification_priority: tuple[str, ...] | None,
) -> LabelBuildResult:
    """Build point-in-time next-28-day merchant loss cohorts."""
    if loss_classification_priority is None:
        raise LabelContractError("Finance/Risk-approved loss_classification_priority is required")
    orders = _validate_orders(orders)
    resolved, chain_quarantine = resolve_effective_events(events, context.label_as_of)
    matched, match_quarantine = _match_events(resolved, orders)
    quarantine = pd.concat([chain_quarantine, match_quarantine], ignore_index=True)
    quarantined_order_ids = set(quarantine.order_id.dropna()) if "order_id" in quarantine else set()
    merchants = pd.Series(list(merchant_universe), dtype="object")
    if merchants.empty or merchants.isna().any() or merchants.duplicated().any():
        raise LabelContractError("merchant_universe must be explicit, non-empty, and unique")
    if not merchants.astype(str).str.fullmatch(r"\d{11}").all():
        raise LabelContractError("merchant_universe contains a non-canonical merchant key")
    merchants = sorted(merchants.astype(str))
    rows = []
    for cutoff_value in sorted(pd.to_datetime(list(cutoffs), utc=True)):
        start = cutoff_value + pd.Timedelta(days=1)
        end = cutoff_value + pd.Timedelta(days=28)
        maturity_at = end + pd.Timedelta(days=context.maturity_window_days)
        cohort = orders.loc[
            orders.eligible & orders.authorised_at.between(start, end, inclusive="both")
        ]
        for merchant_abn in merchants:
            merchant_orders = cohort.loc[cohort.merchant_abn.astype(str).eq(merchant_abn)]
            order_ids = set(merchant_orders.order_id)
            merchant_events = matched.loc[matched.order_id.isin(order_ids)]
            components, component_error = _loss_components(merchant_events, loss_classification_priority)
            future_orders = len(merchant_orders)
            future_gmv = float(merchant_orders.gross_authorised_amount_aud.sum())
            mature = maturity_at <= context.label_as_of
            status, reason = "MATURE", "PASS"
            if not mature:
                status = reason = "IMMATURE"
            elif not context.source_coverage_complete:
                status = "QUARANTINED"; reason = "SOURCE_COVERAGE_INCOMPLETE"
            elif context.reconciliation_status != "PASS":
                status = "QUARANTINED"; reason = "RECONCILIATION_NOT_PASSED"
            elif order_ids & quarantined_order_ids:
                status = "QUARANTINED"; reason = "QUARANTINED_COHORT_EVENT"
            elif component_error:
                status = "QUARANTINED"; reason = component_error
            if not components:
                components = {k: np.nan for k in ("gross_fraud_loss_aud", "gross_credit_loss_aud", "fees_aud", "recoveries_aud", "net_loss_aud")}
            net = components["net_loss_aud"]
            denominator_status = "VALID" if future_gmv > 0 else "NO_FUTURE_GMV"
            net_rate = net / future_gmv if future_gmv > 0 and np.isfinite(net) else np.nan
            if np.isfinite(net) and net < -1e-9:
                status = "QUARANTINED"; reason = "NEGATIVE_NET_LOSS"
            if future_gmv == 0 and np.isfinite(net) and net > 0:
                denominator_status = "INVALID_ZERO_GMV_WITH_LOSS"
                status = "QUARANTINED"; reason = denominator_status
            confirmed_orders = merchant_events.loc[
                merchant_events.event_type.eq("FRAUD_LOSS") & merchant_events.case_status.eq("CONFIRMED")
            ].order_id.nunique()
            if status != "MATURE":
                for key in components: components[key] = np.nan
                net_rate = np.nan
            rows.append({
                "merchant_abn": merchant_abn,
                "cutoff": cutoff_value,
                "label_start": start,
                "label_end": end,
                "maturity_at": maturity_at,
                "observation_end": context.label_as_of,
                "is_mature": bool(mature),
                "label_status": status,
                "label_reason_code": reason,
                "future_orders": future_orders,
                "future_gmv_aud": future_gmv,
                "confirmed_fraud_orders": confirmed_orders,
                "fraud_rate": confirmed_orders / future_orders if future_orders else np.nan,
                **components,
                "net_loss_rate": net_rate,
                "denominator_status": denominator_status,
                "currency": "AUD",
                "reconciliation_status": context.reconciliation_status,
            })
    labels = pd.DataFrame(rows)
    for field, values in _audit_columns(context, len(labels)).items():
        labels[field] = values
    quality = {
        "rows": len(labels),
        "mature_usable": int(labels.label_status.eq("MATURE").sum()) if len(labels) else 0,
        "quarantined": int(labels.label_status.eq("QUARANTINED").sum()) if len(labels) else 0,
        "immature": int(labels.label_status.eq("IMMATURE").sum()) if len(labels) else 0,
        "quarantined_events": len(quarantine),
        "source_coverage_complete": context.source_coverage_complete,
    }
    return LabelBuildResult(labels, quarantine, quality)


def post_maturity_adjustment_rate(
    declared: pd.DataFrame,
    later: pd.DataFrame,
    keys: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> float:
    """Share of declared-mature labels whose governed values later changed."""
    _require(declared, (*keys, *value_fields), "declared labels")
    _require(later, (*keys, *value_fields), "later labels")
    if declared.duplicated(list(keys)).any() or later.duplicated(list(keys)).any():
        raise LabelContractError("Maturity comparison keys must be unique")
    joined = declared[list(keys) + list(value_fields)].merge(
        later[list(keys) + list(value_fields)], on=list(keys), how="left", validate="one_to_one", suffixes=("_declared", "_later")
    )
    if joined.empty:
        raise LabelContractError("Cannot estimate maturity adjustment rate without declared labels")
    changed = pd.Series(False, index=joined.index)
    for field in value_fields:
        left, right = joined[f"{field}_declared"], joined[f"{field}_later"]
        changed |= ~(left.eq(right) | (left.isna() & right.isna()))
    return float(changed.mean())


def choose_maturity_window(adjustment_rates: Mapping[int, float], approved_max_rate: float | None) -> tuple[int | None, str]:
    """Apply the governed 90 -> 120 -> 150 day maturity fallback."""
    if approved_max_rate is None:
        return None, "NOT_CONFIGURED"
    if not _finite_scalar(approved_max_rate) or not 0 <= approved_max_rate <= 1:
        raise LabelContractError("Approved maturity adjustment threshold must be within [0,1]")
    for days in (90, 120, 150):
        rate = adjustment_rates.get(days)
        if rate is None or not _finite_scalar(rate) or not 0 <= rate <= 1:
            continue
        if rate <= approved_max_rate:
            return days, "PASS"
    return None, "DEGRADED_LABEL_QUALITY"


def validate_label_build_policy(policy: Mapping) -> dict:
    """Validate governance fields required to run an R1-R3 label build."""
    required = {
        "contract_version", "maturity_window_candidates_days", "approved_maturity_window_days",
        "max_post_maturity_adjustment_rate", "merchant_label_horizon_days",
        "loss_classification_priority", "required_sources", "finance_reconciliation_tolerance",
    }
    missing = required - set(policy)
    if missing:
        raise LabelContractError(f"Label build policy missing fields: {sorted(missing)}")
    candidates = tuple(policy["maturity_window_candidates_days"])
    if candidates != (90, 120, 150):
        raise LabelContractError("Maturity candidates must remain 90/120/150 days")
    approved = policy["approved_maturity_window_days"]
    if approved not in candidates:
        raise LabelContractError("approved_maturity_window_days is not configured")
    rate = policy["max_post_maturity_adjustment_rate"]
    if rate is None or not _finite_scalar(rate) or not 0 <= rate <= 1:
        raise LabelContractError("Approved post-maturity adjustment threshold is required")
    if policy["merchant_label_horizon_days"] != 28:
        raise LabelContractError("Merchant label horizon must remain 28 days for v1")
    priority = tuple(policy["loss_classification_priority"] or ())
    if set(priority) != {"FRAUD_LOSS", "CREDIT_WRITE_OFF"}:
        raise LabelContractError("Finance/Risk-approved loss classification priority is required")
    sources = tuple(policy["required_sources"] or ())
    if not sources or len(sources) != len(set(sources)) or not all(sources):
        raise LabelContractError("Unique required operational sources must be configured")
    tolerance = policy["finance_reconciliation_tolerance"]
    if not isinstance(tolerance, Mapping):
        raise LabelContractError("Finance reconciliation tolerance must be an approved mapping")
    absolute = tolerance.get("max_absolute_difference_aud")
    relative = tolerance.get("max_relative_difference")
    if absolute is None and relative is None:
        raise LabelContractError("At least one approved Finance reconciliation tolerance is required")
    if absolute is not None and (not _finite_scalar(absolute) or absolute < 0):
        raise LabelContractError("Invalid absolute Finance reconciliation tolerance")
    if relative is not None and (not _finite_scalar(relative) or not 0 <= relative <= 1):
        raise LabelContractError("Invalid relative Finance reconciliation tolerance")
    out = dict(policy)
    out["loss_classification_priority"] = priority
    out["required_sources"] = sources
    return out


def finance_reconciliation(
    operational_net_loss_aud: float,
    finance_net_loss_aud: float,
    tolerance: Mapping,
) -> dict:
    """Evaluate reconciliation evidence rather than trusting a supplied status."""
    try:
        values = np.asarray([operational_net_loss_aud, finance_net_loss_aud], dtype=float)
    except (TypeError, ValueError) as error:
        raise LabelContractError("Reconciliation totals must be numeric") from error
    if not np.isfinite(values).all():
        raise LabelContractError("Reconciliation totals must be finite")
    difference = abs(float(operational_net_loss_aud) - float(finance_net_loss_aud))
    absolute = tolerance.get("max_absolute_difference_aud")
    relative = tolerance.get("max_relative_difference")
    allowed = []
    if absolute is not None:
        allowed.append(float(absolute))
    if relative is not None:
        allowed.append(float(relative) * abs(float(finance_net_loss_aud)))
    if not allowed:
        raise LabelContractError("Reconciliation tolerance is not configured")
    permitted = max(allowed)
    return {
        "status": "PASS" if difference <= permitted else "FAIL",
        "operational_net_loss_aud": float(operational_net_loss_aud),
        "finance_net_loss_aud": float(finance_net_loss_aud),
        "absolute_difference_aud": difference,
        "permitted_difference_aud": permitted,
    }


def assign_temporal_roles(labels: pd.DataFrame) -> pd.DataFrame:
    """Reserve three validation and three protected-test 28-day windows."""
    _require(labels, ("cutoff", "label_start", "label_end", "is_mature", "label_status"), "merchant labels")
    eligible = labels.loc[labels.is_mature & labels.label_status.eq("MATURE")].copy()
    windows = eligible[["cutoff", "label_start", "label_end"]].drop_duplicates().sort_values("cutoff")
    if not (pd.to_datetime(windows.label_end) - pd.to_datetime(windows.label_start)).dt.days.eq(27).all():
        raise LabelContractError("Every merchant label window must contain exactly 28 inclusive days")
    selected, next_start = [], None
    for row in reversed(list(windows.itertuples(index=False))):
        if next_start is None or row.label_end < next_start:
            selected.append(row)
            next_start = row.label_start
    windows = pd.DataFrame(reversed(selected), columns=windows.columns)
    if len(windows) < 7:
        raise LabelContractError("At least seven eligible windows are required for train/validation/test")
    if windows.label_start.min() > windows.label_end.max() - pd.DateOffset(months=18):
        raise LabelContractError("At least 18 months of mature-label history is required")
    ordered = windows.cutoff.tolist()
    roles = {cutoff: "train" for cutoff in ordered[:-6]}
    roles.update({cutoff: "validation" for cutoff in ordered[-6:-3]})
    roles.update({cutoff: "test" for cutoff in ordered[-3:]})
    eligible = eligible.loc[eligible.cutoff.isin(ordered)].copy()
    eligible["split"] = eligible.cutoff.map(roles)
    return eligible


def transition_risk_state(current: str, requested: str, gates: Mapping[str, bool]) -> str:
    """Validate target-state transitions without changing the current v1 runtime."""
    if current not in TARGET_RISK_STATES or requested not in TARGET_RISK_STATES:
        raise LabelContractError("Unknown target risk state")
    if current == requested:
        return current
    if requested == "DEGRADED_LABEL_QUALITY":
        if gates.get("label_quality_pass", True):
            raise LabelContractError("Label degradation requires a failed label-quality gate")
        return requested
    if requested == "DEGRADED_MODEL_QUALITY":
        if gates.get("model_quality_pass", True):
            raise LabelContractError("Model degradation requires a failed model-quality gate")
        return requested
    shadow_gates = ("mature_labels_available", "label_quality_pass", "models_versioned", "thresholds_preregistered")
    if requested == "SHADOW":
        if current not in {"EVIDENCE_ONLY_NO_MATURE_LABELS", "DEGRADED_LABEL_QUALITY", "DEGRADED_MODEL_QUALITY"}:
            raise LabelContractError("Invalid transition to SHADOW")
        required = shadow_gates + (("new_release",) if current.startswith("DEGRADED_") else ())
        if not all(gates.get(field, False) for field in required):
            raise LabelContractError(f"SHADOW requires gates: {required}")
        return requested
    if requested == "VALIDATED":
        if current != "SHADOW":
            raise LabelContractError("VALIDATED can only follow SHADOW")
        required = ("protected_evaluation_pass", "governance_approved", "label_quality_pass", "model_quality_pass")
        if not all(gates.get(field, False) for field in required):
            raise LabelContractError(f"VALIDATED requires gates: {required}")
        return requested
    raise LabelContractError(f"Unsupported risk-state transition: {current} -> {requested}")
