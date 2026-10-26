# Revenue input contract v1

One source row per merchant × cutoff. All `hist_` windows are 90 inclusive calendar days unless explicitly named. Metadata (ID, name, cutoff and boundaries) is never a predictor.

| # | Source field | Definition | Unit | Structural missing rule | Transform |
|---:|---|---|---|---|---|
| 1 | `merchant_category` | Normalised merchant tag category | category | required | C: train-only one-hot; ignore unseen categories |
| 2 | `revenue_level` | Upper-case revenue-level tag | category | required | C: train-only one-hot; ignore unseen categories |
| 3 | `take_rate_pct` | Merchant tag take rate; percentage points | percent | required | N: original numeric definition |
| 4 | `hist_gmv` | Sum of order dollar_value | AUD | zero for no orders | N: original numeric definition |
| 5 | `hist_orders` | Number of orders | count | zero for no orders | N: original numeric definition |
| 6 | `hist_unique_customers` | Distinct user_id count | count | zero for no orders | N: original numeric definition |
| 7 | `hist_aov` | GMV / orders | AUD | null for no orders | N: original numeric definition |
| 8 | `hist_amount_median` | Median order amount | AUD | null for no orders | N: original numeric definition |
| 9 | `hist_amount_std` | Sample standard deviation of order amounts; ddof=1 | AUD | null for fewer than two orders | N: original numeric definition |
| 10 | `hist_active_days` | Distinct order dates | days | zero for no orders | N: original numeric definition |
| 11 | `hist_repeat_customer_rate` | Distinct customers with more than one order / distinct customers | share | null for no customers | N: original numeric definition |
| 12 | `hist_customer_hhi` | Sum of squared customer GMV shares | share | null for zero GMV | N: original numeric definition |
| 13 | `hist_daily_gmv_cv` | Population std of daily GMV over all 90 calendar days (including zero days) / daily mean | ratio | null for zero daily mean | N: original numeric definition |
| 14 | `hist_gmv_last28` | GMV from cutoff-27 through cutoff, inclusive | AUD | zero for no recent orders | N: original numeric definition |
| 15 | `hist_gmv_previous28` | GMV from cutoff-55 through cutoff-28, inclusive | AUD | zero for no earlier orders | N: original numeric definition |
| 16 | `hist_gmv_last7` | GMV from cutoff-6 through cutoff, inclusive | AUD | zero for no recent orders | N: original numeric definition |
| 17 | `hist_high_value_order_share` | Share of eligible-master orders at or above the snapshot-history P99 amount | share | zero for no orders | N: original numeric definition |
| 18 | `hist_high_value_gmv_share` | GMV of high-value orders / GMV; same snapshot-history P99 | share | zero for no orders | N: original numeric definition |
| 19 | `hist_revenue_proxy` | GMV * take_rate_pct / 100 | AUD | zero for no orders | N: original numeric definition |
| 20 | `hist_orders_per_customer` | Orders / distinct customers | ratio | null for no customers | N: original numeric definition |
| 21 | `hist_gmv_per_active_day` | GMV / active days | AUD/day | null for no active days | N: original numeric definition |
| 22 | `hist_active_day_rate` | Active days / history_days | share | zero for no orders | N: original numeric definition |
| 23 | `hist_days_since_last_order` | Cutoff minus most recent historical order date | days | null for no orders | N: original numeric definition |
| 24 | `hist_amount_cv` | Sample order-amount std / AOV | ratio | null for fewer than two orders | N: original numeric definition |
| 25 | `hist_growth_28d` | Last-28-day GMV / previous-28-day GMV - 1 | growth | null when previous28 GMV is zero | N: original numeric definition |
| 26 | `hist_no_previous28_activity` | Indicator: previous28 GMV equals zero | boolean | never null | B: unchanged 0/1 |
| 27 | `hist_gmv_log1p` | log(1 + hist_gmv) | log-AUD | zero for no orders | L: already log1p; do not re-log |
| 28 | `hist_orders_log1p` | log(1 + hist_orders) | log-count | zero for no orders | L: already log1p; do not re-log |
| 29 | `hist_unique_customers_log1p` | log(1 + hist_unique_customers) | log-count | zero for no customers | L: already log1p; do not re-log |
| 30 | `hist_revenue_proxy_log1p` | log(1 + hist_revenue_proxy) | log-AUD | zero for no orders | L: already log1p; do not re-log |

