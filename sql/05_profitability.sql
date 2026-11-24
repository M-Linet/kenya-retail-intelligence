-- 05_profitability.sql
-- Business questions 9-13 (profitability). Margin is always SUM(gross_profit) / SUM(net_revenue);
-- an average of line-level margins would give a KES 30 sukuma wiki the same weight as a KES 1,300 diaper pack.

-- @query q12_top_products_gross_profit
-- Question 9: Which products generate the highest gross profit?
WITH p AS (
    SELECT v.product_id, SUM(v.net_revenue) AS revenue, SUM(v.gross_profit) AS gp, SUM(v.quantity) AS units
    FROM retail.v_sales_lines v GROUP BY v.product_id
)
SELECT RANK() OVER (ORDER BY p.gp DESC) AS gp_rank,
       p.product_id, pr.product_name, pr.category,
       ROUND(p.revenue, 0) AS revenue_kes, ROUND(p.gp, 0) AS gross_profit_kes,
       ROUND(100 * p.gp / p.revenue, 2) AS gross_margin_pct, p.units,
       ROUND(100 * SUM(p.gp) OVER (ORDER BY p.gp DESC) / SUM(p.gp) OVER (), 2) AS cumulative_gp_share_pct
FROM p JOIN retail.products pr USING (product_id)
ORDER BY gp_rank
LIMIT 20;

-- @query q13_high_revenue_low_margin
-- Question 10: Which products generate high revenue but low margins?
-- Definition: top quartile of product revenue (NTILE(4) = 1) AND gross margin below the chain margin.
WITH p AS (
    SELECT product_id, SUM(net_revenue) AS revenue, SUM(gross_profit) AS gp, SUM(discount_amount) AS discounts,
           SUM(gross_sales) AS gross_sales
    FROM retail.v_sales_lines GROUP BY product_id
), chain AS (
    SELECT SUM(gp) / SUM(revenue) AS chain_margin FROM p
), q AS (
    SELECT p.*, NTILE(4) OVER (ORDER BY revenue DESC) AS revenue_quartile FROM p
)
SELECT q.product_id, pr.product_name, pr.category,
       ROUND(q.revenue, 0) AS revenue_kes, ROUND(q.gp, 0) AS gross_profit_kes,
       ROUND(100 * q.gp / q.revenue, 2) AS gross_margin_pct,
       ROUND(100 * c.chain_margin, 2) AS chain_margin_pct,
       ROUND(100 * q.discounts / q.gross_sales, 2) AS discount_rate_pct
FROM q CROSS JOIN chain c JOIN retail.products pr USING (product_id)
WHERE q.revenue_quartile = 1 AND q.gp / q.revenue < c.chain_margin
ORDER BY q.revenue DESC;

-- @query q14_top5_products_per_branch
-- Which five products earn the most gross profit in each branch? ROW_NUMBER() partitioned by branch.
WITH bp AS (
    SELECT branch_id, product_id, SUM(gross_profit) AS gp, SUM(net_revenue) AS revenue
    FROM retail.v_sales_lines GROUP BY branch_id, product_id
), ranked AS (
    SELECT bp.*, ROW_NUMBER() OVER (PARTITION BY branch_id ORDER BY gp DESC) AS rn FROM bp
)
SELECT r.branch_id, b.branch_name, r.rn AS rank_in_branch, r.product_id, p.product_name, p.category,
       ROUND(r.gp, 0) AS gross_profit_kes, ROUND(r.revenue, 0) AS revenue_kes
FROM ranked r JOIN retail.branches b USING (branch_id) JOIN retail.products p USING (product_id)
WHERE r.rn <= 5
ORDER BY r.branch_id, r.rn;

