"""Create notebook reports from reproducible analysis functions; no raw record displays."""
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]


def notebook(title: str, body: list) -> nbf.NotebookNode:
    result = nbf.v4.new_notebook()
    result.metadata["kernelspec"] = {"display_name": "BNPL ADS project 2", "language": "python", "name": "bnpl-ads2"}
    result.cells = [nbf.v4.new_markdown_cell(title), *body]
    return result


setup = nbf.v4.new_code_cell("""from pathlib import Path
import json
import sys
import pandas as pd
from IPython.display import display, Image, Markdown

root = next(path for path in [Path.cwd(), *Path.cwd().parents] if (path / 'config/analysis_v1.json').exists())
sys.path.insert(0, str(root))
from src.bnpl_analysis.common import load_config
from src.run_artifacts import snapshot_manifest_path
config = load_config(root)
pd.set_option('display.max_columns', 12)
""")

eda = notebook("""# BNPL cleaned-data EDA

This report uses the completed cleaning v1.2 outputs. Exploration covers train and internal
validation from 2021-02-28 through 2022-02-27. Protected test outcome distributions are excluded.
Only aggregate statistics and charts are printed; no individual customer or merchant rows appear.
""", [setup,
    nbf.v4.new_code_cell("""from src.bnpl_analysis.eda import run_eda
eda_dir = root / 'reports/eda' / config['analysis_run_id']
summary_path = eda_dir / 'summary.json'
if not summary_path.exists():
    run_eda(root)
summary = json.loads(summary_path.read_text(encoding='utf-8'))
metrics = {k: v for k, v in summary.items() if not isinstance(v, dict)}
display(pd.DataFrame(metrics.items(), columns=['Metric', 'Value']))
"""),
    nbf.v4.new_markdown_cell("## Amount distribution and monthly activity\nPartial February periods should not be compared as complete months."),
    nbf.v4.new_code_cell("""display(pd.DataFrame(summary['amount_quantiles_aud'].items(), columns=['Quantile', 'Amount AUD']))
display(pd.read_json(eda_dir / 'monthly_aggregates.json'))
"""),
    nbf.v4.new_markdown_cell("## Historical charts\nFraud coverage is the proportion matched to a signal, not a realised fraud rate."),
    nbf.v4.new_code_cell("""for path in sorted((eda_dir / 'figures').glob('*.png')):
    display(Image(filename=str(path)))
"""),
    nbf.v4.new_markdown_cell("""## Modelling implications

- Compare top-K value and simple scale baselines before a complex model.
- Preserve absent fraud observations and their coverage flags.
- Keep customer geography contextual; it is not merchant location.
- Recompute time-window features; the contributor's all-period merchant aggregate is not a predictor table.
- Fit all feature selection and preprocessing only on the training partition.
- See the configured run directories under `reports/eda/` and `reports/time_split/`.
""")])

split = notebook("""# BNPL rolling merchant snapshots

## tl;dr

The supervised unit is one eligible merchant at one decision cutoff. Six training and three
internal-validation target windows end before 2022-02-28; every later outcome is protected for one
primary out-of-time test and seven frozen-model robustness checks. No label values or merchant-level
rows are printed here.

## Context & Methods

Features use 90 calendar days ending at the cutoff and predict next-28-day take-rate revenue.
Target windows advance by 28 days and do not overlap. A 90-day target is deferred because the
available pre-protection history cannot support an adequate independent train/validation split.

### Key Assumptions

Static merchant attributes and fraud event dates are treated as available at the cutoff; their
historical publication/effective dates are not supplied. External context remains excluded.
""", [setup,
    nbf.v4.new_markdown_cell("## Data\nOnly aggregate split counts and dates are displayed."),
    nbf.v4.new_code_cell("""from src.bnpl_analysis.time_split import build_time_splits
manifest_path = snapshot_manifest_path(root, config['snapshot_run_id'])
if not manifest_path.exists() or json.loads(manifest_path.read_text(encoding='utf-8')).get('protocol_version') != 'rolling_snapshot_v3':
    build_time_splits(root)
    manifest_path = snapshot_manifest_path(root, config['snapshot_run_id'])
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
display(pd.DataFrame(manifest['splits']))
"""),
    nbf.v4.new_markdown_cell("## Results\nThe schedule proves feature/label separation without revealing outcome values."),
    nbf.v4.new_code_cell("""from src.bnpl_analysis.time_split import snapshot_schedule
schedule = snapshot_schedule('2021-02-28', manifest['source_end'], manifest['config'])
display(schedule)
train = schedule[schedule['split'].eq('train')]
validation = schedule[schedule['split'].eq('validation')]
test = schedule[schedule['split'].eq('test')]
assert train['label_end'].max() < validation['label_start'].min()
assert validation['label_end'].max() < test['label_start'].min()
assert test['label_start'].min() == pd.Timestamp(manifest['protected_outcome_start'])
assert test.query("evaluation_role == 'primary_test'")['cutoff'].item() == pd.Timestamp('2022-02-27')
assert (schedule['history_end'] < schedule['label_start']).all()
assert manifest['eligible_history_enforced_in_model_files']
assert manifest['native_fraud_grain_features']
print('PASS: protected-period, eligibility and native-fraud controls')
print('Predictor count:', len(manifest['predictor_columns']))
print('Model trained:', manifest['model_trained'])
print('Holdout outcomes reported:', manifest['holdout_outcomes_reported'])
"""),
    nbf.v4.new_markdown_cell("""## Takeaways

Train preprocessing and Boruta inside the training partition; use chronological inner folds for
tuning. Use validation to select the model, freeze the complete pipeline, then evaluate the primary
test once and report later cutoffs as robustness. Repeated merchants mean the experiment measures
future ranking of known merchants, not cold-start generalisation.

Model files contain only historically active candidates; all 4,026 master merchants remain in local
coverage snapshots. Fraud summaries use native entity-day observations rather than repeated order
rows. A small number of independent ranking dates limits evidence for a large TCN.
""")])