N and L fields: train-only median fill plus an indicator for every numeric field. All-missing training columns use fixed zero and warn. Ridge standardises N/L after filling; HGB does not scale. B and missing indicators remain 0/1. Invalid infinities, rates, negatives, non-structural nulls and date errors fail instead of being imputed. No-history merchants are audit-only.

Rate is percentage points: 2 means 2%, not 200%. `hist_daily_gmv_cv` uses population standard deviation over all 90 calendar days, including zero days. Order amount standard deviation uses ddof=1. P99 is computed only over the cutoff history and master universe; high-value means amount >= P99. `hist_growth_28d` is last28/previous28 - 1, null when denominator zero.

## Six daily TCN channels

| Channel | Definition and unit | Zero-order day | Transform |
|---|---|---|---|
| daily_gmv | Daily GMV, AUD | 0 | log1p then train-only standardise |
| daily_orders | Daily order count | 0 | log1p then train-only standardise |
| daily_unique_customers | Daily distinct user count | 0 | log1p then train-only standardise |
| daily_aov | Daily GMV / orders, AUD/order | 0; interpreted with active flag | log1p then train-only standardise |
| daily_active | Daily orders > 0, binary | 0 | unchanged |
| daily_revenue_proxy | Daily GMV × rate / 100, AUD | 0 | log1p then train-only standardise |

Sequence is cutoff-29 through cutoff, ascending date, exactly 30 steps. A missing source partition fails, never zero-fills a missing file. Static inputs: train-only category and revenue-level one-hot, take_rate_pct / 100, and train-only-standardised hist_revenue_proxy_log1p. Full source fields and encoded column names are saved separately in training.json.

## Fixed course mapping

| Course group | Exact normalised category |
|---|---|
| Home, Garden & Decorative Arts | antique shops - sales, repairs, and restoration services |
| Home, Garden & Decorative Arts | art dealers and galleries |
| Home, Garden & Decorative Arts | equipment, tool, furniture, and appliance rent al and leasing |
| Home, Garden & Decorative Arts | florists supplies, nursery stock, and flowers |
| Home, Garden & Decorative Arts | furniture, home furnishings and equipment shops, and manufacturers, except appliances |
| Home, Garden & Decorative Arts | lawn and garden supply outlets, including nurseries |
| Fashion, Personal Care & Accessories | health and beauty spas |
| Fashion, Personal Care & Accessories | jewelry, watch, clock, and silverware shops |
| Fashion, Personal Care & Accessories | opticians, optical goods, and eyeglasses |
| Fashion, Personal Care & Accessories | shoe shops |
| Fashion, Personal Care & Accessories | watch, clock, and jewelry repair shops |
| Digital, Technology & Communications | cable, satellite, and other pay television and radio services |
| Digital, Technology & Communications | computer programming , data processing, and integrated systems design services |
| Digital, Technology & Communications | computers, computer peripheral equipment, and software |
| Digital, Technology & Communications | digital goods: books, movies, music |
| Digital, Technology & Communications | telecom |
| Mobility & Outdoor | bicycle shops - sales and service |
| Mobility & Outdoor | motor vehicle supplies and new parts |
| Mobility & Outdoor | tent and awning shops |
| Culture, Creative, Gifts & Office | artist supply and craft shops |
| Culture, Creative, Gifts & Office | books, periodicals, and newspapers |
| Culture, Creative, Gifts & Office | gift, card, novelty, and souvenir shops |
| Culture, Creative, Gifts & Office | hobby, toy and game shops |
| Culture, Creative, Gifts & Office | music shops - musical instruments, pianos, and sheet music |
| Culture, Creative, Gifts & Office | stationery, office supplies and printing and writing paper |

Rationale: operating content (domestic goods/services; appearance/accessories; digital/communications; mobility/outdoor; creative/cultural/gifting/office), fixed before test. Mapping is not a validated ANZSIC crosswalk. See seven_engine_protocol.md for independent group ranking and the complete temporal/decision rules.
