"""Synthetic contracts; no private engine records are embedded."""
import hashlib
import csv
import io
from http.server import ThreadingHTTPServer
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pandas as pd
import pytest
from dashboard.adapter import ContractError, EngineAdapter
from dashboard.server import handler_for, shortlist_csv
from dashboard.bundle_adapter import BundleAdapter, SourceRegistry
from dashboard.workflow import workflow

RUN, DATE = "fixture_v1", "2022-10-26"


@pytest.fixture
def source(tmp_path):
    run = tmp_path / "artifacts/seven_engines" / RUN
    folder = run / "latest_system"
    folder.mkdir(parents=True)
    keys = {"merchant_abn": ["DEMO-001", "DEMO-002"], "cutoff": [DATE, DATE]}
    tables = {
        "predictions": pd.DataFrame({**keys, "prediction": [100., 80.], "merchant_category": ["A", "B"], "course_group": ["Home", "Technology"], "merchant_name": ["Demo One", "=Demo Two"], "consumer_name": ["NEVER_EXPOSE"] * 2}),
        "revenue": pd.DataFrame({**keys, "prediction": [100., 80.]}),
        "eligibility": pd.DataFrame({**keys, "eligible": [True, True], "reason_codes": ["PASS", "PASS"]}),
        "candidate_dispositions": pd.DataFrame({**keys, "eligible": [True, True], "candidate_disposition": ["eligible_recent_history"] * 2}),
        "portfolios": pd.DataFrame({"merchant_abn": ["DEMO-001"], "cutoff": [DATE], "scenario": ["primary"], "global_rank": [1]}),
        "confidence": pd.DataFrame({**keys, "lower": [60., 40.], "upper": [140., 120.], "revenue_reliability": [.9, .6], "confidence_band": ["high", "medium"]}),
        "risk": pd.DataFrame({**keys, "risk_status": ["EVIDENCE_ONLY_NO_LOSS_LABELS"] * 2, "hist_consumer_probability_max": [None, .7], "review_prompt_50": pd.array([None, True], dtype="boolean")}),
        "group_top10": pd.DataFrame({**keys, "course_group": ["Home", "Technology"], "group_rank": [1, 1]}),
    }
    for name, table in tables.items():
        table.to_parquet(folder / f"{name}.parquet", index=False)
    (folder / "solver_audit.json").write_text(json.dumps([{"cutoff": DATE, "scenario": "primary", "status": "OPTIMAL", "count": 1, "revenue": 100., "gap": 0.}]))
    (run / "training.json").write_text(json.dumps({"champion": "fixture"}))
    (run / "calibration.json").write_text(json.dumps({"fixture": {"calibration_status": "INSUFFICIENT"}}))
    (folder / "evaluation.json").write_text(json.dumps({"portfolio_metrics": [{"cutoff": DATE, "scenario": "primary", "realised_revenue_aud": 999.}]}))
    return tmp_path, folder


def snapshot(root, scenario="primary", config=None):
    return EngineAdapter(root, config).snapshot(RUN, "latest", DATE, scenario)


def rewrite(folder, name, change):
    file = folder / f"{name}.parquet"
    change(pd.read_parquet(file)).to_parquet(file, index=False)


def lock(folder):
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.parquet")}
    (folder / "prediction_lock.json").write_text(json.dumps({"files": files}))


def test_normalisation_privacy_and_independent_groups(source):
    result = snapshot(source[0])
    assert result["summary"] == {"candidates": 2, "eligible": 2, "selected": 1, "predicted_revenue": 100.}
    assert len(result["engines"]) == 7
    assert result["metrics"] is None
    assert "NEVER_EXPOSE" not in json.dumps(result)
    assert result["merchants"][0]["risk"]["consumer_probability_max"] is None
    assert result["merchants"][0]["risk"]["review_50"] is None
    assert result["merchants"][1]["risk"]["review_50"] is True
    assert result["merchants"][1]["rank"] is None
    assert result["merchants"][1]["group_rank"] == 1
    assert result["export_allowed"] is True
    json.dumps(result, allow_nan=False)


