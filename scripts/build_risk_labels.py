"""Build governed order-fraud and merchant-loss label releases from operational data."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.contracts import sha
from engines.risk_labels import (
    LabelBuildContext,
    build_merchant_loss_labels,
    build_order_fraud_labels,
    choose_maturity_window,
    finance_reconciliation,
    validate_label_build_policy,
)


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported input format: {path.suffix}")


def combined_hash(paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(map(Path, paths), key=lambda p: str(p)):
        digest.update(str(path.resolve()).encode("utf-8"))
        digest.update(sha(path).encode("ascii"))
    return digest.hexdigest()


def run(args) -> dict:
    config = validate_label_build_policy(json.loads(args.config.read_text(encoding="utf-8")))
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    maturity = json.loads(args.maturity_validation.read_text(encoding="utf-8"))
    coverage_required = tuple(coverage.get("required_sources", ()))
    if coverage_required != config["required_sources"]:
        raise ValueError("Coverage snapshot required_sources must exactly match the governed config")
    selected_maturity, maturity_status = choose_maturity_window(
        {int(days): float(rate) for days, rate in maturity.get("adjustment_rates", {}).items()},
        config["max_post_maturity_adjustment_rate"],
    )
    if maturity_status != "PASS" or selected_maturity != config["approved_maturity_window_days"]:
        raise ValueError("Empirical maturity evidence does not match the approved maturity window")
    if not maturity.get("maturity_validation_id") or not maturity.get("source_release_hashes"):
        raise ValueError("Maturity validation audit metadata is incomplete")
    reconciliation = finance_reconciliation(
        coverage.get("operational_net_loss_aud"),
        coverage.get("finance_net_loss_aud"),
        config["finance_reconciliation_tolerance"],
    )
    if reconciliation["status"] != "PASS":
        raise ValueError("Finance reconciliation failed the approved tolerance")
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite label release: {args.output}")

    orders = read_table(args.orders)
    events = read_table(args.events)
    merchants = read_table(args.merchants)
    if "merchant_abn" not in merchants:
        raise ValueError("Merchant universe file requires merchant_abn")
    source_hash = combined_hash([args.orders, args.events, args.merchants, args.coverage, args.maturity_validation])
    generated = pd.Timestamp(datetime.now(timezone.utc))
    context = LabelBuildContext(
        label_as_of=pd.Timestamp(args.label_as_of),
        label_generated_at=generated,
        data_as_of=pd.Timestamp(args.data_as_of),
        maturity_window_days=config["approved_maturity_window_days"],
        required_sources=config["required_sources"],
        complete_sources=tuple(coverage.get("complete_sources", ())),
        coverage_snapshot_id=str(coverage.get("coverage_snapshot_id", "")),
        label_version=args.label_version,
        source_snapshot_hash=source_hash,
        label_code_version=sha(ROOT / "engines/risk_labels.py"),
        label_config_hash=sha(args.config),
        reconciliation_status="PASS",
    )
    order_result = build_order_fraud_labels(orders, events, context)
    merchant_result = build_merchant_loss_labels(
        orders,
        events,
        args.cutoff,
        merchants.merchant_abn,
        context,
        config["loss_classification_priority"],
    )
    quarantine = pd.concat(
        [order_result.quarantined_events, merchant_result.quarantined_events], ignore_index=True
    ).drop_duplicates(subset=["event_id", "quarantine_reason"])

    args.output.mkdir(parents=True, exist_ok=False)
    order_result.labels.to_parquet(args.output / "order_fraud_labels.parquet", index=False)
    merchant_result.labels.to_parquet(args.output / "merchant_loss_labels.parquet", index=False)
    quarantine.to_parquet(args.output / "quarantined_risk_events.parquet", index=False)
    manifest = {
        "contract_version": config["contract_version"],
        "label_version": args.label_version,
        "created_utc": generated.isoformat(),
        "source_snapshot_hash": source_hash,
        "label_code_version": context.label_code_version,
        "label_config_hash": context.label_config_hash,
        "order_quality": order_result.quality,
        "merchant_quality": merchant_result.quality,
        "maturity_validation": {
            "maturity_validation_id": maturity["maturity_validation_id"],
            "source_release_hashes": maturity["source_release_hashes"],
            "adjustment_rates": maturity["adjustment_rates"],
            "selected_maturity_window_days": selected_maturity,
        },
        "finance_reconciliation": reconciliation,
        "outputs": {},
        "activation_status": "LABEL_RELEASE_ONLY_NOT_MODEL_VALIDATED",
    }
    for name in ("order_fraud_labels.parquet", "merchant_loss_labels.parquet", "quarantined_risk_events.parquet"):
        path = args.output / name
        manifest["outputs"][name] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8"
    )
    (args.output / "_SUCCESS").write_text("", encoding="utf-8")
    return manifest


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--orders", type=Path, required=True)
    value.add_argument("--events", type=Path, required=True)
    value.add_argument("--merchants", type=Path, required=True)
    value.add_argument("--coverage", type=Path, required=True)
    value.add_argument("--maturity-validation", type=Path, required=True)
    value.add_argument("--config", type=Path, default=ROOT / "config/risk_label_contract_v1.json")
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--label-version", required=True)
    value.add_argument("--label-as-of", required=True)
    value.add_argument("--data-as-of", required=True)
    value.add_argument("--cutoff", action="append", required=True)
    return value


if __name__ == "__main__":
    result = run(parser().parse_args())
    print(json.dumps({"status": result["activation_status"], "outputs": result["outputs"]}, indent=2))
