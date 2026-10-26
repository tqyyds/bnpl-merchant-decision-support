SELECT model,
       AVG(ndcg) AS mean_validation_ndcg,
       AVG(oracle_capture) AS mean_validation_oracle_capture,
       AVG(mae) AS mean_validation_mae_aud,
       MAX(replaces_baseline) AS replaces_baseline
FROM validation_metrics
GROUP BY model
ORDER BY model;
