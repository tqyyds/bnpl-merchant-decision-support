"""Targeted presentation repair: retain all data/sections and permit cell wrapping."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engines.contracts import save

p=argparse.ArgumentParser(); p.add_argument('--run-id',required=True); a=p.parse_args()
path=Path('deliverables')/a.run_id/'artifact.json'; artifact=json.loads(path.read_text())
for table in artifact['manifest']['tables']: table['density']='spacious'
save(artifact,path)