def test_catalog_and_invalid_source(source):
    root, _ = source
    assert EngineAdapter(root).catalog()["runs"][0]["splits"][0]["cutoffs"] == [DATE]
    assert EngineAdapter(root / "missing").catalog()["runs"] == []
    with pytest.raises(ContractError):
        EngineAdapter(root, {"artifact_directory": "../outside"})


def test_shared_risk_binding_unknown_and_native_evidence(source):
    root, folder = source
    result = snapshot(root)
    interface = result["risk_interface"]
    assert interface["contract"] == "risk-evidence-v1"
    assert interface["consumers"]["portfolio"]["binding_id"] == interface["consumers"]["diversification"]["binding_id"] == interface["binding_id"]
    assert interface["selected_summary"]["observed"] == 0
    assert interface["selected_summary"]["unknown"] == 1
    assert result["merchants"][1]["risk"]["review_flags"] == ["review_50"]
    assert result["merchants"][1]["risk"]["evidence_status"] == "OBSERVED_NATIVE_EVIDENCE"
    assert all(m["risk"]["binding_id"] == interface["binding_id"] for m in result["merchants"])
    before = interface["binding_id"]
    rewrite(folder, "risk", lambda f: f.assign(hist_consumer_probability_max=[0., .7]))
    changed = snapshot(root)
    assert changed["risk_interface"]["selected_summary"]["observed"] == 1
    assert changed["risk_interface"]["binding_id"] != before
    assert changed["summary"] == result["summary"]  # Evidence does not reselect.


def test_missing_risk_remains_unknown_for_both_consumers(source):
    root, folder = source
    (folder / "risk.parquet").unlink()
    result = snapshot(root)
    assert result["risk_interface"]["source_sha256"] is None
    assert result["risk_interface"]["selected_summary"]["unknown"] == 1
    assert result["risk_interface"]["consumers"]["portfolio"]["risk_constraints"] == "NOT_ATTESTED_BY_ENGINE"
    assert result["risk_interface"]["source_status"] == "MISSING_SOURCE"
    assert all(c["status"] == "MISSING_SOURCE" for c in result["risk_interface"]["consumers"].values())


def test_risk_status_only_or_proxy_schema_is_rejected(source):
    root, folder = source
    rewrite(folder,"risk",lambda f: f.drop(columns=["hist_consumer_probability_max","review_prompt_50"]).assign(proxy_probability_mean=.4))
    with pytest.raises(ContractError,match="Unsupported Risk evidence schema"):
        snapshot(root)


def test_empty_risk_cutoff_is_not_marked_connected(source):
    root, folder=source
    rewrite(folder,"risk",lambda f:f.assign(cutoff="2022-09-11"))
    result=snapshot(root)
    assert result["risk_interface"]["source_status"] == "MISSING_AT_CUTOFF"
    assert all(c["status"] == "MISSING_AT_CUTOFF" for c in result["risk_interface"]["consumers"].values())


def test_historical_freeze_code_drift_is_disclosed_without_changing_results(source):
    root,folder=source
    code=root / "engines/portfolio.py"
    code.parent.mkdir()
    code.write_text("historical code\n")
    freeze={"frozen_utc":"2022-01-01T00:00:00Z","code":{"engines/portfolio.py":hashlib.sha256(code.read_bytes()).hexdigest()}}
    (folder.parent/'freeze.json').write_text(json.dumps(freeze))
    original=snapshot(root)
    assert original["execution"]["code_status"] == "CURRENT_CODE_MATCHES_FROZEN_RECORD"
    code.write_text("new code\n")
    changed=snapshot(root)
    assert changed["execution"]["code_status"] == "CURRENT_CODE_DIFFERS_FROM_FROZEN_RUN"
    assert changed["execution"]["changed_files"] == ["engines/portfolio.py"]
    assert changed["summary"] == original["summary"]
    assert any("historical code" in w for w in changed["warnings"])


