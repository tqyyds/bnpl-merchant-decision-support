# Resume and interview material

## Project entry

**BNPL Merchant Decision Support | Independent Data Science Project**  
Python, pandas, PyArrow, scikit-learn, PyTorch, SciPy MILP, JavaScript, GitHub Actions  
https://github.com/tqyyds/bnpl-merchant-decision-support

- Developed an end-to-end merchant decision-support system, processing 14.2M transactions and 500K consumer records through versioned ETL, validated joins and traceable feature pipelines.
- Designed 90-day/28-day temporal experiments comparing revenue baselines, Ridge, gradient boosting and a three-seed causal TCN; retained the 90-day baseline under a fixed selection gate, with historical validation NDCG@100 of 0.9939.
- Built binary MILP merchant portfolio selection and an interactive dashboard for evidence inspection, confidence diagnostics and scenario comparison, with synthetic public demos and automated contract checks.

## 中文简历版本

**BNPL 商户决策支持系统｜独立数据科学项目**

- 独立完成从数据清洗、特征工程、收入建模、商户组合优化到交互仪表盘的完整系统，处理 1,420 万笔交易及约 50 万名消费者数据。
- 构建 90 天历史 / 28 天预测的时序实验，比较收入基线、Ridge、梯度提升及三随机种子 TCN；依固定规则保留历史验证 NDCG@100 达 0.9939 的收入基线。
- 使用 SciPy 二元 MILP 生成商户组合，实现风险证据、置信度和方案对比界面，并提供合成数据演示与自动化检查。

## Interview explanation

The business problem was to prioritise up to 100 BNPL merchants using historical evidence. I built the pipeline from immutable source validation to rolling merchant features, evaluated simple and learned revenue models under temporal splits, and converted scores into explicit portfolio decisions. I also built the inspection dashboard so a reviewer can see where the recommendation came from.

A key decision was to keep a strong simple baseline when the trained TCN did not pass the fixed replacement gate. The system reports take-rate revenue rather than claiming profit, keeps missing fraud evidence unknown and discloses insufficient interval calibration. The public demo uses invented records; historical aggregate results and private-data reproduction are documented separately.

## Metric wording

Use “historical validation NDCG@100 of 0.9939.” Do not describe it as 99.39% prediction accuracy, test accuracy, guaranteed future return or profit improvement. Synthetic public demo values do not establish model performance.
