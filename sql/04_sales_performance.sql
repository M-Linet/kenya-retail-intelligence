-- 04_sales_performance.sql
-- Business questions 1-8 (sales performance). All queries read the semantic views in 03_views.sql.
-- Period: 1 Nov 2024 - 31 Oct 2026. "Year 1" = Nov 2024 - Oct 2025, "Year 2" = Nov 2025 - Oct 2026.

-- @query q01_headline_kpis
-- Question 1: What is the total revenue generated, and what are the headline commercial KPIs?
-- Note: transactions and ATV come from v_baskets (one row per basket), so line joins cannot inflate them.
WITH lines AS (
    SELECT SUM(gross_sales) AS gross_sales, SUM(discount_amount) AS discounts, SUM(net_revenue) AS net_revenue,
           SUM(cogs) AS cogs, SUM(gross_profit) AS gross_profit, SUM(quantity) AS units
    FROM retail.v_sales_lines
), baskets AS (
    SELECT COUNT(*) AS transactions, AVG(basket_revenue) AS atv, AVG(units) AS units_per_basket,
           AVG(CASE WHEN customer_id IS NOT NULL THEN 1.0 ELSE 0 END) AS loyalty_share
    FROM retail.v_baskets
)
SELECT ROUND(l.gross_sales, 0)                          AS gross_sales_kes,
       ROUND(l.discounts, 0)                            AS discounts_kes,
       ROUND(l.net_revenue, 0)                          AS net_revenue_kes,
       ROUND(l.cogs, 0)                                 AS cogs_kes,
       ROUND(l.gross_profit, 0)                         AS gross_profit_kes,
       ROUND(100 * l.gross_profit / l.net_revenue, 2)   AS gross_margin_pct,
       ROUND(100 * l.discounts / l.gross_sales, 2)      AS discount_rate_pct,
       l.units                                          AS units_sold,
       b.transactions,
       ROUND(b.atv, 2)                                  AS avg_transaction_value_kes,
       ROUND(b.units_per_basket, 2)                     AS units_per_basket,
       ROUND(100 * b.loyalty_share, 1)                  AS loyalty_identified_pct
FROM lines l CROSS JOIN baskets b;