def test_workflow_reconciles_swaps_revenue_concentration_and_risk(source):
    root, folder = source
    rewrite(folder, "portfolios", lambda f: pd.concat([f, pd.DataFrame({"merchant_abn":["DEMO-002"],"cutoff":[DATE],"scenario":["alternate"],"global_rank":[1]})]))
    audit = [{"cutoff": DATE,"scenario": key,"status":"OPTIMAL","count":1,"revenue":value} for key,value in (("primary",100.),("alternate",80.))]
    (folder / "solver_audit.json").write_text(json.dumps(audit))
    result = workflow(EngineAdapter(root), RUN, "latest", DATE)
    alt = next(s for s in result["scenarios"] if s["id"] == "alternate")
    assert (alt["added"], alt["removed"], alt["revenue_delta_aud"]) == (1,1,-20.)
    assert alt["risk"]["observed"] == alt["risk"]["review_prompts"] == 1
    assert alt["category_hhi_count"] == alt["category_hhi_revenue"] == 1.
    assert len({s["risk_binding_id"] for s in result["scenarios"]}) == 1
    assert all(s["metrics"] is None for s in result["scenarios"])


def test_workflow_rejects_drift_and_invalid_request(source):
    root, folder = source
    adapter = EngineAdapter(root)
    with pytest.raises(ContractError):
        workflow(adapter,RUN,"latest","2020-01-01")
    rewrite(folder, "portfolios", lambda f: pd.concat([f, f.assign(scenario="alternate")]))
    original = adapter.snapshot
    def changing(*args):
        result = original(*args)
        result["source_fingerprint"] = args[-1]
        return result
    adapter.snapshot = changing
    with pytest.raises(ContractError, match="changed during"):
        workflow(adapter,RUN,"latest",DATE)


def make_bundle(source):
    root, folder = source
    keys = {"merchant_abn":["DEMO-001","DEMO-002"],"cutoff":[DATE,DATE]}
    for name, values in (("diversification",{"marginal_category_hhi":[.01,.02]}),
                         ("strategic_fit",{"strategic_status":["NOT_CONFIGURED"]*2}),
                         ("portfolio",{})):
        pd.DataFrame({**keys,**values}).to_parquet(folder / f"{name}.parquet",index=False)
    outputs = {}
    for file in folder.glob("*.parquet"):
        outputs[file.stem] = {"path":str(file.relative_to(root)),"sha256":hashlib.sha256(file.read_bytes()).hexdigest(),"engine_version":"fixture_v1","snapshot_id":"fixture_snapshot"}
    return {"schema_version":"engine-bundle-v1","run":"separate_files_v1","snapshot_id":"fixture_snapshot","source_commit":"fixture_commit","windows":{"latest":{"outputs":outputs,"cutoffs":[DATE],"scenarios":["primary"],"solver_audit":json.loads((folder / "solver_audit.json").read_text())}}}


def test_separate_files_bundle_all_engines_with_column_mapping(source):
    root, folder = source
    manifest = make_bundle(source)
    rewrite(folder,"risk", lambda f: f.rename(columns={"risk_status":"native_risk_status"}))
    descriptor = manifest["windows"]["latest"]["outputs"]["risk"]
    descriptor["columns"] = {"risk_status":"native_risk_status"}
    descriptor["sha256"] = hashlib.sha256((folder / "risk.parquet").read_bytes()).hexdigest()
    registry = SourceRegistry(root,{"bundles":[manifest]})
    assert len(registry.catalog()["runs"]) == 2
    result = registry.snapshot(manifest["run"],"latest",DATE,"primary")
    assert result["adapter"] == "engine-bundle-v1"
    assert result["lineage"]["snapshot_id"] == "fixture_snapshot"
    assert all(e["rows"] and e["versions"] == ["fixture_v1"] for e in result["engines"])
    assert result["summary"]["predicted_revenue"] == 100.
    assert result["risk_interface"]["selected_summary"]["unknown"] == 1
    assert workflow(registry,manifest["run"],"latest",DATE)["scenarios"][0]["risk"]["unknown"] == 1


