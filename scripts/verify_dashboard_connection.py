"""Read saved snapshots without importing or executing engine code."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.adapter import EngineAdapter
from dashboard.bundle_adapter import SourceRegistry
from dashboard.workflow import workflow


def inventory(root):
    files = list((root / "engines").rglob("*.py")) + list((root / "engines").rglob("*.ipynb")) + list((root / "artifacts").rglob("*"))
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files if p.is_file() and "__pycache__" not in p.parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    root = args.engine_root.resolve()
    before = inventory(root)
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    adapter = SourceRegistry(root, config)
    catalog = adapter.catalog()
    if not catalog["runs"]:
        raise AssertionError("No saved runs available")
    checks = 0
    for run in catalog["runs"]:
        for split in run["splits"]:
            if split.get("error"):
                raise AssertionError(split["error"])
            for cutoff in split["cutoffs"]:
                for scenario in split["scenarios"]:
                    data = adapter.snapshot(run["id"], split["id"], cutoff, scenario)
                    selected = [m for m in data["merchants"] if m["decision"] == "selected"]
                    assert len(selected) == data["summary"]["selected"]
                    assert abs(sum(m["prediction"] for m in selected) - data["summary"]["predicted_revenue"]) < .00001
                    assert all(m["eligible"] for m in selected)
                    assert len(data["engines"]) == 7
                    assert data["integrity"] == "VERIFIED_PARQUET_HASHES"
                    risk = data["risk_interface"]
                    assert risk["consumers"]["diversification"]["binding_id"] == risk["consumers"]["portfolio"]["binding_id"] == risk["binding_id"]
                    assert risk["selected_summary"]["observed"] + risk["selected_summary"]["unknown"] == len(selected)
                    if split["id"] == "latest":
                        assert data["metrics"] is None
                    json.dumps(data, allow_nan=False)
                    checks += 1
                comparison = workflow(adapter, run["id"], split["id"], cutoff)
                assert len({s["risk_binding_id"] for s in comparison["scenarios"]}) == 1
                assert comparison["mode"] == "SAVED_OUTPUT_REPLAY"
            print(f"PASS {run['id']} / {split['id']}: {len(split['cutoffs'])} cutoffs × {len(split['scenarios'])} scenarios", flush=True)
    assert before == inventory(root), "Source engine files changed during verification"
    print(json.dumps({"snapshots_passed": checks, "shared_risk_and_scenario_comparisons_passed": True, "engine_source_and_artifacts_unchanged": True, "source_files_checked": len(before)}), flush=True)


if __name__ == "__main__":
    main()
