"""Register an existing saved run as independently located, immutable outputs.

Writes only the dashboard configuration chosen by --output. Engine sources and
artifacts are read-only. This is also a working recipe for future output layouts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.adapter import EngineAdapter, FIELDS
from dashboard.bundle_adapter import SourceRegistry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root",type=Path,required=True)
    parser.add_argument("--run",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    root=args.engine_root.resolve()
    output=args.output.resolve()
    if output.is_relative_to(root):
        parser.error("Configuration output must be outside the read-only engine root")
    if output.exists():
        parser.error("Output already exists; choose a new file to preserve the existing configuration")
    adapter=EngineAdapter(root)
    run=next((r for r in adapter.catalog()["runs"] if r["id"]==args.run),None)
    if not run:
        parser.error("Saved run not found")
    commit=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()
    run_path=adapter.run_path(args.run)
    training=adapter.json_file(run_path / "training.json",{})
    champion=training.get("champion","Unknown")
    acceptance=adapter.json_file(run_path / "calibration.json",{}).get(champion,{}).get("calibration_status","UNKNOWN")
    manifest={"schema_version":"engine-bundle-v1","run":args.run+"_bundle","snapshot_id":args.run,
              "source_commit":commit,"revenue_model":champion,"confidence_acceptance":acceptance,"windows":{}}
    for split in run["splits"]:
        folder=run_path / (split["id"]+"_system")
        outputs={}
        for name in FIELDS:
            if adapter.has_table(folder,name):
                frame,digest=adapter.table(folder,name)
                versions=frame.engine_version.dropna().astype(str).unique() if "engine_version" in frame else []
                version=versions[0] if len(versions)==1 else None
                # Recommendation tables inherit the explicit saved run profile.
                if not version and name in ("predictions","candidate_dispositions","portfolios","group_top10"):
                    version="saved-run/"+args.run
                if not version:
                    parser.error(f"{name}: cannot register unknown or mixed engine versions")
                outputs[name]={"path":str(adapter.table_path(folder,name).relative_to(root)).replace("\\","/"),
                    "sha256":digest,"engine_version":version,"snapshot_id":args.run,"columns":{}}
        manifest["windows"][split["id"]]={"outputs":outputs,"cutoffs":split["cutoffs"],"scenarios":split["scenarios"],
            "solver_audit":adapter.json_file(folder / "solver_audit.json",[])}
    config={"adapter":"seven-engine-files-v1","bundles":[manifest]}
    registry=SourceRegistry(root,config)
    for split in run["splits"]:
        registry.snapshot(manifest["run"],split["id"],split["cutoffs"][0],split["scenarios"][0])
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"registered_run":manifest["run"],"windows":len(manifest["windows"]),"engine_sources_unchanged":True}))


if __name__=="__main__":
    main()