@pytest.mark.parametrize("mutation,message", [
    (lambda m: m["windows"]["latest"]["outputs"]["risk"].update(snapshot_id="different"),"lineage mismatch"),
    (lambda m: m["windows"]["latest"]["outputs"]["risk"].update(path="../outside.parquet"),"escapes"),
    (lambda m: m["windows"]["latest"]["outputs"]["risk"].update(sha256="invalid"),"SHA256"),
    (lambda m: m.update(schema_version="future-v2"),"Unsupported"),
])
def test_bundle_rejects_incompatible_lineage_paths_and_schema(source,mutation,message):
    manifest = make_bundle(source)
    mutation(manifest)
    with pytest.raises(ContractError,match=message):
        BundleAdapter(source[0],manifest)


def test_bundle_declared_missing_or_modified_output_fails(source):
    root, folder = source
    manifest = make_bundle(source)
    adapter = BundleAdapter(root,manifest)
    rewrite(folder,"risk", lambda f: f.assign(risk_status="CHANGED"))
    with pytest.raises(ContractError,match="hash mismatch"):
        adapter.snapshot(manifest["run"],"latest",DATE,"primary")
    (folder / "risk.parquet").unlink()
    with pytest.raises(ContractError,match="Missing risk"):
        adapter.snapshot(manifest["run"],"latest",DATE,"primary")


@pytest.mark.parametrize("run,split,date,scenario", [("../outside", "latest", DATE, "primary"), (RUN, "../../", DATE, "primary"), (RUN, "latest", "bad", "primary"), (RUN, "latest", DATE, "../")])
def test_invalid_request(source, run, split, date, scenario):
    with pytest.raises(ContractError):
        EngineAdapter(source[0]).snapshot(run, split, date, scenario)


def test_missing_optional_is_unknown_not_stale_prediction(source):
    root, folder = source
    rewrite(folder, "predictions", lambda f: f.assign(lower=1., revenue_reliability=1.))
    (folder / "confidence.parquet").unlink()
    result = snapshot(root)
    assert result["merchants"][0]["confidence"]["lower"] is None
    assert result["merchants"][0]["confidence"]["reliability"] is None
    assert any("confidence.parquet" in warning for warning in result["warnings"])


def test_required_missing_and_schema_drift(source):
    root, folder = source
    rewrite(folder, "revenue", lambda f: f.rename(columns={"prediction": "new_value"}))
    with pytest.raises(ContractError, match="required fields missing"):
        snapshot(root)
    config = {"columns": {"revenue": {"prediction": "new_value"}}}
    assert snapshot(root, config=config)["summary"]["predicted_revenue"] == 100.
    (folder / "eligibility.parquet").unlink()
    with pytest.raises(ContractError, match="Missing eligibility"):
        snapshot(root, config=config)


def test_hash_verification_and_cache_invalidation(source):
    root, folder = source
    lock(folder)
    assert snapshot(root)["integrity"] == "VERIFIED_PARQUET_HASHES"
    rewrite(folder, "revenue", lambda f: f.assign(prediction=[100., 81.]))
    with pytest.raises(ContractError, match="hash mismatch"):
        snapshot(root)


@pytest.mark.parametrize("table,change,message", [
    ("predictions", lambda f: pd.concat([f, f.iloc[:1]], ignore_index=True), "duplicate"),
    ("predictions", lambda f: f.assign(prediction=[100., float("nan")]), "invalid prediction"),
    ("revenue", lambda f: f.assign(prediction=[100., 81.]), "amounts disagree"),
    ("eligibility", lambda f: f.assign(eligible=[False, True]), "ineligible"),
    ("portfolios", lambda f: f.assign(global_rank=[2]), "ranks"),
    ("portfolios", lambda f: f.assign(merchant_abn=["DEMO-NOT-PRESENT"]), "absent"),
    ("candidate_dispositions", lambda f: f.assign(eligible=[True, False]), "universes differ"),
    ("confidence", lambda f: f.assign(lower=[150., 40.]), "lower bound"),
    ("risk", lambda f: f.assign(hist_consumer_probability_max=[None, 70.]), "fraction"),
    ("risk", lambda f: f.assign(review_prompt_50=["unknown", "true"]), "nullable boolean"),
    ("group_top10", lambda f: f.assign(course_group=["Wrong", "Technology"]), "membership"),
    ("group_top10", lambda f: f.assign(group_rank=[2, 1]), "contiguous"),
])
def test_invalid_engine_outputs(source, table, change, message):
    root, folder = source
    rewrite(folder, table, change)
    with pytest.raises(ContractError, match=message):
        snapshot(root)


