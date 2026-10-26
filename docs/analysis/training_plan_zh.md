# BNPL test dataset 定义与完整训练计划（待确认）

> Historical plan — superseded by the user-approved [seven-engine protocol](seven_engine_protocol.md).
> Its pause instruction and train-plus-validation refit discussion are no longer the active protocol.

**本轮交付清洗数据、特征及 test 定义；下面是实施计划，不是执行训练的授权。收到用户确认后才继续训练、调参或最终测试。**

收到这项暂停训练要求前，上一阶段已重跑 validation-only baseline v2；其结果保留作历史开发证据。
本计划和后续数据交付不新增训练。最终 test 没有被评分；导出脚本只按既定截止日分离文件并检查键/日期。

## 1. 决策目标和预测标签

- 决策单位：商户在某个 cutoff 的状态；学习单位为 `(merchant_abn, cutoff)`。
- 预测目标：接下来 28 个日历日的 `GMV × take_rate_pct / 100`，单位 AUD。
- 标签名：`target_revenue`。它是 take-rate 收入代理，不是利润、扣除诈骗的净收益或真实信用损失。
- 容量约束：最多选择 100 家商户。短期预测排名为年度 onboarding 名单提供证据，不能宣称已验证全年收益。
- 主要评估任务：预测已观察到交易的商户未来价值排序；不把本实验描述为新商户冷启动泛化。
- eligibility 只看历史：主表中存在且最近 90 天至少一笔交易。未来 28 天没有交易的标签保留为零，不能删除。

## 2. 明确定义 test dataset

主协议保持现有 90 天历史 / 28 天目标 / 每 28 天一个 cutoff。所有边界均按交易日、首尾包含。
本项目只有日粒度，视为 cutoff 当天数据已完整收到后作决定，不假定盘中实时可用。

| 分区 | Cutoff 日期 | 标签覆盖 | 行数 / 用途 |
|---|---|---|---|
| Train | 2021-06-20、07-18、08-15、09-12、10-10、11-07 | 2021-06-21 至 2021-12-05 | 23,537 merchant-cutoff 行；fit/内部时间交叉验证 |
| Internal validation | 2021-12-05、2022-01-02、01-30 | 2021-12-06 至 2022-02-27 | 11,872 行；比较候选并确定方案 |
| **Primary test** | **2022-02-27** | **2022-02-28 至 2022-03-27** | **3,930 行；冻结后进行一次主测试** |
| Temporal robustness | 2022-03-27、04-24、05-22、06-19、07-17、08-14、09-11 | 2022-03-28 至 2022-10-09 | 27,514 行；7 个单列窗口，模型保持冻结 |

Primary test 的 feature window 为 **2021-11-30 至 2022-02-27（90 天）**。其 4,026 家主表候选
均保留在 coverage/context 文件；其中 96 家无近期历史，不进入 3,930 行主测试模型表。
原始数据最后 17 天（2022-10-10 至 10-26）不足以形成另一完整 28 天标签窗口，不作为额外测试窗口。

交付 ZIP 中的对应路径：

```text
modeling/train/features.parquet
modeling/train/labels.parquet
modeling/validation/features.parquet
modeling/validation/labels.parquet
test/primary/test_features.parquet
test/primary/test_labels.parquet
test/robustness/test_features.parquet
test/robustness/test_labels.parquet
test_definition.json
```

Primary/test labels 在独立目录内，属于逻辑隔离，并未加密。测试数据已经由脚本按协议生成；
“未评分”不等于原始文件从未被 ETL 或质量审计读取。此前全量质量审计可见结构和部分分布；
EDA 覆盖 train + internal validation，internal validation 也不是完全未见数据。因此最终证据应
准确称为“未用于模型选择的时间外主测试”，不作更强的绝对无接触声明。

之后的 robustness 特征窗口自然包含之前已经发生的测试期交易，这符合当时可用历史；
不得因此利用先前测试成绩重新选择特征、调参或改规则。

## 3. 哪些特征可以训练

主方案使用 `primary_feature_contract.json` 中明确列出的 **46 个字段**，不是自动选择所有数值列。
这些包括商业规模、复购/集中度、活跃/增长/波动、窗口内尾部比例和原生粒度 fraud 证据。
同时保留 **31 个字段的 no-fraud 方案**，排除 15 个 fraud signal/probability 字段；
`hist_customer_entity_days` 为独立商业暴露计数，仍可保留。

禁止作为 primary predictors 的字段/数据：

- merchant/user/consumer/order ID、merchant_name、cutoff 和窗口边界等元数据。
- `future_gmv`、`target_revenue`、标签窗口信息。
- 全周期 P99/P99.9 标记和全周期 merchant audit 汇总。
- 最新 `2022-10-26` 商户导出：其历史覆盖 protected period，只用于后续部署/描述，不能混入历史训练。
- 当前 `ctx_` 人口/地理背景及补充候选状态/tenure：保留用于描述和后续经批准的实验，暂不扩充主方案。

静态 merchant tags/take rate 和 fraud 发布时点仍缺版本记录。主方案是带有明确 as-of 假设的回溯实验。
不把 2021 统计年份当成它一定在 2021 cutoff 已经发布。区域收入/SEIFA 描述地区，不代表个人收入/风险。

## 4. 训练前验收

