-- 03_views.sql
-- Semantic layer: one place where business definitions live. The SQL analysis files, the
-- Python notebooks and Power BI all read these views, so "revenue" means the same thing everywhere.
--
-- Definitions (all amounts KES; shelf prices treated as VAT-exclusive, which is a documented assumption):
--   gross_sales  = quantity * unit_price
--   net_revenue  = gross_sales - discount_amount          <- "Revenue" in every report
--   cogs         = quantity * unit_cost (standard cost)
--   gross_profit = net_revenue - cogs
--   gross_margin = gross_profit / net_revenue (calculated at aggregate level, never averaged)

DROP VIEW IF EXISTS retail.v_sales_lines CASCADE;
CREATE VIEW retail.v_sales_lines AS
SELECT
    ti.transaction_item_id,
    ti.transaction_id,
    t.transaction_ts,
    t.transaction_ts::date                              AS sale_date,
    date_trunc('month', t.transaction_ts)::date         AS sale_month,
    date_trunc('week',  t.transaction_ts)::date         AS sale_week,     -- Monday
    t.branch_id,
    t.customer_id,
    t.payment_method,
    ti.product_id,
    p.category,
    p.brand,
    ti.quantity,
    ti.unit_price,
    p.unit_cost,
    ti.quantity * ti.unit_price                         AS gross_sales,
    ti.discount_amount,
    ti.quantity * ti.unit_price - ti.discount_amount    AS net_revenue,
    ti.quantity * p.unit_cost                           AS cogs,
    ti.quantity * ti.unit_price - ti.discount_amount
        - ti.quantity * p.unit_cost                     AS gross_profit,
    ti.promotion_id,
    CASE
        WHEN ti.promotion_id IS NOT NULL THEN 'Promotion'
        WHEN ti.discount_amount > 0      THEN 'Non-promotional discount'
        ELSE 'Full price'
    END                                                 AS price_type
FROM retail.transaction_items ti
JOIN retail.transactions t ON t.transaction_id = ti.transaction_id
JOIN retail.products     p ON p.product_id     = ti.product_id;

-- One row per basket. Used for ATV and basket-size analysis so that line-level joins
-- never inflate transaction counts.
CREATE VIEW retail.v_baskets AS
SELECT
    transaction_id,
    MIN(transaction_ts)                  AS transaction_ts,
    MIN(branch_id)                       AS branch_id,
    MIN(customer_id)                     AS customer_id,
    MIN(payment_method)                  AS payment_method,
    COUNT(*)                             AS lines,
    SUM(quantity)                        AS units,
    SUM(net_revenue)                     AS basket_revenue,
    SUM(gross_profit)                    AS basket_gross_profit
FROM retail.v_sales_lines
GROUP BY transaction_id;

-- Calendar dimension (also exported to Power BI as dim_date)
CREATE VIEW retail.v_dim_date AS
SELECT
    d::date                                   AS date,
    EXTRACT(YEAR FROM d)::int                 AS year,
    EXTRACT(MONTH FROM d)::int                AS month_number,
    to_char(d, 'Mon')                         AS month_short,
    to_char(d, 'YYYY-MM')                     AS year_month,
    date_trunc('month', d)::date              AS month_start,
    date_trunc('week', d)::date               AS week_start,
    EXTRACT(ISODOW FROM d)::int               AS iso_dow,          -- 1 = Monday
    to_char(d, 'Dy')                          AS day_short,
    EXTRACT(ISODOW FROM d) IN (6, 7)          AS is_weekend,
    (EXTRACT(DAY FROM d) >= 25 OR EXTRACT(DAY FROM d) <= 3) AS is_payday_window
FROM generate_series(DATE '2024-11-01', DATE '2026-10-31', INTERVAL '1 day') AS g(d);

-- Weekly sales per branch-product, aligned with the Sunday stock count of the same week.
CREATE VIEW retail.v_weekly_product_sales AS
SELECT branch_id, product_id, sale_week,
       SUM(quantity)     AS units_sold,
       SUM(cogs)         AS cogs,
       SUM(net_revenue)  AS net_revenue
FROM retail.v_sales_lines
GROUP BY branch_id, product_id, sale_week;

CREATE VIEW retail.v_inventory_weekly AS
SELECT
    i.inventory_id,
    i.branch_id,
    i.product_id,
    p.category,
    i.snapshot_date,
    date_trunc('week', i.snapshot_date)::date               AS week_start,
    i.stock_quantity,
    i.reorder_level,
    i.stock_quantity * p.unit_cost                          AS stock_value_at_cost,
    COALESCE(w.units_sold, 0)                               AS units_sold_in_week,
    (i.stock_quantity = 0)                                  AS is_stockout,          -- shelf empty at week close
    (i.stock_quantity <= i.reorder_level)                   AS at_or_below_reorder
FROM retail.inventory_snapshots i
JOIN retail.products p ON p.product_id = i.product_id
LEFT JOIN retail.v_weekly_product_sales w
       ON w.branch_id = i.branch_id AND w.product_id = i.product_id
      AND w.sale_week = date_trunc('week', i.snapshot_date)::date;

-- Latest position per branch-product with demand-based cover.
-- weeks_of_cover = closing stock / average weekly units over the last 12 weeks.
CREATE VIEW retail.v_inventory_position AS
WITH latest AS (
    SELECT MAX(snapshot_date) AS d FROM retail.inventory_snapshots
), recent AS (
    SELECT v.branch_id, v.product_id,
           AVG(v.units_sold_in_week)        AS avg_weekly_units_12w,
           SUM(v.is_stockout::int)          AS stockout_weeks_12w
    FROM retail.v_inventory_weekly v, latest
    WHERE v.snapshot_date > latest.d - INTERVAL '12 weeks'
    GROUP BY v.branch_id, v.product_id
)
SELECT
    i.branch_id, i.product_id, i.category, i.snapshot_date,
    i.stock_quantity, i.reorder_level, i.stock_value_at_cost,
    r.avg_weekly_units_12w,
    r.stockout_weeks_12w,
    CASE WHEN r.avg_weekly_units_12w > 0
         THEN i.stock_quantity / r.avg_weekly_units_12w END AS weeks_of_cover,
    CASE
        WHEN r.avg_weekly_units_12w = 0 AND i.stock_quantity > 0     THEN 'No sales in 12 weeks'
        WHEN i.stock_quantity / NULLIF(r.avg_weekly_units_12w, 0) > 26 THEN 'Slow-moving (>26 wks cover)'
        WHEN i.stock_quantity / NULLIF(r.avg_weekly_units_12w, 0) > 12 THEN 'Overstocked (12-26 wks)'
        WHEN i.stock_quantity <= i.reorder_level                     THEN 'At/below reorder level'
        ELSE 'Healthy'
    END AS stock_status
FROM retail.v_inventory_weekly i
JOIN latest ON i.snapshot_date = latest.d
JOIN recent r ON r.branch_id = i.branch_id AND r.product_id = i.product_id;