-- @query q02_monthly_revenue_mom
-- Question 2: How does revenue change monthly? Includes month-over-month growth (LAG) and a running total (SUM OVER).
WITH m AS (
    SELECT sale_month, SUM(net_revenue) AS revenue, SUM(gross_profit) AS gross_profit,
           COUNT(DISTINCT transaction_id) AS transactions
    FROM retail.v_sales_lines
    GROUP BY sale_month
)
SELECT sale_month,
       ROUND(revenue, 0)                                                    AS revenue_kes,
       ROUND(gross_profit, 0)                                               AS gross_profit_kes,
       ROUND(100 * gross_profit / revenue, 2)                               AS gross_margin_pct,
       transactions,
       ROUND(100 * (revenue / LAG(revenue) OVER (ORDER BY sale_month) - 1), 2) AS mom_growth_pct,
       ROUND(SUM(revenue) OVER (ORDER BY sale_month), 0)                    AS running_revenue_kes,
       ROUND(AVG(revenue) OVER (ORDER BY sale_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 0) AS revenue_3m_avg_kes
FROM m
ORDER BY sale_month;

-- @query q03_year_over_year
-- Question 2 (cont.): Is growth real? Year 2 vs Year 1, total and like-for-like
-- (excluding Ruiru, BR10, which opened in June 2025 and so has no full comparison year).
WITH y AS (
    SELECT CASE WHEN sale_date < DATE '2025-11-01' THEN 'Year 1' ELSE 'Year 2' END AS period,
           branch_id, net_revenue, gross_profit, transaction_id
    FROM retail.v_sales_lines
)
SELECT scope,
       ROUND(SUM(CASE WHEN period = 'Year 1' THEN net_revenue END), 0) AS year1_revenue_kes,
       ROUND(SUM(CASE WHEN period = 'Year 2' THEN net_revenue END), 0) AS year2_revenue_kes,
       ROUND(100 * (SUM(CASE WHEN period = 'Year 2' THEN net_revenue END)
                  / SUM(CASE WHEN period = 'Year 1' THEN net_revenue END) - 1), 2) AS revenue_growth_pct,
       ROUND(100 * (SUM(CASE WHEN period = 'Year 2' THEN gross_profit END)
                  / SUM(CASE WHEN period = 'Year 1' THEN gross_profit END) - 1), 2) AS gross_profit_growth_pct
FROM (
    SELECT 'All branches' AS scope, * FROM y
    UNION ALL
    SELECT 'Like-for-like (excl. BR10)', * FROM y WHERE branch_id <> 'BR10'
) s
GROUP BY scope;

-- @query q04_branch_ranking
-- Question 3: Which branches generate the highest revenue? Ranked with RANK(), plus share of chain revenue.
WITH b AS (
    SELECT v.branch_id, SUM(v.net_revenue) AS revenue, SUM(v.gross_profit) AS gross_profit,
           SUM(v.discount_amount) AS discounts, SUM(v.gross_sales) AS gross_sales,
           COUNT(DISTINCT v.transaction_id) AS transactions
    FROM retail.v_sales_lines v
    GROUP BY v.branch_id
)
SELECT RANK() OVER (ORDER BY b.revenue DESC)              AS revenue_rank,
       b.branch_id, br.branch_name, br.county, br.branch_type,
       ROUND(b.revenue, 0)                                AS revenue_kes,
       ROUND(100 * b.revenue / SUM(b.revenue) OVER (), 2) AS share_of_chain_pct,
       ROUND(b.gross_profit, 0)                           AS gross_profit_kes,
       ROUND(100 * b.gross_profit / b.revenue, 2)         AS gross_margin_pct,
       RANK() OVER (ORDER BY b.gross_profit / b.revenue DESC) AS margin_rank,
       b.transactions,
       ROUND(b.revenue / b.transactions, 0)               AS atv_kes
FROM b JOIN retail.branches br USING (branch_id)
ORDER BY revenue_rank;

-- @query q05_county_contribution
-- Question 4: Which counties contribute most to sales? Revenue per branch normalises for branch count.
SELECT br.county,
       COUNT(DISTINCT br.branch_id)                                  AS branches,
       ROUND(SUM(v.net_revenue), 0)                                  AS revenue_kes,
       ROUND(100 * SUM(v.net_revenue) / SUM(SUM(v.net_revenue)) OVER (), 2) AS share_pct,
       ROUND(SUM(v.net_revenue) / COUNT(DISTINCT br.branch_id), 0)   AS revenue_per_branch_kes,
       ROUND(100 * SUM(v.gross_profit) / SUM(v.net_revenue), 2)      AS gross_margin_pct
FROM retail.v_sales_lines v
JOIN retail.branches br USING (branch_id)
GROUP BY br.county
ORDER BY revenue_kes DESC;

-- @query q06_category_revenue
-- Question 5: Which product categories generate the most revenue, and how does that compare with their profit share?
SELECT category,
       ROUND(SUM(net_revenue), 0)                                    AS revenue_kes,
       ROUND(100 * SUM(net_revenue) / SUM(SUM(net_revenue)) OVER (), 2)   AS revenue_share_pct,
       ROUND(SUM(gross_profit), 0)                                   AS gross_profit_kes,
       ROUND(100 * SUM(gross_profit) / SUM(SUM(gross_profit)) OVER (), 2) AS gp_share_pct,
       ROUND(100 * SUM(gross_profit) / SUM(net_revenue), 2)          AS gross_margin_pct,
       SUM(quantity)                                                 AS units
FROM retail.v_sales_lines
GROUP BY category
ORDER BY revenue_kes DESC;

-- @query q07_day_of_week
-- Question 6: What are the busiest shopping days?
-- Denominator: the number of calendar days of each weekday in the period (from v_dim_date), so a weekday
-- that occurs 105 times is not compared with one that occurs 104 times.
WITH daily AS (
    SELECT sale_date, SUM(net_revenue) AS revenue, COUNT(DISTINCT transaction_id) AS transactions
    FROM retail.v_sales_lines GROUP BY sale_date
)
SELECT d.iso_dow, d.day_short,
       COUNT(*)                                   AS days_in_period,
       ROUND(AVG(COALESCE(x.revenue, 0)), 0)      AS avg_daily_revenue_kes,
       ROUND(AVG(COALESCE(x.transactions, 0)), 0) AS avg_daily_transactions,
       ROUND(100 * (AVG(COALESCE(x.revenue, 0)) / AVG(AVG(COALESCE(x.revenue, 0))) OVER () - 1), 1) AS index_vs_avg_day_pct
FROM retail.v_dim_date d
LEFT JOIN daily x ON x.sale_date = d.date
GROUP BY d.iso_dow, d.day_short
ORDER BY d.iso_dow;

-- @query q08_hourly_profile
-- Question 7: What are the busiest shopping periods within the day, weekday vs weekend?
SELECT EXTRACT(HOUR FROM transaction_ts)::int AS hour_of_day,
       COUNT(*) FILTER (WHERE EXTRACT(ISODOW FROM transaction_ts) < 6)  AS weekday_transactions,
       COUNT(*) FILTER (WHERE EXTRACT(ISODOW FROM transaction_ts) >= 6) AS weekend_transactions,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)               AS share_of_all_transactions_pct
