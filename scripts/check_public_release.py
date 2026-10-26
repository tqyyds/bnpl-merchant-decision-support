"""Check the public file inventory without reading ignored local datasets."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_SUFFIXES = {'.parquet', '.csv', '.tsv', '.zip', '.pkl', '.pickle', '.pt', '.pth', '.npy', '.npz', '.xlsx', '.pdf'}
BLOCKED_PREFIXES = ('tables/raw/', 'tables/staging/', 'tables/curated/', 'tables/modeling/', 'data/', 'artifacts/', 'deliverables/', 'dashboard/.local/')
PATTERNS = [
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{50,}\b'),
    re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
    re.compile(r'(?i)[A-Z]:[\\/]Users[\\/][^\s"\']+'),
]

def inventory():
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True)
    if result.returncode == 0 and result.stdout:
        return [ROOT / name for name in result.stdout.decode('utf-8').split('\0') if name]
    return [p for p in ROOT.rglob('*') if p.is_file() and not any(x in p.relative_to(ROOT).parts for x in ('.git', '__pycache__', '.pytest_cache', '.venv', 'node_modules'))]

def main():
    failures = []
    files = inventory()
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in BLOCKED_SUFFIXES or relative.startswith(BLOCKED_PREFIXES) or path.name.startswith('.env'):
            failures.append(f'{relative}: restricted path or format')
            continue
        if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.svg', '.webp'}:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            failures.append(f'{relative}: unexpected binary file')
            continue
        if any(pattern.search(text) for pattern in PATTERNS):
            failures.append(f'{relative}: potential secret or private absolute path')
        if path.suffix == '.ipynb':
            notebook = json.loads(text)
            if any(c.get('outputs') or c.get('execution_count') is not None or c.get('attachments') for c in notebook['cells']):
                failures.append(f'{relative}: notebook contains outputs or execution state')
    demo = json.loads((ROOT / 'dashboard/demo.json').read_text())
    if demo.get('source') != 'synthetic_demo' or demo.get('integrity') != 'SYNTHETIC_NOT_ENGINE_OUTPUT':
        failures.append('dashboard/demo.json: missing synthetic provenance')
    if failures:
        print('\n'.join(failures))
        return 1
    print(f'PASS: {len(files)} public files; notebook outputs removed; demo explicitly synthetic.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
