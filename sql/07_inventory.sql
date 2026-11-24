-- 07_inventory.sql
-- Business questions 14-18 and 22 (inventory).
-- Snapshots are Sunday closing-stock counts per branch-product (105 weeks; Ruiru from June 2025).
--   stock value               = stock_quantity x unit_cost (at cost, not retail)
--   annualised turnover       = COGS in the period / average stock value at cost x (364 / days covered)
--   stockout week             = closing stock of zero (the shelf was empty at the end of that week)
--   weeks of cover            = closing stock / average weekly units sold over the last 12 weeks

-- @query q20_inventory_turnover_by_category
-- Question 14: inventory turnover by category (chain level).
WITH stock AS (
    SELECT category, snapshot_date, SUM(stock_value_at_cost) AS stock_value
    FROM retail.v_inventory_weekly GROUP BY category, snapshot_date
), avg_stock AS (
    SELECT category, AVG(stock_value) AS avg_stock_value, COUNT(*) AS weeks FROM stock GROUP BY category
), cogs AS (
    SELECT category, SUM(cogs) AS cogs FROM retail.v_sales_lines GROUP BY category
)
SELECT a.category,
       ROUND(c.cogs, 0)                                         AS cogs_kes,
       ROUND(a.avg_stock_value, 0)                              AS avg_stock_value_kes,
       ROUND(c.cogs / a.avg_stock_value * (364.0 / (a.weeks * 7)), 1) AS annual_turnover,
       ROUND(52 / (c.cogs / a.avg_stock_value * (364.0 / (a.weeks * 7))), 1) AS avg_weeks_of_stock
FROM avg_stock a JOIN cogs c USING (category)
ORDER BY annual_turnover DESC;

-- @query q21_product_turnover_extremes
-- Questions 14-15: the fastest- and slowest-turning products (chain level), with RANK() in both directions.
WITH s AS (
    SELECT product_id, snapshot_date, SUM(stock_value_at_cost) AS sv FROM retail.v_inventory_weekly GROUP BY product_id, snapshot_date
), a AS (
    SELECT product_id, AVG(sv) AS avg_sv, COUNT(*) AS weeks FROM s GROUP BY product_id
), c AS (
    SELECT product_id, SUM(cogs) AS cogs FROM retail.v_sales_lines GROUP BY product_id
), t AS (
    SELECT a.product_id, a.avg_sv, COALESCE(c.cogs, 0) AS cogs,
           COALESCE(c.cogs, 0) / NULLIF(a.avg_sv, 0) * (364.0 / (a.weeks * 7)) AS turnover
    FROM a LEFT JOIN c USING (product_id)
), r AS (
    SELECT t.*, RANK() OVER (ORDER BY turnover DESC) AS fast_rank, RANK() OVER (ORDER BY turnover ASC) AS slow_rank FROM t
)
SELECT CASE WHEN fast_rank <= 10 THEN 'Fastest 10' ELSE 'Slowest 10' END AS grp,
       r.product_id, p.product_name, p.category,
       ROUND(r.turnover, 1) AS annual_turnover, ROUND(r.avg_sv, 0) AS avg_stock_value_kes, ROUND(r.cogs, 0) AS cogs_kes
FROM r JOIN retail.products p USING (product_id)
WHERE fast_rank <= 10 OR slow_rank <= 10
ORDER BY r.turnover DESC;

-- @query q22_slow_moving_stock_value
-- Questions 15 and 18: how much inventory value is tied up in slow-moving stock at the latest count?
SELECT stock_status,
       COUNT(*)                                           AS branch_product_lines,
       ROUND(SUM(stock_value_at_cost), 0)                 AS stock_value_kes,
       ROUND(100 * SUM(stock_value_at_cost) / SUM(SUM(stock_value_at_cost)) OVER (), 2) AS share_of_stock_value_pct
FROM retail.v_inventory_position
GROUP BY stock_status
ORDER BY stock_value_kes DESC;

-- @query q23_slow_moving_products
-- Question 15: the products behind the slow-moving value (latest count, summed across branches).
SELECT ip.product_id, p.product_name, p.category,
       COUNT(*)                              AS branches_affected,
       SUM(ip.stock_quantity)                AS units_on_hand,
       ROUND(SUM(ip.avg_weekly_units_12w), 2) AS weekly_units_sold_12w,
       ROUND(SUM(ip.stock_quantity) / NULLIF(SUM(ip.avg_weekly_units_12w), 0), 1) AS chain_weeks_of_cover,
       ROUND(SUM(ip.stock_value_at_cost), 0) AS stock_value_kes
FROM retail.v_inventory_position ip JOIN retail.products p USING (product_id)
WHERE ip.stock_status IN ('Slow-moving (>26 wks cover)', 'No sales in 12 weeks')
GROUP BY ip.product_id, p.product_name, p.category
ORDER BY stock_value_kes DESC
LIMIT 25;

-- @query q24_stockout_rate_by_branch
-- Question 16: which branches have stockout problems? Share of branch-product-weeks closing at zero.
SELECT i.branch_id, b.branch_name, b.county,
       COUNT(*)                                                    AS branch_product_weeks,
       SUM(i.is_stockout::int)                                     AS stockout_weeks,
       ROUND(100.0 * AVG(i.is_stockout::int), 2)                   AS stockout_rate_pct,
       ROUND(100.0 * AVG(i.is_stockout::int) FILTER (WHERE i.snapshot_date > DATE '2026-08-02'), 2) AS stockout_rate_last_13w_pct,
       RANK() OVER (ORDER BY AVG(i.is_stockout::int) DESC)         AS worst_rank
