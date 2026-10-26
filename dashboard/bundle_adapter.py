"""Register separate engine output locations without copying or changing engines.

The dashboard-owned manifest binds hashes, versions and one snapshot lineage.
Column mappings expose only the existing allowlisted DTO. Unknown semantics must
be implemented as a new adapter rather than guessed from similarly named fields.
"""
from pathlib import Path
import hashlib
import json
import re

from .adapter import EngineAdapter, ContractError, FIELDS, REQUIRED, SPLITS, safe_token


class BundleAdapter(EngineAdapter):
    def __init__(self, root, manifest):
        super().__init__(root)
        if manifest.get("schema_version") != "engine-bundle-v1":
            raise ContractError("Unsupported engine bundle version")
        self.bundle = manifest
        safe_token(manifest["run"])
        if not manifest.get("snapshot_id") or not manifest.get("source_commit"):
            raise ContractError("Bundle requires snapshot_id and source_commit lineage")
        self.windows = manifest.get("windows", {})
        if not self.windows or set(self.windows) - set(SPLITS):
            raise ContractError("Bundle has unsupported or missing windows")
        for split, window in self.windows.items():
            outputs = window.get("outputs", {})
            if set(REQUIRED) - set(outputs) or set(outputs) - set(FIELDS):
                raise ContractError("Bundle is missing required outputs or includes unknown output names")
            for name, output in outputs.items():
                if output.get("snapshot_id") != manifest["snapshot_id"]:
                    raise ContractError(f"{name}: snapshot lineage mismatch")
                if not output.get("engine_version") or not re.fullmatch(r"[0-9a-f]{64}", output.get("sha256", "")):
                    raise ContractError(f"{name}: version and SHA256 are required")
                self.resolve(output["path"])
            for field in ("cutoffs", "scenarios"):
                if not window.get(field) or len(set(window[field])) != len(window[field]):
                    raise ContractError(f"Bundle requires unique {field}")
            for scenario in window["scenarios"]:
                safe_token(scenario)

    def resolve(self, relative):
        if Path(relative).is_absolute():
            raise ContractError("Bundle output paths must be relative to the engine root")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ContractError("Bundle output path escapes the engine root")
        return path

    def run_path(self, run):
        if run != self.bundle["run"]:
            raise ContractError("Bundle run not found")
        return self.root / "__dashboard_bundle__" / safe_token(run)

    def window(self, folder):
        split = folder.name.removesuffix("_system")
        if split not in self.windows:
            raise ContractError("Bundle window unavailable")
        return self.windows[split]

    def table_path(self, folder, name):
        output = self.window(folder)["outputs"].get(name)
        return self.resolve(output["path"]) if output else self.root / "__missing_output__" / f"{name}.parquet"

    def column_mapping(self, folder, name):
        return self.window(folder)["outputs"].get(name, {}).get("columns", {})

    def has_table(self, folder, name):
        # A declared missing output is an error, never silently downgraded.
        return name in self.window(folder)["outputs"]

    def table(self, folder, name, hashes=None):
        output = self.window(folder)["outputs"].get(name)
        if output is None:
            raise ContractError(f"Missing {name}.parquet; not registered in bundle")
        frame, digest = super().table(folder, name, {f"{name}.parquet": output["sha256"]})
        if "engine_version" in frame and not frame.engine_version.dropna().astype(str).eq(output["engine_version"]).all():
            raise ContractError(f"{name}: engine version disagrees with bundle")
        frame["engine_version"] = output["engine_version"]
        return frame, digest

    def json_file(self, path, default=None):
        if path.name == "training.json":
            return {"champion": self.bundle.get("revenue_model", "Registered revenue output")}
        if path.name == "calibration.json":
            champion = self.bundle.get("revenue_model", "Registered revenue output")
            return {champion: {"calibration_status": self.bundle.get("confidence_acceptance", "UNKNOWN")}}
        if path.name == "prediction_lock.json":
            return {"files": {f"{name}.parquet": output["sha256"] for name, output in self.window(path.parent)["outputs"].items()}}
        if path.name == "solver_audit.json":
            return self.window(path.parent).get("solver_audit", [])
        if path.name == "evaluation.json":
            # Inline evaluation is deliberately excluded until its own source
            # lineage and lock hash are supported by a new contract version.
            return {}
        return default

    def catalog(self):
        return {"api_version": "1.0", "adapter": "engine-bundle-v1", "source": "local_engine_outputs",
            "source_label": self.root.name, "runs": [{"id": self.bundle["run"], "status": "REGISTERED",
                "splits": [{"id": split, "cutoffs": sorted(w["cutoffs"]), "scenarios": w["scenarios"]}
                           for split, w in self.windows.items()]}]}

    def snapshot(self, run, split, cutoff, scenario):
        window = self.windows.get(split, {})
        if cutoff not in window.get("cutoffs", []) or scenario not in window.get("scenarios", []):
            raise ContractError("Bundle cutoff or scenario unavailable")
        result = super().snapshot(run, split, cutoff, scenario)
        result["adapter"] = "engine-bundle-v1"
        result["lineage"] = {**{k: self.bundle[k] for k in ("snapshot_id", "source_commit")},
                             "binding_authority": "DASHBOARD_MANIFEST", "producer_lineage": "NOT_ATTESTED"}
        result["source_fingerprint"] = hashlib.sha256(json.dumps({"bundle": self.bundle,
            "source_fingerprint": result["source_fingerprint"]},sort_keys=True).encode()).hexdigest()[:16]
        result["warnings"].append("Registered bundle evaluation is unavailable in engine-bundle-v1; no outcome metrics are inferred.")
        result["warnings"].append("Bundle snapshot/commit identity is declared by the dashboard manifest; producer execution lineage is not independently attested.")
        return result


class SourceRegistry:
    def __init__(self, root, config=None):
        self.root = Path(root).resolve()
        self.legacy = EngineAdapter(root, config)
        self.adapters = {}
        for manifest in (config or {}).get("bundles", []):
            adapter = BundleAdapter(root, manifest)
            if manifest["run"] in self.adapters:
                raise ContractError("Duplicate registered bundle run")
            self.adapters[manifest["run"]] = adapter

    def catalog(self):
        catalog = self.legacy.catalog()
        ids = {r["id"] for r in catalog["runs"]}
        if ids.intersection(self.adapters):
            raise ContractError("Bundle and legacy run identifiers collide")
        for adapter in self.adapters.values():
            catalog["runs"].extend(adapter.catalog()["runs"])
        catalog["registered_adapters"] = ["seven-engine-files-v1", "engine-bundle-v1"]
        return catalog

    def snapshot(self, run, split, cutoff, scenario):
        return self.adapters.get(run, self.legacy).snapshot(run, split, cutoff, scenario)
