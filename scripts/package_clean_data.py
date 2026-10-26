"""Package clean data and explicit test partitions. No training or test scoring."""
from pathlib import Path
import json
import shutil
import sys
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.bnpl_analysis.common import load_config,save_json
from src.bnpl_analysis.time_split import snapshot_schedule
from src.run_artifacts import claim_run,finish_run,file_hash


def package(root: Path):
    config = load_config(root)
    name = 'bnpl_clean_features_v1_2_v3'
    output = root/'deliverables'/name
    archive_path = root/'deliverables'/f'{name}.zip'
    if archive_path.exists():
        raise FileExistsError('Delivery archive already exists')
    claim_run(output)
    staging = root/'tables/staging'/config['cleaning_run_id']
    snapshots = root/'tables/modeling'/config['snapshot_run_id']
    context = root/'tables/features/customer_context_v1'
    for directory in (staging,snapshots,context):
        if not (directory/'_SUCCESS').exists():
            raise ValueError(f'Incomplete input: {directory}')
    primary_dir = output/'test/primary'
    robustness_dir = output/'test/robustness'
    primary_dir.mkdir(parents=True)
    robustness_dir.mkdir(parents=True)
    # Only partition and export the supplied protected values; no distribution/performance analysis.
    for kind in ('features','labels'):
        table = pq.read_table(snapshots/f'test_{kind}.parquet')
        mask = pc.equal(table['cutoff'],pa.scalar(pd.Timestamp(config['anchor_reference']).to_pydatetime(),type=table['cutoff'].type))
        pq.write_table(table.filter(mask),primary_dir/f'test_{kind}.parquet',compression='snappy')
        pq.write_table(table.filter(pc.invert(mask)),robustness_dir/f'test_{kind}.parquet',compression='snappy')
    # Inspect keys/dates only when checking the exported protected tables.
    protected_counts = {}
    for role,directory in [('primary',primary_dir),('robustness',robustness_dir)]:
        x = pq.read_table(directory/'test_features.parquet',columns=['merchant_abn','cutoff']).to_pandas()
        y = pq.read_table(directory/'test_labels.parquet',columns=['merchant_abn','cutoff','label_start','label_end']).to_pandas()
        pd.testing.assert_frame_equal(x,y[['merchant_abn','cutoff']])
        assert not x.duplicated(['merchant_abn','cutoff']).any()
        assert y.label_start.gt(y.cutoff).all()
        protected_counts[role] = len(x)
    schedule = snapshot_schedule('2021-02-28','2022-10-26',config)
    definition = {
        'status':'defined_exported_not_evaluated','primary_test_cutoff':config['anchor_reference'],
        'history_days':90,'target_days':28,'target':'future_28d_GMV_times_take_rate_pct_divided_by_100',
        'primary_test_history_start':'2021-11-30','primary_test_history_end':'2022-02-27',
        'primary_test_label_start':'2022-02-28','primary_test_label_end':'2022-03-27',
        'protected_counts':protected_counts,'primary_predictors':46,
        'context_predictors_permitted':False,'latest_export_permitted_for_training':False,
        'eligibility':'master merchant with at least one order in the previous 90 days; future zero targets retained',
        'schedule':json.loads(schedule.to_json(orient='records',date_format='iso')),
        'test_is_logically_separate_not_encrypted':True,
        'training_authorisation':'awaiting user confirmation of the training plan',
    }
    save_json(definition,output/'test_definition.json')
    mappings = []
    for path in sorted(staging.rglob('*.parquet')):
        mappings.append((path,'clean/'+path.relative_to(staging).as_posix()))
    mappings.append((root/'tables/curated'/config['cleaning_run_id']/'merchant_features.parquet','clean/merchant_all_period_audit.parquet'))
    for split in ('train','validation'):
        for kind in ('features','labels'):
            mappings.append((snapshots/f'{split}_{kind}.parquet',f'modeling/{split}/{kind}.parquet'))
    for path in sorted((snapshots/'all_candidates').glob('*.parquet')):
        mappings.append((path,'modeling/all_candidate_coverage/'+path.name))
    for path in sorted(context.glob('context_*.parquet')):
        mappings.append((path,'features/descriptive_context/'+path.name))
    for filename in ('merchant_features_latest.csv','merchant_features_latest.parquet',
                     'unknown_merchants_latest.csv','unknown_merchants_latest.parquet'):
        mappings.append((context/filename,'features/latest/'+filename))
    for path in [*primary_dir.glob('*.parquet'),*robustness_dir.glob('*.parquet')]:
        mappings.append((path,path.relative_to(output).as_posix()))
    mappings.extend([
        (root/'reports/feature_qa'/config['snapshot_run_id']/'feature_contract.json','documentation/primary_feature_contract.json'),
        (root/'reports/feature_qa'/config['snapshot_run_id']/'feature_catalogue.md','documentation/primary_feature_catalogue.md'),
        (root/'docs/analysis/customer_context_contract.md','documentation/customer_context_contract.md'),
        (root/'docs/analysis/training_plan_zh.md','documentation/training_plan_zh.md'),
        (root/'reports/etl/v1_2_manifest.json','documentation/cleaning_reference_manifest.json'),
        (context/'manifest.json','documentation/context_manifest.json'),
        (output/'test_definition.json','test_definition.json'),
    ])
    files,schemas = [],{}
    for path,relative in mappings:
        entry = {'path':relative,'bytes':path.stat().st_size,'sha256':file_hash(path)}
        if path.suffix == '.parquet':
            parquet = pq.ParquetFile(path)
            entry['rows'] = parquet.metadata.num_rows
            key = 'clean/transactions' if relative.startswith('clean/transactions/') else relative
            schemas.setdefault(key,[{'column':field.name,'type':str(field.type)} for field in parquet.schema_arrow])
        files.append(entry)
    save_json({'dataset':name,'files':files,'test_evaluated':False,'models_included':False},output/'dataset_manifest.json')
    save_json(schemas,output/'schema_dictionary.json')
    readme = '''# BNPL cleaned dataset + feature engineering

本包包含 14,195,505 笔清洗订单（606 天）、499,999 个最小化消费者记录、4,026 个商户主表记录，
以及包含 396 个主表缺失商户的全周期审计表。消费者姓名、地址和 gender 已移除；关联 ID 保留。

## 从哪里开始

- `features/latest/merchant_features_latest.csv`：2022-10-26 截止的 4,026 家主表商户特征，CSV 可直接查看。
- `features/latest/unknown_merchants_latest.csv`：396 家主表缺失商户，明确标记 unresolved。
- `clean/`：Parquet 格式的完整清洗数据；交易按日期分区。
- `modeling/train/` 与 `modeling/validation/`：46 个 primary predictors 与独立标签。
- `test/primary/`：cutoff 2022-02-27 的一次主测试；`test/robustness/` 为之后七个冻结模型检查窗口。
- `features/descriptive_context/`：客户居住地与区域人口/收入/SEIFA 背景，不能当作商户经营地址或个人收入。
- `modeling/all_candidate_coverage/`：包括没有近期交易的全部主表商户。按 merchant_abn + cutoff 连接 context 状态。

## 使用边界

只有 `documentation/primary_feature_contract.json` 中明确列出的 46 个字段是当前拟议模型输入。
最新日期导出、全周期审计表和 `ctx_` 区域背景字段不得送入历史预测训练。
`no_observed_history` 不等于商户刚成立；`inactive_recent_window` 表示过去曾出现但近 90 天无订单。
概率缺失不等于零风险。未定义主观综合风险/置信度分数，保留原始证据和覆盖率。

test 标签仅由脚本按既定 cutoff 分离导出，未进行模型评估。test 目录是逻辑隔离，不是加密保护。
`test_definition.json` 和 `documentation/training_plan_zh.md` 定义完整计划；等待用户确认后才继续训练。
未包含模型权重、原始 ZIP、消费者直接个人字段或合成 dashboard 数据。

每个文件的行数、大小和 SHA-256 在 dataset_manifest.json；字段类型在 schema_dictionary.json。
读取交易时建议使用 pyarrow.parquet.ParquetFile(path).read().to_pandas()，避免把目录分区日期与
文件内日期重复推断为不兼容类型。不要把 606 个分区一次性载入 Excel。
'''
    (output/'README.md').write_text(readme,encoding='utf-8')
    mappings.extend((output/name,name) for name in ('README.md','dataset_manifest.json','schema_dictionary.json'))
    with zipfile.ZipFile(archive_path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
        for path,relative in mappings:
            archive.write(path,relative)
    with zipfile.ZipFile(archive_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f'Archive CRC failure: {bad}')
    summary = {'archive':archive_path.relative_to(root).as_posix(),'bytes':archive_path.stat().st_size,
               'sha256':file_hash(archive_path),'entries':len(mappings),'crc_verified':True,
               'primary_test_rows':protected_counts['primary'],'robustness_rows':protected_counts['robustness']}
    save_json(summary,root/'reports/dataset_delivery.json')
    finish_run(output)
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    package(ROOT)