def test_solver_mismatch_and_nonoptimal_export(source):
    root, folder = source
    audit = [{"cutoff": DATE, "scenario": "primary", "status": "OPTIMAL", "count": 1, "revenue": 99.}]
    (folder / "solver_audit.json").write_text(json.dumps(audit))
    with pytest.raises(ContractError, match="reconcile"):
        snapshot(root)
    audit[0].update(revenue=100., status="NOT_PROVEN_OPTIMAL")
    (folder / "solver_audit.json").write_text(json.dumps(audit))
    assert snapshot(root)["export_allowed"] is False


def test_conservative_objective(source):
    root, folder = source
    rewrite(folder, "portfolios", lambda f: f.assign(scenario="conservative"))
    (folder / "solver_audit.json").write_text(json.dumps([{"cutoff": DATE, "scenario": "conservative", "status": "OPTIMAL", "count": 1, "revenue": 60.}]))
    assert snapshot(root, "conservative")["summary"]["predicted_revenue"] == 100.
    (folder / "confidence.parquet").unlink()
    with pytest.raises(ContractError, match="requires confidence"):
        snapshot(root, "conservative")


def test_csv_reconciles_and_guards_formulas(source):
    data = snapshot(source[0])
    data["merchants"][0]["name"] = "=FORMULA()"
    rows = list(csv.DictReader(io.StringIO(shortlist_csv(data).decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["merchant_name"] == "'=FORMULA()"
    assert rows[0]["predicted_revenue_aud"] == "100.0"
    assert rows[0]["run"] == RUN
    data["export_allowed"] = False
    with pytest.raises(ContractError, match="optimality"):
        shortlist_csv(data)


def test_http_routes_and_source_unchanged(source):
    root, folder = source
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(EngineAdapter(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/catalog") as response:
            assert json.load(response)["api_version"] == "1.0"
        with urlopen(base + f"/api/snapshot?run={RUN}&split=latest&cutoff={DATE}&scenario=primary") as response:
            assert json.load(response)["summary"]["selected"] == 1
        with urlopen(base + f"/api/workflow?run={RUN}&split=latest&cutoff={DATE}") as response:
            comparison=json.load(response)
            assert comparison["risk_contract"] == "risk-evidence-v1"
            assert comparison["scenarios"][0]["risk"]["unknown"] == 1
        for asset in ("/product-views.js","/product.css"):
            with urlopen(base+asset) as response:
                assert response.status == 200
        with urlopen(base + f"/api/export?run={RUN}&split=latest&cutoff={DATE}&scenario=primary") as response:
            assert response.headers["Content-Disposition"].startswith("attachment;")
            assert len(list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))) == 1
        for route in ("/tables/raw/course/secret.zip", "/../README.md", "/adapter-config.json"):
            with pytest.raises(HTTPError) as exc:
                urlopen(base + route)
            assert exc.value.code == 404
        with pytest.raises(HTTPError) as exc:
            urlopen(base + "/api/snapshot")
        assert exc.value.code == 422
        with pytest.raises(HTTPError) as exc:
            urlopen(base + f"/api/workflow?run={RUN}&split=latest&cutoff={DATE}&scenario=primary")
        assert exc.value.code == 422
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(base + "/api/catalog", headers={"Host": "untrusted.example"}))
        assert exc.value.code == 403
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(base + "/api/catalog", data=b"{}", method="POST"))
        assert exc.value.code == 501
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
