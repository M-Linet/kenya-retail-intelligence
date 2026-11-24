-- 08_management_scorecard.sql
-- Questions 19-20: one view per branch and per category that combines growth, margin, discount,
-- availability and stock-health signals, and flags where management should look first.
-- Thresholds are explicit and editable, so the flags can be explained and challenged.

-- @query q29_branch_scorecard
WITH sales AS (
    SELECT branch_id,
           SUM(net_revenue) AS revenue,
           SUM(gross_profit) / SUM(net_revenue) AS gm,
           SUM(discount_amount) FILTER (WHERE price_type = 'Non-promotional discount') / SUM(gross_sales) AS non_promo_disc,
           SUM(net_revenue) FILTER (WHERE sale_date >= DATE '2025-11-01')
             / NULLIF(SUM(net_revenue) FILTER (WHERE sale_date < DATE '2025-11-01'), 0) - 1 AS yoy
    FROM retail.v_sales_lines GROUP BY branch_id
), inv AS (
    SELECT branch_id, AVG(is_stockout::int) AS stockout_rate FROM retail.v_inventory_weekly GROUP BY branch_id
), pos AS (
    SELECT branch_id,
           SUM(stock_value_at_cost) FILTER (WHERE stock_status IN ('Slow-moving (>26 wks cover)', 'No sales in 12 weeks'))
             / SUM(stock_value_at_cost) AS slow_share
    FROM retail.v_inventory_position GROUP BY branch_id
), chain AS (
    SELECT SUM(gross_profit) / SUM(net_revenue) AS gm FROM retail.v_sales_lines
)
SELECT s.branch_id, b.branch_name, b.branch_type,
       ROUND(s.revenue, 0)                 AS revenue_kes,
       CASE WHEN b.opening_date <= DATE '2024-11-01' THEN ROUND(100 * s.yoy, 1) END AS yoy_growth_pct,  -- NULL for BR10 (no full Year 1)
       ROUND(100 * s.gm, 2)                AS gross_margin_pct,
       ROUND(100 * s.non_promo_disc, 2)    AS non_promo_discount_pct,
       ROUND(100 * i.stockout_rate, 2)     AS stockout_rate_pct,
       ROUND(100 * p.slow_share, 1)        AS slow_stock_share_pct,
       COALESCE(NULLIF(CONCAT_WS('; ',
         CASE WHEN b.opening_date <= DATE '2024-11-01' AND s.yoy < 0 THEN 'Declining sales' END,
         CASE WHEN s.gm < c.gm - 0.01 THEN 'Margin >1pt below chain' END,
         CASE WHEN s.non_promo_disc > 0.01 THEN 'High non-promo discounting' END,
         CASE WHEN i.stockout_rate > 0.10 THEN 'Stockout rate >10%' END,
         CASE WHEN p.slow_share > 0.25 THEN 'Slow stock >25% of value' END), ''), 'No flags') AS flags
FROM sales s
JOIN retail.branches b USING (branch_id)
JOIN inv i USING (branch_id)
JOIN pos p USING (branch_id)
CROSS JOIN chain c
ORDER BY (CASE WHEN b.opening_date <= DATE '2024-11-01' AND s.yoy < 0 THEN 1 ELSE 0 END
        + CASE WHEN s.gm < c.gm - 0.01 THEN 1 ELSE 0 END
        + CASE WHEN s.non_promo_disc > 0.01 THEN 1 ELSE 0 END
        + CASE WHEN i.stockout_rate > 0.10 THEN 1 ELSE 0 END
        + CASE WHEN p.slow_share > 0.25 THEN 1 ELSE 0 END) DESC, s.revenue DESC;

-- @query q30_category_scorecard
WITH s AS (
    SELECT category, SUM(net_revenue) AS revenue, SUM(gross_profit) AS gp,
           SUM(gross_profit) FILTER (WHERE sale_date >= DATE '2025-11-01' AND branch_id <> 'BR10')
             / NULLIF(SUM(gross_profit) FILTER (WHERE sale_date < DATE '2025-11-01' AND branch_id <> 'BR10'), 0) - 1 AS gp_growth
    FROM retail.v_sales_lines GROUP BY category
), i AS (
    SELECT category, AVG(is_stockout::int) AS stockout_rate FROM retail.v_inventory_weekly GROUP BY category
), p AS (
    SELECT category,
           SUM(stock_value_at_cost) FILTER (WHERE stock_status IN ('Slow-moving (>26 wks cover)', 'No sales in 12 weeks')) AS slow_value,
           SUM(stock_value_at_cost) AS stock_value
    FROM retail.v_inventory_position GROUP BY category
)
SELECT s.category,
       ROUND(100 * s.gp / SUM(s.gp) OVER (), 2) AS gp_share_pct,
       ROUND(100 * s.gp / s.revenue, 2)         AS gross_margin_pct,
       ROUND(100 * s.gp_growth, 1)              AS lfl_gp_growth_pct,
       ROUND(100 * i.stockout_rate, 2)          AS stockout_rate_pct,
       ROUND(COALESCE(p.slow_value, 0), 0)      AS slow_stock_value_kes,
       ROUND(100 * COALESCE(p.slow_value, 0) / p.stock_value, 1) AS slow_share_of_category_stock_pct
FROM s JOIN i USING (category) JOIN p USING (category)
ORDER BY gp_share_pct DESC;