FROM retail.v_inventory_weekly i JOIN retail.branches b USING (branch_id)
GROUP BY i.branch_id, b.branch_name, b.county
ORDER BY stockout_rate_pct DESC;

-- @query q25_stockout_by_category
-- Question 16 (cont.): which categories run out most, chain-wide?
SELECT category,
       ROUND(100.0 * AVG(is_stockout::int), 2) AS stockout_rate_pct,
       SUM(is_stockout::int)                    AS stockout_weeks
FROM retail.v_inventory_weekly
GROUP BY category
ORDER BY stockout_rate_pct DESC;

-- @query q26_replenishment_watchlist
-- Question 17: which branch-product pairs need replenishment attention now?
-- Rule: at least 3 stockout weeks in the last 12, ranked by the gross profit the product earns per selling week.
WITH recent AS (
    SELECT branch_id, product_id,
           SUM(is_stockout::int) AS stockout_weeks_12w,
           SUM(units_sold_in_week) FILTER (WHERE NOT is_stockout) AS units_in_selling_weeks,
           COUNT(*) FILTER (WHERE NOT is_stockout) AS selling_weeks
    FROM retail.v_inventory_weekly
    WHERE snapshot_date > (SELECT MAX(snapshot_date) FROM retail.inventory_snapshots) - INTERVAL '12 weeks'
    GROUP BY branch_id, product_id
), gp AS (
    SELECT branch_id, product_id, SUM(gross_profit) / NULLIF(SUM(quantity), 0) AS gp_per_unit
    FROM retail.v_sales_lines GROUP BY branch_id, product_id
)
SELECT r.branch_id, r.product_id, p.product_name, p.category, r.stockout_weeks_12w,
       ip.stock_quantity AS latest_stock, ip.reorder_level,
       ROUND(r.units_in_selling_weeks / NULLIF(r.selling_weeks, 0), 1) AS weekly_units_when_in_stock,
       ROUND(g.gp_per_unit * r.units_in_selling_weeks / NULLIF(r.selling_weeks, 0), 0) AS gp_per_selling_week_kes
FROM recent r
JOIN retail.products p USING (product_id)
JOIN retail.v_inventory_position ip USING (branch_id, product_id)
LEFT JOIN gp g USING (branch_id, product_id)
WHERE r.stockout_weeks_12w >= 3
ORDER BY gp_per_selling_week_kes DESC NULLS LAST
LIMIT 30;

-- @query q27_reorder_level_adequacy
-- Question 22: are reorder levels set correctly? Compares the reorder level with average weekly demand
-- in weeks with stock available. A reorder level below one week of demand cannot protect the shelf
-- when deliveries take a week or more.
WITH d AS (
    SELECT branch_id, product_id, MAX(reorder_level) AS reorder_level,
           AVG(units_sold_in_week) FILTER (WHERE NOT is_stockout) AS weekly_demand,
           AVG(is_stockout::int) AS stockout_rate
    FROM retail.v_inventory_weekly GROUP BY branch_id, product_id
)
SELECT branch_id,
       CASE WHEN reorder_level < 0.75 * weekly_demand THEN 'Reorder level < 0.75 wk demand'
            WHEN reorder_level < 1.25 * weekly_demand THEN '0.75-1.25 wk'
            ELSE '>= 1.25 wk demand' END AS reorder_cover_band,
       COUNT(*) AS branch_product_pairs,
       ROUND(100 * AVG(stockout_rate), 2) AS avg_stockout_rate_pct
FROM d WHERE weekly_demand > 0
GROUP BY 1, 2
ORDER BY 1, 2;

-- @query q28_lost_sales_estimate
-- Question 22: what do stockouts cost? Estimate = stockout weeks x the gross profit that pair earns in a
-- normal in-stock week. It is an approximation: demand while empty is unobservable.
WITH pair AS (
    SELECT i.branch_id, i.product_id,
           SUM(i.is_stockout::int) AS stockout_weeks,
           AVG(i.units_sold_in_week) FILTER (WHERE NOT i.is_stockout) AS weekly_units_in_stock
    FROM retail.v_inventory_weekly i GROUP BY i.branch_id, i.product_id
), unit_gp AS (
    SELECT branch_id, product_id, SUM(gross_profit) / NULLIF(SUM(quantity), 0) AS gp_per_unit,
           SUM(net_revenue) / NULLIF(SUM(quantity), 0) AS rev_per_unit
    FROM retail.v_sales_lines GROUP BY branch_id, product_id
)
SELECT p.branch_id, b.branch_name,
       SUM(p.stockout_weeks) AS stockout_weeks,
       ROUND(SUM(p.stockout_weeks * p.weekly_units_in_stock * u.rev_per_unit), 0) AS est_lost_revenue_kes,
       ROUND(SUM(p.stockout_weeks * p.weekly_units_in_stock * u.gp_per_unit), 0)  AS est_lost_gross_profit_kes
FROM pair p JOIN unit_gp u USING (branch_id, product_id) JOIN retail.branches b USING (branch_id)
GROUP BY p.branch_id, b.branch_name
ORDER BY est_lost_gross_profit_kes DESC;
