"""Generate English field and segmentation documentation from executable contracts."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engines.contracts import FIELDS,SPECS,CATEGORIES,BINARY,CHANNELS,GROUPS,save

root=Path(__file__).resolve().parents[1]
lines=['# Revenue input contract v1','','One source row per merchant × cutoff. All `hist_` windows are 90 inclusive calendar days unless explicitly named. Metadata (ID, name, cutoff and boundaries) is never a predictor.','',
    '| # | Source field | Definition | Unit | Structural missing rule | Transform |','|---:|---|---|---|---|---|']
for i,k in enumerate(FIELDS,1):
    definition,unit,missing=SPECS[k]
    transform='C: train-only one-hot; ignore unseen categories' if k in CATEGORIES else 'B: unchanged 0/1' if k==BINARY else 'L: already log1p; do not re-log' if k.endswith('log1p') else 'N: original numeric definition'
    lines.append(f'| {i} | `{k}` | {definition} | {unit} | {missing} | {transform} |')
lines += ['', 'N and L fields: train-only median fill plus an indicator for every numeric field. All-missing training columns use fixed zero and warn. Ridge standardises N/L after filling; HGB does not scale. B and missing indicators remain 0/1. Invalid infinities, rates, negatives, non-structural nulls and date errors fail instead of being imputed. No-history merchants are audit-only.',
    '', 'Rate is percentage points: 2 means 2%, not 200%. `hist_daily_gmv_cv` uses population standard deviation over all 90 calendar days, including zero days. Order amount standard deviation uses ddof=1. P99 is computed only over the cutoff history and master universe; high-value means amount >= P99. `hist_growth_28d` is last28/previous28 - 1, null when denominator zero.',
    '', '## Six daily TCN channels', '', '| Channel | Definition and unit | Zero-order day | Transform |','|---|---|---|---|',
    '| daily_gmv | Daily GMV, AUD | 0 | log1p then train-only standardise |',
    '| daily_orders | Daily order count | 0 | log1p then train-only standardise |',
    '| daily_unique_customers | Daily distinct user count | 0 | log1p then train-only standardise |',
    '| daily_aov | Daily GMV / orders, AUD/order | 0; interpreted with active flag | log1p then train-only standardise |',
    '| daily_active | Daily orders > 0, binary | 0 | unchanged |',
    '| daily_revenue_proxy | Daily GMV × rate / 100, AUD | 0 | log1p then train-only standardise |',
    '', 'Sequence is cutoff-29 through cutoff, ascending date, exactly 30 steps. A missing source partition fails, never zero-fills a missing file. Static inputs: train-only category and revenue-level one-hot, take_rate_pct / 100, and train-only-standardised hist_revenue_proxy_log1p. Full source fields and encoded column names are saved separately in training.json.',
    '', '## Fixed course mapping', '', '| Course group | Exact normalised category |','|---|---|']
for group,categories in GROUPS.items():
    lines += [f'| {group} | {c} |' for c in categories]
lines += ['', 'Rationale: operating content (domestic goods/services; appearance/accessories; digital/communications; mobility/outdoor; creative/cultural/gifting/office), fixed before test. Mapping is not a validated ANZSIC crosswalk. See seven_engine_protocol.md for independent group ranking and the complete temporal/decision rules.']
(root/'docs/analysis/revenue_input_contract_v1.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
save({'source_fields':FIELDS,'sequence_channels':CHANNELS,'groups':GROUPS},root/'config/seven_engine_contract_v1.json')