baseline = notebook("""# BNPL validation-only baseline models

## tl;dr

This notebook displays an existing checkpoint comparing two trailing-revenue rules, Ridge, and histogram gradient boosting on three
validation cutoffs. Learned models have all-feature and no-fraud variants. Test features and labels
remain sealed, and no merchant-level rows are displayed. It never starts model training.
The user has requested a complete training plan before any further fitting or test scoring.

## Context & Methods

All preprocessing is fitted on train. Model settings and the selection rule are fixed in
`config/baseline_v1.json`. NDCG@100 is the primary metric and oracle revenue capture is the
tiebreaker.

### Key Assumptions

Fraud fields represent evidence coverage rather than realised fraud. Three validation dates provide
limited evidence, and a selected development model is not a test-performance claim.
""", [setup,
    nbf.v4.new_markdown_cell("## Data\nOnly development split counts and aggregate results are shown."),
    nbf.v4.new_code_cell("""from src.bnpl_analysis.baselines import load_baseline_config
baseline_config = load_baseline_config(root)
metrics_path = root / 'reports/baseline' / baseline_config['baseline_run_id'] / 'metrics.json'
if not metrics_path.exists():
    raise FileNotFoundError('Saved baseline evidence missing; review the training plan before scheduling a new fit')
result = json.loads(metrics_path.read_text(encoding='utf-8'))
display(pd.DataFrame({
    'split': ['train', 'validation', 'test'],
    'rows': [result['development_protocol']['train_rows'], result['development_protocol']['validation_rows'], 'SEALED'],
    'role': ['fit preprocessing and models', 'compare fixed candidates', 'not opened'],
}))
"""),
    nbf.v4.new_markdown_cell("## Results\nMetrics are macro-averaged over the three validation cutoffs."),
    nbf.v4.new_code_cell("""metrics = pd.DataFrame(result['aggregate_validation_metrics'])
display(metrics)
print('Selected on validation:', result['selection']['selected_model'])
assert result['development_protocol']['preprocessing_fit_split'] == 'train'
assert result['development_protocol']['test_features_opened'] is False
assert result['development_protocol']['test_labels_opened'] is False
assert result['development_protocol']['test_evaluated'] is False
print('PASS: train-only preprocessing and sealed-test controls')
"""),
    nbf.v4.new_markdown_cell("""## Takeaways

The winning candidate is frozen as `validation_selected_not_tested` in
the versioned baseline report's `model_contract.json`. This notebook presents saved evidence;
explicit CLI runs produce the immutable model artifacts. Independent review is the next gate. Boruta and TCN are
later experiments; they must use the same development boundary and outperform these baselines before
the primary test is opened once.
""")])

quality = notebook("""# BNPL feature quality v3

All 46 predictors have a formula, unit, missing-value rule and availability assumption. This
notebook reports development-only checks; it never opens test feature or label values.
""", [setup,
    nbf.v4.new_code_cell("""from src.bnpl_analysis.feature_qa import run_feature_qa
qa_dir = root / 'reports/feature_qa' / config['snapshot_run_id']
if not (qa_dir / 'summary.json').exists():
    run_feature_qa(root)
quality = json.loads((qa_dir / 'summary.json').read_text(encoding='utf-8'))
assert quality['status'] == 'PASS'
assert quality['test_feature_or_label_values_read'] is False
print('Predictors checked:', quality['predictor_count'])
print('Development rows:', quality['development_rows'])
display(pd.DataFrame(quality['coverage_by_cutoff']))
"""),
    nbf.v4.new_markdown_cell("## Missingness and stability\nCoverage is observed evidence, not a measured fraud rate. Do not drop correlated predictors automatically."),
    nbf.v4.new_code_cell("""drift = pd.DataFrame(quality['train_validation_drift'])
drift['absolute_change'] = drift['missingness_change_pp'].abs()
display(drift.sort_values('absolute_change', ascending=False).head(10))
print('Complete per-cutoff profiles:', len(quality['profiles']))
print('Near-constant feature/date combinations:', len(quality['near_constant_features']))
"""),
    nbf.v4.new_markdown_cell("## Interpretation\nConsumer latest now averages distinct users on the latest observed signal date. Sparse merchant fraud and changing consumer coverage warrant the no-fraud comparison. See the versioned feature catalogue for all formulas; final test performance is still unevaluated.")])

for name, value in [
    ("02_cleaned_data_eda.ipynb", eda),
    ("03_time_split.ipynb", split),
    ("04_baseline_models.ipynb", baseline),
    ("05_feature_quality.ipynb", quality),
]:
    destination = ROOT / 'notebooks' / name
    nbf.write(value, destination)
    print(f"Created {destination.name}")
