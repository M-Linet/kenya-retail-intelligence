-- 02_data_quality_checks.sql
-- Part A profiles the RAW staging layer (finds the problems).
-- Part B validates the CLEAN retail layer (proves the fixes worked). Every Part B check should return 0.
-- Each block starts with "-- @query <name>" so that src/run_sql.py can execute and save it.

-- =====================================================================
-- PART A: STAGING PROFILE
-- =====================================================================

-- @query dq_a01_row_counts
-- Purpose: compare raw row counts with distinct business keys, which reveals duplicates.
SELECT 'transactions' AS table_name, COUNT(*) AS raw_rows, COUNT(DISTINCT transaction_id) AS distinct_keys FROM staging.transactions
UNION ALL SELECT 'transaction_items', COUNT(*), COUNT(DISTINCT transaction_item_id) FROM staging.transaction_items
UNION ALL SELECT 'customers', COUNT(*), COUNT(DISTINCT customer_id) FROM staging.customers
UNION ALL SELECT 'products', COUNT(*), COUNT(DISTINCT product_id) FROM staging.products
UNION ALL SELECT 'inventory', COUNT(*), COUNT(DISTINCT inventory_id) FROM staging.inventory
UNION ALL SELECT 'promotions', COUNT(*), COUNT(DISTINCT promotion_id) FROM staging.promotions
ORDER BY table_name;

