"""Local run ownership and provenance; committed reports are reference evidence."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib.metadata
import json
import re
import subprocess


def validate_run_id(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        raise ValueError('Run ID must be a single alphanumeric path component')
    return value


def file_hash(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def inventory(root: Path, paths) -> list[dict]:
    return [{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size,
             'sha256': file_hash(p)} for p in sorted(paths)]


def claim_run(directory: Path) -> None:
    """Atomically reserve a run. Completed AND interrupted runs cannot be overwritten."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir()
    except FileExistsError:
        raise FileExistsError(f'Run directory already exists: {directory}; choose a new run ID') from None
    (directory / '_RUNNING').write_text(datetime.now(timezone.utc).isoformat(), encoding='utf-8')


def finish_run(directory: Path) -> None:
    (directory / '_SUCCESS').write_text('', encoding='utf-8')
    (directory / '_RUNNING').unlink()


def provenance(root: Path, config: dict) -> dict:
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    code = [p for folder in ('src', 'scripts') for p in (root / folder).rglob('*.py')]
    return {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'git_commit': commit,
        'config_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        'code_files': inventory(root, code),
        'runtime_versions': {name: importlib.metadata.version(name)
                             for name in ('pandas', 'numpy', 'pyarrow')},
    }


def etl_manifest_path(root: Path, run_id: str) -> Path:
    """Prefer the actual local run manifest; legacy accepted runs remain readable."""
    validate_run_id(run_id)
    actual = root / 'reports/etl/runs' / f'{run_id}_manifest.json'
    return actual if actual.exists() else root / 'reports/etl' / f'{run_id}_manifest.json'


def snapshot_manifest_path(root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    actual = root / 'tables/modeling' / run_id / 'manifest.json'
    if actual.exists():
        return actual
    # Read-only reference for report notebooks / historical v2 runs.
    versioned = root / 'reports/time_split' / run_id / 'manifest.json'
    return versioned if versioned.exists() else root / 'reports/time_split/manifest.json'


def verify_baseline_freeze(root: Path, run_id: str) -> None:
    """Detect modified frozen artifacts or development inputs before evaluation."""
    validate_run_id(run_id)
    directory = root / 'artifacts' / run_id
    if not (directory / '_SUCCESS').exists():
        raise ValueError('Baseline run is not complete')
    frozen = json.loads((directory / 'freeze.json').read_text(encoding='utf-8'))
    contract = json.loads((directory / 'model_contract.json').read_text(encoding='utf-8'))
    for entry in frozen['output_files'] + contract['input_files']:
        path = root / entry['path']
        if path.stat().st_size != entry['bytes'] or file_hash(path) != entry['sha256']:
            raise ValueError(f'Frozen file changed: {entry["path"]}')
    if 'snapshot_run_id' in contract:
        manifest = snapshot_manifest_path(root, contract['snapshot_run_id'])
        if file_hash(manifest) != contract['snapshot_manifest_sha256']:
            raise ValueError('Frozen snapshot manifest changed')