FROM retail.v_baskets
GROUP BY 1
ORDER BY 1;

-- @query q09_weekday_vs_weekend
-- Question 8: How does weekday performance compare with weekend performance (per calendar day)?
WITH daily AS (
    SELECT sale_date, SUM(net_revenue) AS revenue, COUNT(DISTINCT transaction_id) AS transactions
    FROM retail.v_sales_lines GROUP BY sale_date
)
SELECT CASE WHEN d.is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_type,
       COUNT(*)                                  AS days,
       ROUND(AVG(x.revenue), 0)                  AS avg_daily_revenue_kes,
       ROUND(AVG(x.transactions), 0)             AS avg_daily_transactions,
       ROUND(SUM(x.revenue) / SUM(x.transactions), 0) AS atv_kes
FROM retail.v_dim_date d JOIN daily x ON x.sale_date = d.date
GROUP BY 1;

-- @query q10_payday_window
-- Question 7 (cont.): Do sales concentrate around salary dates (25th to 3rd)? December excluded to avoid
-- mixing the festive peak with the payday effect.
WITH daily AS (
    SELECT sale_date, SUM(net_revenue) AS revenue, COUNT(DISTINCT transaction_id) AS transactions
    FROM retail.v_sales_lines GROUP BY sale_date
)
SELECT CASE WHEN d.is_payday_window THEN 'Payday window (25th-3rd)' ELSE 'Mid-month (4th-24th)' END AS period,
       COUNT(*)                         AS days,
       ROUND(AVG(x.revenue), 0)         AS avg_daily_revenue_kes,
       ROUND(AVG(x.transactions), 0)    AS avg_daily_transactions
FROM retail.v_dim_date d JOIN daily x ON x.sale_date = d.date
WHERE d.month_number <> 12
GROUP BY 1;

-- @query q11_branch_growth_trend
-- Questions 3 and 19: which branches are growing or declining? Year 2 vs Year 1 by branch, plus the
-- latest-quarter trend. Ruiru (BR10) has no full Year 1.
WITH x AS (
    SELECT branch_id,
           SUM(net_revenue) FILTER (WHERE sale_date <  DATE '2025-11-01') AS y1,
           SUM(net_revenue) FILTER (WHERE sale_date >= DATE '2025-11-01') AS y2,
           SUM(net_revenue) FILTER (WHERE sale_date >= DATE '2026-08-01') AS last_q,
           SUM(net_revenue) FILTER (WHERE sale_date >= DATE '2025-08-01' AND sale_date < DATE '2025-11-01') AS same_q_last_year
    FROM retail.v_sales_lines GROUP BY branch_id
)
SELECT x.branch_id, b.branch_name, b.opening_date,
       ROUND(y1, 0) AS year1_revenue_kes, ROUND(y2, 0) AS year2_revenue_kes,
       CASE WHEN b.opening_date > DATE '2024-11-01' THEN NULL
            ELSE ROUND(100 * (y2 / y1 - 1), 2) END                    AS yoy_growth_pct,
       CASE WHEN b.opening_date > DATE '2025-08-01' THEN NULL
            ELSE ROUND(100 * (last_q / same_q_last_year - 1), 2) END  AS latest_quarter_yoy_pct
FROM x JOIN retail.branches b USING (branch_id)
ORDER BY yoy_growth_pct NULLS LAST;
