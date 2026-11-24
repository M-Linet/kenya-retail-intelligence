# SQL query guide

This guide covers the 30 analytical queries and 14 data-quality checks. Each query is listed with its business purpose, the question it answers, the SQL techniques it uses, and what the result showed. The SQL itself is in `sql/`, and the full result of every query is in `reports/sql_outputs/<name>.csv` (regenerate with `python -m src.run_sql`). All figures describe the **fictional** Savanna Fresh chain built from synthetic data.

Technique key: **J** = joins · **A** = aggregation · **CW** = CASE WHEN · **CTE** · **SQ** = subquery · **W** = window function · **D** = date logic · **V** = semantic view

## Semantic layer (`03_views.sql`)
| View | Why it exists |
|---|---|
| `v_sales_lines` | One row per sold line with gross sales, net revenue, COGS, gross profit and price type. It defines "revenue" in one place. |
| `v_baskets` | One row per receipt, so that basket counts and ATV can never be inflated by line-level joins. |
| `v_dim_date` | The calendar. It provides correct denominators (number of Mondays, payday days) and feeds Power BI. |
| `v_weekly_product_sales`, `v_inventory_weekly` | Align each Sunday stock count with the same week's sales. |
| `v_inventory_position` | The latest stock per branch-product, with 12-week demand, weeks of cover and a stock-status label. |

## Data quality (`02_data_quality_checks.sql`)
Part A (`dq_a01`–`dq_a11`) profiles the raw staging layer: duplicates, missing values, label variants, invalid years, orphan keys, quantity bands, zero prices, negative stock and reversed promotion dates. Part B proves the clean layer is sound. `dq_b01` runs 11 integrity checks that must all return 0, and they do. `dq_b02` shows the sales view has exactly as many rows as the line table (no join fan-out). `dq_b03` summarises the exception log. Notebooks 02 and 03 interpret these results.

## Sales performance (`04_sales_performance.sql`)

**q01_headline_kpis**: *Q1: total revenue and headline KPIs.* CTE, A, CROSS JOIN of line-level and basket-level aggregates.
Result: net revenue KES 489.6M, gross profit KES 91.2M (18.62% margin), 289,936 transactions, ATV KES 1,689, discounts 0.95% of gross sales; 61.9% of baskets carry a loyalty ID.

**q02_monthly_revenue_mom**: *Q2: how revenue changes monthly.* CTE, W (`LAG`, running `SUM() OVER`, 3-month moving `AVG() OVER ROWS`), D.
Result: December peaks (KES 25.7M in 2024, 28.3M in 2025) are followed by January drops of 36–37%. Month-over-month growth is therefore dominated by seasonality, which is why the report uses year-over-year comparisons.

**q03_year_over_year**: *Is growth real?* CTE, CW, conditional aggregation, UNION ALL.
Result: total revenue +10.3% (Year 2 vs Year 1), but like-for-like (excluding Ruiru, opened June 2025) only +6.3%. Like-for-like gross profit grew 5.96%, slightly behind revenue.

**q04_branch_ranking**: *Q3: highest-revenue branches.* J, A, W (`RANK`, share via `SUM() OVER ()`).
Result: Westlands (15.5% of revenue), Nyali and Nakuru lead. Nyali is #2 on revenue but last (#12) on margin, which is the first signal of a problem there.

**q05_county_contribution**: *Q4: county contribution.* J, A, W.
Result: Nairobi 30.2%, Mombasa 22.4%. Mombasa has the highest revenue per branch (KES 54.7M) and the lowest county margin (17.9%).

**q06_category_revenue**: *Q5: category revenue and profit share.* A, W.
Result: Staples are 31.1% of revenue but 16.6% of gross profit (9.9% margin). Fresh Produce is 7.3% of revenue but 13.0% of gross profit (33.1% margin).

**q07_day_of_week**: *Q6: busiest days.* CTE, LEFT JOIN to the calendar, W. Averages are per calendar day, so each weekday is compared on equal terms.
Result: Saturday averages KES 891K a day, 33% above the average day. Monday and Tuesday are about 16% below.

**q08_hourly_profile**: *Q7: busiest periods.* Conditional `COUNT(*) FILTER`, D.
Result: weekday traffic peaks at 17:00–19:59 (18:00 is the busiest hour), while weekends peak at 12:00–13:59. This matters for staffing and replenishment timing.

**q09_weekday_vs_weekend**: *Q8.* CW, J to calendar.
Result: a weekend day averages KES 815K against KES 613K on a weekday (+33%). ATV is almost identical (KES 1,701 vs 1,682), so the weekend lift comes from **more shoppers, not bigger baskets**.

**q10_payday_window**: *Q7 (cont.).* CW, D; December excluded to avoid mixing the festive and payday effects.
Result: days from the 25th to the 3rd average KES 735K against KES 615K mid-month (+19%).

**q11_branch_growth_trend**: *Q3/Q19: which branches are growing or declining?* Conditional `SUM() FILTER`, CW for new branches.
Result: Machakos is the only established branch in decline (−11.9% YoY, −13.4% in the latest quarter). Thika (+9.3%) and Westlands (+8.5%) grew fastest.

## Profitability (`05_profitability.sql`)

**q12_top_products_gross_profit**: *Q9.* CTE, J, W (`RANK`, cumulative share).
Result: the top earners are high-margin everyday lines (Savanna Farm Tomatoes, Mtoto Soft Diapers, Tamu Dairy Cheese). The top five deliver 13.5% of chain gross profit.