-- @query q15_category_performance
-- Question 13: Which categories are underperforming? Margin, profit share vs revenue share, and Year-2 growth.
WITH c AS (
    SELECT category,
           SUM(net_revenue) AS revenue, SUM(gross_profit) AS gp, SUM(discount_amount) AS discounts, SUM(gross_sales) AS gross_sales,
           SUM(net_revenue)  FILTER (WHERE sale_date <  DATE '2025-11-01' AND branch_id <> 'BR10') AS y1_lfl,
           SUM(net_revenue)  FILTER (WHERE sale_date >= DATE '2025-11-01' AND branch_id <> 'BR10') AS y2_lfl,
           SUM(gross_profit) FILTER (WHERE sale_date <  DATE '2025-11-01' AND branch_id <> 'BR10') AS gp_y1_lfl,
           SUM(gross_profit) FILTER (WHERE sale_date >= DATE '2025-11-01' AND branch_id <> 'BR10') AS gp_y2_lfl
    FROM retail.v_sales_lines GROUP BY category
)
SELECT category,
       ROUND(revenue, 0) AS revenue_kes,
       ROUND(100 * gp / revenue, 2) AS gross_margin_pct,
       ROUND(100 * revenue / SUM(revenue) OVER (), 2) AS revenue_share_pct,
       ROUND(100 * gp / SUM(gp) OVER (), 2) AS gp_share_pct,
       ROUND(100 * discounts / gross_sales, 2) AS discount_rate_pct,
       ROUND(100 * (y2_lfl / y1_lfl - 1), 2) AS lfl_revenue_growth_pct,
       ROUND(100 * (gp_y2_lfl / gp_y1_lfl - 1), 2) AS lfl_gp_growth_pct,
       CASE WHEN gp / SUM(gp) OVER () < revenue / SUM(revenue) OVER () THEN 'Dilutes margin' ELSE 'Accretive' END AS margin_role
FROM c
ORDER BY lfl_gp_growth_pct;

-- @query q16_branch_margin_drivers
-- Questions 11 and 19: Why do branch margins differ? Separates price-before-discount margin (product mix)
-- from discount leakage, split into promotional and non-promotional discounts.
SELECT v.branch_id, b.branch_name,
       ROUND(100 * (SUM(v.gross_sales) - SUM(v.cogs)) / SUM(v.gross_sales), 2)                           AS margin_before_discounts_pct,
       ROUND(100 * SUM(v.discount_amount) FILTER (WHERE v.price_type = 'Promotion') / SUM(v.gross_sales), 2) AS promo_discount_pct_of_sales,
       ROUND(100 * SUM(v.discount_amount) FILTER (WHERE v.price_type = 'Non-promotional discount') / SUM(v.gross_sales), 2) AS non_promo_discount_pct_of_sales,
       ROUND(100 * SUM(v.gross_profit) / SUM(v.net_revenue), 2)                                         AS gross_margin_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE v.price_type = 'Non-promotional discount') / COUNT(*), 2)    AS pct_lines_non_promo_discounted,
       ROUND(SUM(v.discount_amount) FILTER (WHERE v.price_type = 'Non-promotional discount'), 0)        AS non_promo_discount_kes
FROM retail.v_sales_lines v JOIN retail.branches b USING (branch_id)
GROUP BY v.branch_id, b.branch_name
ORDER BY non_promo_discount_pct_of_sales DESC;

-- @query q17_non_promo_discount_by_category_branch
-- Diagnostic: in which categories do non-promotional discounts occur? Perishable markdowns are expected
-- (Fresh Produce, Bakery, Dairy); discounts on ambient categories point to manual price overrides.
SELECT v.branch_id,
       ROUND(100 * COALESCE(SUM(v.discount_amount) FILTER (WHERE v.price_type = 'Non-promotional discount'
                    AND v.category IN ('Fresh Produce', 'Bakery', 'Dairy')), 0) / SUM(v.gross_sales), 2) AS perishable_markdown_pct,
       ROUND(100 * COALESCE(SUM(v.discount_amount) FILTER (WHERE v.price_type = 'Non-promotional discount'
                    AND v.category NOT IN ('Fresh Produce', 'Bakery', 'Dairy')), 0) / SUM(v.gross_sales), 2) AS ambient_override_pct
FROM retail.v_sales_lines v
GROUP BY v.branch_id
ORDER BY ambient_override_pct DESC;
