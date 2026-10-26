"""The complete v3 predictor contract, shared by documentation and QA."""

SPECS = {
    'merchant_category': ('Normalised merchant tag category', 'category', 'required'),
    'revenue_level': ('Upper-case revenue-level tag', 'category', 'required'),
    'take_rate_pct': ('Merchant tag take rate; percentage points', 'percent', 'required'),
    'hist_gmv': ('Sum of order dollar_value', 'AUD', 'zero for no orders'),
    'hist_orders': ('Number of orders', 'count', 'zero for no orders'),
    'hist_unique_customers': ('Distinct user_id count', 'count', 'zero for no orders'),
    'hist_aov': ('GMV / orders', 'AUD', 'null for no orders'),
    'hist_amount_median': ('Median order amount', 'AUD', 'null for no orders'),
    'hist_amount_std': ('Sample standard deviation of order amounts; ddof=1', 'AUD', 'null for fewer than two orders'),
    'hist_active_days': ('Distinct order dates', 'days', 'zero for no orders'),
    'hist_repeat_customer_rate': ('Distinct customers with more than one order / distinct customers', 'share', 'null for no customers'),
    'hist_customer_hhi': ('Sum of squared customer GMV shares', 'share', 'null for zero GMV'),
    'hist_daily_gmv_cv': ('Population std of daily GMV over all 90 calendar days (including zero days) / daily mean', 'ratio', 'null for zero daily mean'),
    'hist_gmv_last28': ('GMV from cutoff-27 through cutoff, inclusive', 'AUD', 'zero for no recent orders'),
    'hist_gmv_previous28': ('GMV from cutoff-55 through cutoff-28, inclusive', 'AUD', 'zero for no earlier orders'),
    'hist_gmv_last7': ('GMV from cutoff-6 through cutoff, inclusive', 'AUD', 'zero for no recent orders'),
    'hist_high_value_order_share': ('Share of eligible-master orders at or above the snapshot-history P99 amount', 'share', 'zero for no orders'),
    'hist_high_value_gmv_share': ('GMV of high-value orders / GMV; same snapshot-history P99', 'share', 'zero for no orders'),
    'hist_customer_entity_days': ('Distinct merchant-user-date exposures', 'count', 'zero for no exposures'),
    'hist_consumer_signal_entity_days': ('Exposures matched to a non-null native user-date fraud observation', 'count', 'zero for no matched signals'),
    'hist_consumer_signal_days': ('Distinct dates among matched consumer signals', 'days', 'zero for no matched signals'),
    'hist_consumer_probability_mean': ('Unweighted mean across observed merchant-user-date probabilities / 100', 'share', 'null for no matched signals'),
    'hist_consumer_probability_max': ('Maximum observed merchant-user-date probability / 100', 'share', 'null for no matched signals'),
    'hist_consumer_probability_latest_day_mean': ('Mean across distinct observed users on the latest matched date / 100', 'share', 'null for no matched signals'),
    'hist_consumer_signal_coverage': ('Matched consumer entity-days / all exposed customer entity-days', 'share', 'zero if no exposures'),
    'hist_consumer_signal_recency_days': ('Cutoff minus latest matched consumer signal date', 'days', 'null for no matched signals'),
    'hist_merchant_signal_days': ('Count of native merchant-date observations within history, including non-trading days', 'days', 'zero for no observed signals'),
    'hist_merchant_probability_mean': ('Mean native merchant-date probability / 100', 'share', 'null for no observed signals'),
    'hist_merchant_probability_max': ('Maximum native merchant-date probability / 100', 'share', 'null for no observed signals'),
    'hist_merchant_probability_latest': ('Probability on latest native merchant-date / 100', 'share', 'null for no observed signals'),
    'hist_merchant_signal_calendar_coverage': ('Observed native merchant signal days / history_days', 'share', 'zero for no observed signals'),
    'hist_merchant_signal_recency_days': ('Cutoff minus latest native merchant signal date', 'days', 'null for no observed signals'),
    'hist_revenue_proxy': ('GMV * take_rate_pct / 100', 'AUD', 'zero for no orders'),
    'hist_orders_per_customer': ('Orders / distinct customers', 'ratio', 'null for no customers'),
    'hist_gmv_per_active_day': ('GMV / active days', 'AUD/day', 'null for no active days'),
    'hist_active_day_rate': ('Active days / history_days', 'share', 'zero for no orders'),
    'hist_days_since_last_order': ('Cutoff minus most recent historical order date', 'days', 'null for no orders'),
    'hist_amount_cv': ('Sample order-amount std / AOV', 'ratio', 'null for fewer than two orders'),
    'hist_growth_28d': ('Last-28-day GMV / previous-28-day GMV - 1', 'growth', 'null when previous28 GMV is zero'),
    'hist_no_previous28_activity': ('Indicator: previous28 GMV equals zero', 'boolean', 'never null'),
    'hist_consumer_signal_missing': ('Indicator: no observed consumer entity-days', 'boolean', 'never null; not a risk label'),
    'hist_merchant_signal_missing': ('Indicator: no observed native merchant-days', 'boolean', 'never null; not a risk label'),
    'hist_gmv_log1p': ('log(1 + hist_gmv)', 'log-AUD', 'zero for no orders'),
    'hist_orders_log1p': ('log(1 + hist_orders)', 'log-count', 'zero for no orders'),
    'hist_unique_customers_log1p': ('log(1 + hist_unique_customers)', 'log-count', 'zero for no customers'),
    'hist_revenue_proxy_log1p': ('log(1 + hist_revenue_proxy)', 'log-AUD', 'zero for no orders'),
}


def feature_contract() -> dict:
    fields = []
    for name, (formula, unit, missing) in SPECS.items():
        is_fraud = any(token in name for token in ('consumer_probability', 'consumer_signal', 'merchant_probability', 'merchant_signal'))
        fields.append({
            'name': name, 'formula': formula, 'unit': unit, 'missing_rule': missing,
            'grain': 'merchant_abn x cutoff',
            'availability': ('unversioned merchant master; retrospective availability assumption'
                             if not name.startswith('hist_') else
                             'event_date <= cutoff; publication lag unknown' if is_fraud else
                             'historical orders only: cutoff-89 through cutoff'),
            'preprocessing': 'fit train only; observed missingness is never labelled as zero risk',
        })
    return {'version': 'feature_contract_v3', 'history_days': 90, 'predictor_count': len(fields), 'fields': fields}