确认清洗 manifest、snapshot config 和数据哈希；核对每行 merchant-cutoff 唯一、X/y 一一对齐、
feature_end < label_start、标签窗口互不重叠、未来零标签未被排除。复核所有 46 字段的公式、单位、
缺失规则与 source availability。按 cutoff 检查 null/零值、极端值、近常数和高相关字段。

已完成的 v3 开发 QA 覆盖 35,409 行；同日 fraud mean、行重排、重复订单、无/单笔订单、未来输入
和地理覆盖的测试随代码提供。若更改特征定义，必须新 run ID 并重做对应验证；不能覆盖旧产物。

## 5. 开发期训练与调参（确认后才执行）

1. **固定规则基线。** 历史 90 天收入 × 28/90；历史最近 28 天收入。无需学习参数，是强制对照。
2. **简单可解释模型。** Ridge：目标 `log1p(target_revenue)`，数值列 median imputation + missing indicator +
   scaling，类别 one-hot。预测经 `expm1` 回到 AUD 并截在零以上。
3. **小规模非线性对照。** Histogram Gradient Boosting 或同等表格树模型；先固定小范围设置，
   分别对比全 46 字段和 no-fraud 31 字段。类别处理必须明确，缺失值不能被解读为低风险。
4. **调参只使用 train 内的时间 folds。** 拟用 expanding-window：前 2 个 train cutoff fit、预测第 3 个；
   前 3 个预测第 4 个；前 4 个预测第 5 个；前 5 个预测第 6 个。每折的 imputer/scaler/encoder/selector
   仅 fit 当折训练部分；不随机拆商户行，目标窗口不能跨越该折 validation cutoff。
5. **拟议搜索预算。** Ridge alpha `{1,10,100}`；树模型以现有固定设置为基础，仅比较 leaf 数 `{15,31}`
   和 min_samples_leaf `{30,60}` 的小网格。先用 seed=30034，只有结果确实不稳定时才加预先列明的 seed。
   这一预算和模型集合也属于待确认计划，不在本轮执行。
6. **候选选择。** 在三个 internal-validation cutoff 上比较 macro mean NDCG@100；同分时比较
   Top-100 oracle capture，再同分优先简单规则。小差异不宣称统计显著。MAE 最优不自动等同于排名最优。
7. **可选实验后置。** Boruta 必须在每个 train fold 内重新选择并检查稳定性；TCN 必须有足够序列和
   明确增益理由。两者均不是完成课程任务的前提，不能凭复杂度取代规则基线。

此前已保存的 validation-only baseline 结果可以用于检查复现；新训练与旧训练的比较要同时记录
代码、特征和运行库版本，不能将版本变化带来的成绩差异全部归因于某个特征修复。

## 6. 冻结与最终测试

选择方案后冻结 predictor allow-list、预处理、超参数、seed、eligibility、tie-breaking、主指标、
分组映射及任何风险/集中度约束。拟议最终做法：在 train + internal validation 的全部 35,409 行上
重新 fit 一次选定管线，数据标签均在 2022-02-27 结束，然后保存不可覆写的模型、配置、代码和输入哈希。
若最终选用规则基线，则冻结公式和输入契约，无需拟合。

运行一次 primary test，报告其独立结果；之后在七个 robustness cutoff 上使用同一冻结模型，逐期报告。
如果 test 不理想，应诚实记录失败；不能调参后仍把相同测试期称为未见测试。新的方法改进需要新的评价设计。

## 7. 报告哪些指标

| 指标 | 用途 / 定义 |
|---|---|
| NDCG@100 | 主排序指标，采用非负线性收入 gain，避免对货币值做指数增益 |
| Top-100 realised revenue | 预测选中的 100 家商户在对应未来窗口的真实收入代理总和 |
| Oracle capture@100 | 上述收入 / 同一候选集合的真实 Top-100 收入；同时报告规则基线对照 |
| Spearman | 全候选排名相关，用于观察总体排序 |
| MAE（AUD） | 金额预测误差，辅助指标 |
| Top-100 Jaccard | 相邻 cutoff 名单稳定性；高稳定性不独自证明收益优越 |
| 分组/资格覆盖 | 每组表现、没有历史的商户处置、缺失主表商户数量和排除原因 |

Primary test 为一个决策日期，robustness 仅七个日期；重复商户行不能当作大量独立时间样本。
报告每个 cutoff 的结果和范围，不用随机 row bootstrap 制造看似很窄的泛化区间。

## 8. 排名与课程最终交付

模型评估完成后，建立覆盖 25 个 category 的 **3–5 个 segment**，或在测试前冻结需要进入比较的
segment 映射；输出总体最多 100 家和每组 Top 10。基于交易价值、活动、客户集中度与可用风险证据
解释推荐原因，单列 active、inactive/no-history/manual-review、missing-master 等处置。

Composite risk/confidence 分数和硬性配额目前没有经确认的业务公式；保持证据字段可见，并先给出
不加任意风险惩罚的价值基线。任何调整规则需在相应最终评价前冻结并做敏感性比较。
年度容量与短期收入代理的差异、merchant location 缺失、合成数据、发布时点和观测窗口限制必须写进总结。

**下一步授权边界：确认本计划之后，才开始新的模型 fit、调参或 primary test 评分。**
