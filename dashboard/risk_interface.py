"""Shared, versioned Risk evidence interface for both downstream consumers.

This module reads evidence. It does not create risk scores, monetary losses,
selection constraints, or a second optimiser in the dashboard.
"""
import hashlib
import json

RISK_CONTRACT = "risk-evidence-v1"


def attach_risk(snapshot, risk_digest=None):
    engine = next(e for e in snapshot["engines"] if e["id"] == "risk")
    binding = {"contract": RISK_CONTRACT, "run": snapshot["run"],
               "cutoff": snapshot["cutoff"], "split": snapshot["split"],
               "versions": engine["versions"], "source_sha256": risk_digest}
    source_status = "EVIDENCE_CONNECTED" if risk_digest and engine["rows"] > 0 else "MISSING_SOURCE" if not risk_digest else "MISSING_AT_CUTOFF"
    binding["binding_id"] = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    for m in snapshot["merchants"]:
        r = m["risk"]
        r["binding_id"] = binding["binding_id"]
        r["evidence_status"] = "OBSERVED_NATIVE_EVIDENCE" if any(
            r.get(key) is not None for key in ("consumer_probability_max", "merchant_probability_max")
        ) or any((r.get(key) or 0) > 0 for key in ("consumer_coverage", "merchant_coverage")) else "UNKNOWN"
        r["review_flags"] = [key for key in ("review_50", "review_80") if r.get(key) is True]
        r["components"] = [
            {"id": key, "value": r.get(key), "unit": "fraction", "meaning": meaning}
            for key, meaning in (("consumer_probability_max", "native signal; unvalidated fraud probability"),
                                 ("merchant_probability_max", "native signal; unvalidated fraud probability"),
                                 ("consumer_coverage", "source consumer signal coverage"),
                                 ("merchant_coverage", "source merchant calendar coverage"))]
    chosen = [m for m in snapshot["merchants"] if m["decision"] == "selected"]
    evidence = aggregate_risk(chosen)
    snapshot["risk_interface"] = {**binding, "mode": "READ_ONLY_EVIDENCE",
        "units": {"native_signal": "fraction", "coverage": "fraction", "recency": "days"},
        "source_status": source_status, "semantic_profile": "native-evidence-v1" if risk_digest else None,
        "engine_consumption": "NOT_ATTESTED_BY_ENGINE",
        "consumers": {
            "diversification": {"binding_id": binding["binding_id"], "status": source_status, "engine_consumption": "NOT_ATTESTED_BY_ENGINE",
                "by_category": grouped_risk(chosen, "category"), "by_group": grouped_risk(chosen, "group")},
            "portfolio": {"binding_id": binding["binding_id"], "status": source_status, "engine_consumption": "NOT_ATTESTED_BY_ENGINE",
                "risk_constraints": "NOT_ATTESTED_BY_ENGINE", "summary": evidence}},
        "selected_summary": evidence,
        "limitation": "Native signals and evidence concentration do not establish expected loss or risk reduction."}
    return snapshot


def aggregate_risk(rows):
    observed = [m for m in rows if m["risk"]["evidence_status"] == "OBSERVED_NATIVE_EVIDENCE"]
    revenue = sum(m["prediction"] or 0 for m in rows)
    covered_revenue = sum(m["prediction"] or 0 for m in observed)
    return {"merchants": len(rows), "observed": len(observed), "unknown": len(rows) - len(observed),
            "review_prompts": sum(bool(m["risk"]["review_flags"]) for m in rows),
            "review_unknown": sum(m["risk"].get("review_50") is None and m["risk"].get("review_80") is None for m in rows),
            "evidence_coverage": len(observed) / len(rows) if rows else None,
            "estimated_revenue_aud": revenue,
            "revenue_with_evidence_share": covered_revenue / revenue if revenue > 0 else None}


def grouped_risk(rows, dimension):
    groups = {}
    for m in rows:
        groups.setdefault(m.get(dimension) or "Unknown", []).append(m)
    return [{"label": label, **aggregate_risk(group)} for label, group in
            sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))]