-- @query dq_a02_exact_duplicate_items
-- Purpose: are duplicate keys exact copies (safe to drop) or conflicting records (need a decision)?
WITH d AS (
    SELECT transaction_item_id, COUNT(*) AS copies,
           COUNT(DISTINCT (transaction_id, product_id, quantity, unit_price, discount_amount, promotion_id)) AS distinct_versions
    FROM staging.transaction_items
    GROUP BY transaction_item_id
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS duplicated_keys,
       SUM(copies - 1) AS extra_rows,
       SUM(CASE WHEN distinct_versions > 1 THEN 1 ELSE 0 END) AS conflicting_keys
FROM d;

-- @query dq_a03_missing_values
-- Purpose: count NULLs in the fields analysis depends on.
SELECT 'products.brand' AS field, COUNT(*) FILTER (WHERE brand IS NULL) AS missing, COUNT(*) AS total FROM staging.products
UNION ALL SELECT 'products.unit_cost', COUNT(*) FILTER (WHERE unit_cost IS NULL), COUNT(*) FROM staging.products
UNION ALL SELECT 'customers.county', COUNT(*) FILTER (WHERE county IS NULL), COUNT(*) FROM staging.customers
UNION ALL SELECT 'transactions.customer_id (anonymous)', COUNT(*) FILTER (WHERE customer_id IS NULL), COUNT(*) FROM staging.transactions
UNION ALL SELECT 'transactions.payment_method', COUNT(*) FILTER (WHERE payment_method IS NULL), COUNT(*) FROM staging.transactions;

-- @query dq_a04_category_labels
-- Purpose: reveal inconsistent category spellings before standardisation.
SELECT category, COUNT(*) AS products
FROM staging.products
GROUP BY category
ORDER BY lower(trim(category)), category;

-- @query dq_a05_payment_labels
SELECT COALESCE(payment_method, '<NULL>') AS payment_method, COUNT(*) AS transactions
FROM staging.transactions
GROUP BY 1 ORDER BY 2 DESC;

-- @query dq_a06_invalid_dates
-- Purpose: timestamps outside the extraction window (Nov 2024 - Oct 2026).
SELECT LEFT(transaction_ts, 4) AS year_text, COUNT(*) AS transactions
FROM staging.transactions
GROUP BY 1 ORDER BY 1;

-- @query dq_a07_orphan_keys
-- Purpose: foreign keys that point at nothing.
SELECT 'transactions -> branches' AS relationship, COUNT(*) AS orphan_rows
FROM staging.transactions t LEFT JOIN staging.branches b ON b.branch_id = t.branch_id WHERE b.branch_id IS NULL
UNION ALL
SELECT 'transactions -> customers', COUNT(*)
FROM staging.transactions t LEFT JOIN (SELECT DISTINCT customer_id FROM staging.customers) c ON c.customer_id = t.customer_id
WHERE t.customer_id IS NOT NULL AND c.customer_id IS NULL
UNION ALL
SELECT 'items -> products', COUNT(*)
FROM staging.transaction_items i LEFT JOIN staging.products p ON p.product_id = i.product_id WHERE p.product_id IS NULL;

-- @query dq_a08_quantity_profile
-- Purpose: separate returns, normal lines and suspicious extremes before choosing rules.
SELECT CASE
           WHEN quantity::int < 0 THEN 'a) negative (return)'
           WHEN quantity::int BETWEEN 1 AND 10 THEN 'b) 1-10'
           WHEN quantity::int BETWEEN 11 AND 60 THEN 'c) 11-60'
           WHEN quantity::int BETWEEN 61 AND 99 THEN 'd) 61-99'
           ELSE 'e) 100+'
       END AS quantity_band,
       COUNT(*) AS lines,
       MIN(quantity::int) AS min_q, MAX(quantity::int) AS max_q
FROM staging.transaction_items
GROUP BY 1 ORDER BY 1;

-- @query dq_a09_zero_or_negative_prices
SELECT COUNT(*) FILTER (WHERE unit_price::numeric = 0) AS zero_price_lines,
       COUNT(*) FILTER (WHERE unit_price::numeric < 0) AS negative_price_lines
FROM staging.transaction_items;

-- @query dq_a10_inventory_anomalies
SELECT COUNT(*) FILTER (WHERE stock_quantity::int < 0) AS negative_stock_rows,
       COUNT(*) - COUNT(DISTINCT (product_id, branch_id, snapshot_date)) AS duplicate_snapshot_rows
FROM staging.inventory;

-- @query dq_a11_promotion_date_logic
SELECT promotion_id, start_date, end_date
FROM staging.promotions
WHERE end_date::date < start_date::date;

-- =====================================================================
-- PART B: CLEAN-LAYER VALIDATION (every value should be 0)
-- =====================================================================

-- @query dq_b01_integrity_summary
SELECT 'duplicate transaction_id' AS check_name,
       (SELECT COUNT(*) - COUNT(DISTINCT transaction_id) FROM retail.transactions) AS failures
UNION ALL SELECT 'items without a transaction',
       (SELECT COUNT(*) FROM retail.transaction_items i LEFT JOIN retail.transactions t USING (transaction_id) WHERE t.transaction_id IS NULL)
UNION ALL SELECT 'transactions outside period',
       (SELECT COUNT(*) FROM retail.transactions WHERE transaction_ts < '2024-11-01' OR transaction_ts >= '2026-11-01')
UNION ALL SELECT 'transactions before branch opening',
       (SELECT COUNT(*) FROM retail.transactions t JOIN retail.branches b USING (branch_id) WHERE t.transaction_ts::date < b.opening_date)
UNION ALL SELECT 'purchases before customer registration',
       (SELECT COUNT(*) FROM retail.transactions t JOIN retail.customers c USING (customer_id) WHERE t.transaction_ts::date < c.registration_date)
UNION ALL SELECT 'non-positive quantity or price',
       (SELECT COUNT(*) FROM retail.transaction_items WHERE quantity <= 0 OR unit_price <= 0)
UNION ALL SELECT 'discount greater than line value',
       (SELECT COUNT(*) FROM retail.transaction_items WHERE discount_amount > quantity * unit_price)
UNION ALL SELECT 'promotion line outside promotion dates',
       (SELECT COUNT(*) FROM retail.transaction_items i JOIN retail.transactions t USING (transaction_id)
         JOIN retail.promotions p USING (promotion_id)
        WHERE t.transaction_ts::date NOT BETWEEN p.start_date AND p.end_date)
UNION ALL SELECT 'promotion line for a different product',
       (SELECT COUNT(*) FROM retail.transaction_items i JOIN retail.promotions p USING (promotion_id) WHERE p.product_id <> i.product_id)
UNION ALL SELECT 'inventory snapshot for unopened branch',
       (SELECT COUNT(*) FROM retail.inventory_snapshots i JOIN retail.branches b USING (branch_id)
         WHERE i.snapshot_date < b.opening_date)
UNION ALL SELECT 'non-canonical category labels',
       (SELECT COUNT(*) FROM retail.products WHERE category NOT IN ('Staples','Fresh Produce','Dairy','Bakery','Beverages',
        'Meat & Poultry','Household & Cleaning','Personal Care','Snacks & Confectionery','Baby Care'));

-- @query dq_b02_join_fanout_check
-- Purpose: prove that the sales view does not duplicate lines through its joins.
SELECT (SELECT COUNT(*) FROM retail.transaction_items) AS item_rows,
       (SELECT COUNT(*) FROM retail.v_sales_lines)     AS view_rows,
       (SELECT COUNT(*) FROM retail.transaction_items) - (SELECT COUNT(*) FROM retail.v_sales_lines) AS difference;

-- @query dq_b03_exception_log
-- Purpose: an auditable record of every change made during cleaning.
SELECT source_table, issue, action_taken, COUNT(*) AS records
FROM retail.dq_exceptions
GROUP BY source_table, issue, action_taken
ORDER BY source_table, records DESC;
