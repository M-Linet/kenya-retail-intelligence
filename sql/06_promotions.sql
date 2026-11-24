-- 06_promotions.sql
-- Questions 12 and 21: How do promotions influence profitability, and where should promotional spend go?
--
-- Method (chain-level, per promotion):
--   baseline = average daily units and gross profit of the same product over the 28 days before the
--              promotion, counting full-price days only (lines with no promotion_id)
--   uplift   = promo units/day / baseline units/day - 1
--   incremental GP = (promo GP/day - baseline GP/day) x promotion days
-- Limitations: this does not capture cannibalisation of substitute products, pantry loading (a dip after
-- the promotion), or extra footfall. It is a first-pass screen, not a causal estimate.

-- @query q18_promotion_performance
WITH daily AS (
    SELECT product_id, sale_date, promotion_id,
           SUM(quantity) AS units, SUM(gross_profit) AS gp, SUM(discount_amount) AS discount
    FROM retail.v_sales_lines
    GROUP BY product_id, sale_date, promotion_id
), promo AS (
    SELECT pr.promotion_id, pr.product_id, pr.start_date, pr.end_date, pr.discount_percentage,
           (pr.end_date - pr.start_date + 1) AS days,
           SUM(d.units)    AS promo_units,
           SUM(d.gp)       AS promo_gp,
           SUM(d.discount) AS promo_discount
    FROM retail.promotions pr
    LEFT JOIN daily d ON d.promotion_id = pr.promotion_id
    GROUP BY pr.promotion_id, pr.product_id, pr.start_date, pr.end_date, pr.discount_percentage
), base AS (
    SELECT pr.promotion_id,
           COALESCE(SUM(d.units), 0) / 28.0 AS base_units_per_day,
           COALESCE(SUM(d.gp), 0)    / 28.0 AS base_gp_per_day
    FROM retail.promotions pr
    LEFT JOIN daily d ON d.product_id = pr.product_id
                     AND d.promotion_id IS NULL
                     AND d.sale_date BETWEEN pr.start_date - 28 AND pr.start_date - 1
    GROUP BY pr.promotion_id
)
SELECT p.promotion_id, p.product_id, prd.product_name, prd.category, p.start_date, p.days, p.discount_percentage,
       ROUND(b.base_units_per_day, 2)                                   AS baseline_units_per_day,
       ROUND(p.promo_units / p.days::numeric, 2)                        AS promo_units_per_day,
       ROUND(100 * (p.promo_units / p.days::numeric / NULLIF(b.base_units_per_day, 0) - 1), 1) AS unit_uplift_pct,
       ROUND(p.promo_discount, 0)                                       AS discount_cost_kes,
       ROUND(p.promo_gp - b.base_gp_per_day * p.days, 0)                AS incremental_gp_kes,
       CASE WHEN p.promo_gp - b.base_gp_per_day * p.days > 0 THEN 'GP-positive' ELSE 'GP-negative' END AS outcome
FROM promo p JOIN base b USING (promotion_id) JOIN retail.products prd ON prd.product_id = p.product_id
WHERE p.start_date >= DATE '2024-11-29'      -- needs a full 28-day baseline inside the data
ORDER BY incremental_gp_kes;

-- @query q19_promotion_summary_by_category
-- Roll-up of q18 by category and discount depth: which kinds of promotion pay back?
WITH daily AS (
    SELECT product_id, sale_date, promotion_id, SUM(quantity) AS units, SUM(gross_profit) AS gp, SUM(discount_amount) AS discount
    FROM retail.v_sales_lines GROUP BY product_id, sale_date, promotion_id
), promo AS (
    SELECT pr.promotion_id, pr.product_id, pr.start_date, pr.discount_percentage, (pr.end_date - pr.start_date + 1) AS days,
           SUM(d.units) AS units, SUM(d.gp) AS gp, SUM(d.discount) AS discount
    FROM retail.promotions pr LEFT JOIN daily d ON d.promotion_id = pr.promotion_id
    GROUP BY pr.promotion_id, pr.product_id, pr.start_date, pr.end_date, pr.discount_percentage
), base AS (
    SELECT pr.promotion_id, COALESCE(SUM(d.units), 0) / 28.0 AS bu, COALESCE(SUM(d.gp), 0) / 28.0 AS bg
    FROM retail.promotions pr LEFT JOIN daily d ON d.product_id = pr.product_id AND d.promotion_id IS NULL
         AND d.sale_date BETWEEN pr.start_date - 28 AND pr.start_date - 1
    GROUP BY pr.promotion_id
), r AS (
    SELECT prd.category, p.discount_percentage, p.days, p.units, p.gp, p.discount, b.bu, b.bg
    FROM promo p JOIN base b USING (promotion_id) JOIN retail.products prd USING (product_id)
    WHERE p.start_date >= DATE '2024-11-29'
)
SELECT category,
       COUNT(*)                                                    AS promotions,
       ROUND(AVG(discount_percentage), 1)                          AS avg_discount_pct,
       ROUND(100 * (SUM(units) / NULLIF(SUM(bu * days), 0) - 1), 1) AS unit_uplift_pct,
       ROUND(SUM(discount), 0)                                     AS discount_cost_kes,
       ROUND(SUM(gp - bg * days), 0)                               AS incremental_gp_kes,
       ROUND(SUM(gp - bg * days) / NULLIF(SUM(discount), 0), 2)    AS incremental_gp_per_kes_discount,
       COUNT(*) FILTER (WHERE gp - bg * days > 0)                  AS gp_positive_promotions
FROM r
GROUP BY category
ORDER BY incremental_gp_per_kes_discount DESC NULLS LAST;
