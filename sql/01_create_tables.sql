-- 01_create_tables.sql
-- Two layers:
--   staging : raw CSVs loaded as TEXT, with no constraints, so that bad rows can be loaded and investigated
--   retail  : the cleaned, typed and constrained model that analysis and Power BI use
-- Re-runnable: drops and recreates both schemas.

DROP SCHEMA IF EXISTS staging CASCADE;
DROP SCHEMA IF EXISTS retail CASCADE;
CREATE SCHEMA staging;
CREATE SCHEMA retail;

-- ------------------------------------------------------------------
-- STAGING (everything TEXT: we want the load to succeed even with bad values)
-- ------------------------------------------------------------------
CREATE TABLE staging.branches (branch_id TEXT, branch_name TEXT, county TEXT, town TEXT, branch_type TEXT, opening_date TEXT);
CREATE TABLE staging.products (product_id TEXT, product_name TEXT, category TEXT, brand TEXT, unit_cost TEXT);
CREATE TABLE staging.customers (customer_id TEXT, customer_segment TEXT, registration_date TEXT, county TEXT);
CREATE TABLE staging.transactions (transaction_id TEXT, transaction_ts TEXT, branch_id TEXT, customer_id TEXT, payment_method TEXT);
CREATE TABLE staging.transaction_items (transaction_item_id TEXT, transaction_id TEXT, product_id TEXT, quantity TEXT,
                                        unit_price TEXT, discount_amount TEXT, promotion_id TEXT);
CREATE TABLE staging.inventory (inventory_id TEXT, product_id TEXT, branch_id TEXT, snapshot_date TEXT,
                                stock_quantity TEXT, reorder_level TEXT);
CREATE TABLE staging.promotions (promotion_id TEXT, product_id TEXT, start_date TEXT, end_date TEXT, discount_percentage TEXT);

-- ------------------------------------------------------------------
-- RETAIL (clean model)
-- ------------------------------------------------------------------
CREATE TABLE retail.branches (
    branch_id     VARCHAR(4)   PRIMARY KEY,
    branch_name   VARCHAR(60)  NOT NULL UNIQUE,
    county        VARCHAR(40)  NOT NULL,
    town          VARCHAR(40)  NOT NULL,
    branch_type   VARCHAR(20)  NOT NULL CHECK (branch_type IN ('Hypermarket', 'Supermarket', 'Express')),
    opening_date  DATE         NOT NULL
);

CREATE TABLE retail.products (
    product_id         VARCHAR(5)    PRIMARY KEY,
    product_name       VARCHAR(80)   NOT NULL,
    category           VARCHAR(40)   NOT NULL,
    brand              VARCHAR(40)   NOT NULL,           -- 'Unknown' where source was blank
    unit_cost          NUMERIC(10,2) NOT NULL CHECK (unit_cost > 0),  -- standard cost, KES
    unit_cost_imputed  BOOLEAN       NOT NULL DEFAULT FALSE
);

CREATE TABLE retail.customers (
    customer_id        VARCHAR(6)   PRIMARY KEY,
    customer_segment   VARCHAR(30)  NOT NULL,
    registration_date  DATE,                              -- NULL where source held a placeholder
    county             VARCHAR(40)                        -- NULL where unknown
);

CREATE TABLE retail.promotions (
    promotion_id         VARCHAR(5)   PRIMARY KEY,
    product_id           VARCHAR(5)   NOT NULL REFERENCES retail.products(product_id),
    start_date           DATE         NOT NULL,
    end_date             DATE         NOT NULL,
    discount_percentage  NUMERIC(5,2) NOT NULL CHECK (discount_percentage > 0 AND discount_percentage < 100),
    CHECK (end_date >= start_date)
);

CREATE TABLE retail.transactions (
    transaction_id   VARCHAR(8)   PRIMARY KEY,
    transaction_ts   TIMESTAMP    NOT NULL,
    branch_id        VARCHAR(4)   NOT NULL REFERENCES retail.branches(branch_id),
    customer_id      VARCHAR(6)   REFERENCES retail.customers(customer_id),   -- NULL = anonymous basket
    payment_method   VARCHAR(20)  NOT NULL
);

CREATE TABLE retail.transaction_items (
    transaction_item_id  BIGINT        PRIMARY KEY,
    transaction_id       VARCHAR(8)    NOT NULL REFERENCES retail.transactions(transaction_id),
    product_id           VARCHAR(5)    NOT NULL REFERENCES retail.products(product_id),
    quantity             INTEGER       NOT NULL CHECK (quantity > 0),
    unit_price           NUMERIC(10,2) NOT NULL CHECK (unit_price > 0),       -- shelf price, KES, VAT-exclusive (assumption)
    discount_amount      NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    promotion_id         VARCHAR(5)    REFERENCES retail.promotions(promotion_id),
    price_imputed        BOOLEAN       NOT NULL DEFAULT FALSE,
    CHECK (discount_amount <= quantity * unit_price)
);

-- Negative-quantity lines in the POS export are customer returns, not sales.
CREATE TABLE retail.returns (
    return_line_id     BIGINT        PRIMARY KEY,          -- original transaction_item_id
    transaction_id     VARCHAR(8)    NOT NULL REFERENCES retail.transactions(transaction_id),
    product_id         VARCHAR(5)    NOT NULL REFERENCES retail.products(product_id),
    quantity_returned  INTEGER       NOT NULL CHECK (quantity_returned > 0),
    unit_price         NUMERIC(10,2) NOT NULL,
    refund_value       NUMERIC(12,2) NOT NULL
);

CREATE TABLE retail.inventory_snapshots (
    inventory_id     BIGINT      PRIMARY KEY,
    product_id       VARCHAR(5)  NOT NULL REFERENCES retail.products(product_id),
    branch_id        VARCHAR(4)  NOT NULL REFERENCES retail.branches(branch_id),
    snapshot_date    DATE        NOT NULL,                 -- Sunday closing-stock count
    stock_quantity   INTEGER     NOT NULL CHECK (stock_quantity >= 0),
    reorder_level    INTEGER     NOT NULL CHECK (reorder_level >= 0),
    UNIQUE (product_id, branch_id, snapshot_date)
);

-- Every record that the cleaning step changed, excluded or quarantined, with the reason.
CREATE TABLE retail.dq_exceptions (
    exception_id  BIGSERIAL    PRIMARY KEY,
    source_table  VARCHAR(40)  NOT NULL,
    record_key    VARCHAR(40)  NOT NULL,
    issue         VARCHAR(80)  NOT NULL,
    action_taken  VARCHAR(80)  NOT NULL,
    logged_at     TIMESTAMP    NOT NULL DEFAULT now()
);

-- Indexes that support the joins and date filters used in the analysis
CREATE INDEX ix_tx_branch_ts   ON retail.transactions (branch_id, transaction_ts);
CREATE INDEX ix_tx_customer    ON retail.transactions (customer_id);
CREATE INDEX ix_items_tx       ON retail.transaction_items (transaction_id);
CREATE INDEX ix_items_product  ON retail.transaction_items (product_id);
CREATE INDEX ix_inv_branch_date ON retail.inventory_snapshots (branch_id, snapshot_date);
