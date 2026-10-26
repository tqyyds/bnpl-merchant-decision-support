"""Execute saved-evidence report notebooks with the invoking Python environment."""
from pathlib import Path
import sys

import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    for name in ('02_cleaned_data_eda.ipynb','03_time_split.ipynb','04_baseline_models.ipynb','05_feature_quality.ipynb'):
        path = ROOT/'notebooks'/name
        notebook = nbformat.read(path,as_version=4)
        manager = KernelManager(kernel_name='python3')
        manager.kernel_spec.argv = [sys.executable,'-m','ipykernel_launcher','-f','{connection_file}']
        try:
            NotebookClient(notebook,km=manager,timeout=300,
                           resources={'metadata':{'path':str(ROOT)}}).execute()
        finally:
            if manager.has_kernel:
                manager.shutdown_kernel(now=True)
        nbformat.validate(notebook)
        nbformat.write(notebook,path)
        print(f'Executed {name}',flush=True)