**q13_high_revenue_low_margin**: *Q10.* CTE, W (`NTILE(4)`), CROSS JOIN to the chain benchmark.
Result: 29 top-quartile-revenue products sit below the chain margin. Cooking oil 3L (5.3–11.4%), sugar, flour and rice dominate, along with eggs.

**q14_top5_products_per_branch**: *Top 5 products per branch.* W (`ROW_NUMBER() OVER (PARTITION BY branch)`).
Result: tomatoes are the #1 gross-profit product in 8 of 12 branches. Kisumu and Ruiru lead with bar soap, and Naivasha with diapers.

**q15_category_performance**: *Q13: underperforming categories.* Conditional aggregation, W, CW label.
Result: Household & Cleaning is the only category with falling like-for-like revenue (−2.9%) and gross profit (−2.6%). Snacks grew only 1.7%. Staples and Dairy dilute margin.

**q16_branch_margin_drivers**: *Q11/Q19: why do branch margins differ?* Conditional `SUM() FILTER` by price type.
Result: Nyali's margin before discounts (19.8%) is normal. Its non-promotional discounts are 2.58% of sales (about 0.4% elsewhere) and touch 17.8% of its lines (about 2.2% elsewhere), worth KES 1.77M over two years.

**q17_non_promo_discount_by_category_branch**: *Diagnostic.* Conditional aggregation, `COALESCE`.
Result: in 11 branches, non-promotional discounts occur only on perishables (markdowns). Nyali alone discounts ambient goods (1.59% of its sales), which is consistent with manual price overrides.

## Promotions (`06_promotions.sql`)

**q18_promotion_performance**: *Q12.* Multi-CTE baseline design: promotion-window units and GP vs the 28 days before, restricted to full-price days. Date arithmetic, `NULLIF`.
Result: 103 promotions could be measured. 74 were GP-negative and 29 GP-positive. Units almost always rose, but the margin given away on baseline volume usually exceeded the margin on extra units.

**q19_promotion_summary_by_category**: *Q21: where should promotional spend go?* Roll-up of q18.
Result: Snacks & Confectionery returns +0.15 KES of incremental GP per KES of discount (11 of 15 promotions positive), and Personal Care roughly breaks even. Staples (−0.58; 0 of 25 positive) and Dairy (−0.59) destroy the most.

## Inventory (`07_inventory.sql`)

**q20_inventory_turnover_by_category**: *Q14.* CTE, averages of weekly stock value, annualisation.
Result: Dairy turns 28 times a year (1.8 weeks of stock), while Personal Care turns 11.6 times (4.5 weeks) and Household & Cleaning 15.6 times (3.3 weeks).

**q21_product_turnover_extremes**: *Q14/15.* W (`RANK` in both directions), `LEFT JOIN` so that products with no sales are kept.
Result: the fastest products (mostly dairy, bakery, beverage and staple lines) turn 30–36 times a year. The slowest ten turn only 2–6 times. They are mainly premium or tail SKUs (deodorants, hair food, premium soda) plus the two collapsed Household SKUs.

**q22_slow_moving_stock_value**: *Q15/18.* A, W.
Result: of KES 8.7M stock at cost, KES 0.50M (5.7%) is slow-moving (more than 26 weeks of cover) or unsold for 12 weeks.

**q23_slow_moving_products**: *Q15.* J, A, `NULLIF`.
Result: two Household SKUs, Nyota Clean Toilet Paper (308 weeks of cover) and Safi Home Detergent (153 weeks), hold KES 384K of the KES 497K.

**q24_stockout_rate_by_branch**: *Q16.* A, `FILTER`, W (`RANK`).
Result: Kisumu 23.4% and Eldoret 18.9% of product-weeks close at zero, against 3.9–7.0% for most branches. Naivasha is borderline at 10.3%.

**q25_stockout_by_category**: *Q16 (cont.).*
Result: Beverages (11.4%) and Staples (10.3%) run out most, which matters because these are the footfall categories.

**q26_replenishment_watchlist**: *Q17.* CTEs, `FILTER`, a SQ for the latest date, a join to the position view.
Result: 30 branch-product pairs with at least 3 stockout weeks in the last 12, ranked by the gross profit they earn per in-stock week. Several show reorder levels far below weekly demand (for example cheese at 9–11 units).

**q27_reorder_level_adequacy**: *Q22: root cause.* CTE, CW banding.
Result: in every branch, pairs with a reorder level below 0.75 weeks of demand stock out in 27–55% of weeks. Kisumu and Eldoret stock out at 17–20% even with a normal reorder cover, which points to a lead-time problem rather than a parameter one.

**q28_lost_sales_estimate**: *Q22: the cost.* CTEs; stockout weeks × the pair's normal in-stock GP.
Result: about KES 6.0M of gross profit is estimated lost chain-wide over two years, 48% of it at Kisumu and Eldoret (KES 2.87M). This is an approximation, because demand during a stockout is unobservable.

## Management scorecard (`08_management_scorecard.sql`)

**q29_branch_scorecard**: *Q19.* Four CTEs, CW flags, `CONCAT_WS`, ordering by flag count.
Result: Nyali (margin plus discounting), Kisumu, Eldoret and Naivasha (stockouts), and Machakos (declining sales) are flagged. The other 7 branches are clean.

**q30_category_scorecard**: *Q20.* CTEs joining sales, availability and stock health.
Result: Household & Cleaning needs the most attention (negative GP growth, and 31.6% of its stock is slow-moving). Beverages and Staples need availability work (stockouts above 10%).
