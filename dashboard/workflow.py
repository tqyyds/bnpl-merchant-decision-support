"""Reconcile saved scenario results through the same source and Risk contract."""
from .adapter import ContractError


def concentration(rows, dimension, revenue=False):
    groups = {}
    for m in rows:
        key = m.get(dimension) or "Unknown"
        groups[key] = groups.get(key, 0) + (m["prediction"] if revenue else 1)
    total = sum(groups.values())
    return sum((v / total) ** 2 for v in groups.values()) if total else None


def workflow(adapter, run, split, cutoff):
    catalog = adapter.catalog()
    item = next((r for r in catalog["runs"] if r["id"] == run), None)
    window = next((s for s in (item or {}).get("splits", []) if s["id"] == split), None)
    if not window or cutoff not in window["cutoffs"]:
        raise ContractError("Workflow run, window or cutoff unavailable")
    snapshots = [adapter.snapshot(run, split, cutoff, scenario) for scenario in window["scenarios"]]
    if len({s["source_fingerprint"] for s in snapshots}) != 1:
        raise ContractError("Source changed during scenario comparison. Refresh after outputs are complete.")
    baseline = next((s for s in snapshots if s["scenario"] == "primary"), snapshots[0])
    baseline_ids = {m["id"] for m in baseline["merchants"] if m["decision"] == "selected"}
    scenarios = []
    for s in snapshots:
        rows = [m for m in s["merchants"] if m["decision"] == "selected"]
        ids = {m["id"] for m in rows}
        scenarios.append({"id": s["scenario"], "summary": s["summary"], "solver": s["solver"],
            "metrics": s["metrics"], "export_allowed": s["export_allowed"],
            "revenue_delta_aud": s["summary"]["predicted_revenue"] - baseline["summary"]["predicted_revenue"],
            "added": len(ids - baseline_ids), "removed": len(baseline_ids - ids),
            "category_hhi_count": concentration(rows, "category"),
            "category_hhi_revenue": concentration(rows, "category", True),
            "risk": s["risk_interface"]["selected_summary"],
            "risk_binding_id": s["risk_interface"]["binding_id"],
            "risk_constraints": "NOT_ATTESTED_BY_ENGINE"})
    return {"api_version": "1.0", "run": run, "split": split, "cutoff": cutoff,
            "source_fingerprint": baseline["source_fingerprint"], "baseline": baseline["scenario"],
            "scenarios": scenarios, "risk_contract": baseline["risk_interface"]["contract"],
            "dependencies": [["eligibility", "revenue"], ["revenue", "confidence"],
                ["risk", "diversification"], ["risk", "portfolio"], ["diversification", "portfolio"],
                ["strategic_fit", "portfolio"], ["confidence", "portfolio"]],
            "mode": "SAVED_OUTPUT_REPLAY"}
