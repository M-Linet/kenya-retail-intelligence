"""Export the Power BI star schema to CSV, and write the KPI reconciliation sheet.

Power BI can connect straight to PostgreSQL (Get Data > PostgreSQL database) and import the
`powerbi` schema views created below. The CSV export is for anyone who would rather not install the
Npgsql connector, and it makes the model reproducible from files.

    python -m src.export_powerbi
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from src.data_loader import PROJECT_ROOT, get_engine, query

OUT = PROJECT_ROOT / "data" / "processed" / "powerbi"

VIEWS = {
    "dim_date": "SELECT * FROM retail.v_dim_date",
    "dim_branch": """SELECT branch_id, branch_name, REPLACE(branch_name, 'Savanna Fresh ', '') AS branch_short,
                     county, town, branch_type, opening_date, (opening_date <= DATE '2024-11-01') AS is_like_for_like
                     FROM retail.branches""",
    "dim_product": """SELECT product_id, product_name, category, brand, unit_cost, unit_cost_imputed,
                      CASE WHEN category IN ('Fresh Produce','Bakery','Dairy','Meat & Poultry') THEN 'Fresh' ELSE 'Ambient' END AS product_group
                      FROM retail.products""",
    "dim_customer": """SELECT customer_id AS customer_key, customer_segment, registration_date, COALESCE(county, 'Unknown') AS county
                       FROM retail.customers
                       UNION ALL SELECT 'ANON', 'Anonymous (no loyalty card)', NULL, 'Unknown'""",
    "dim_promotion": """SELECT promotion_id, product_id, start_date, end_date, discount_percentage FROM retail.promotions""",
    "fact_sales": """SELECT transaction_item_id, transaction_id, sale_date, EXTRACT(HOUR FROM transaction_ts)::int AS sale_hour,
                     branch_id, product_id, COALESCE(customer_id, 'ANON') AS customer_key, payment_method, promotion_id, price_type,
                     quantity, gross_sales, discount_amount, net_revenue, cogs, gross_profit
                     FROM retail.v_sales_lines""",
    "fact_inventory": """SELECT inventory_id, snapshot_date, branch_id, product_id, stock_quantity, reorder_level,
                         stock_value_at_cost, units_sold_in_week, is_stockout, at_or_below_reorder
                         FROM retail.v_inventory_weekly""",
    "fact_inventory_position": """SELECT branch_id, product_id, snapshot_date, stock_quantity, reorder_level, stock_value_at_cost,
                                  avg_weekly_units_12w, stockout_weeks_12w, weeks_of_cover, stock_status
                                  FROM retail.v_inventory_position""",
}


def create_powerbi_schema(engine) -> None:
    """Also expose the same tables as views in a `powerbi` schema, for a direct PostgreSQL connection."""
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS powerbi CASCADE; CREATE SCHEMA powerbi;"))
        for name, sql in VIEWS.items():
            c.execute(text(f"CREATE VIEW powerbi.{name} AS {sql}"))


def export_csv(engine) -> dict[str, int]:
    OUT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in VIEWS:
        df = query(engine, f"SELECT * FROM powerbi.{name}")
        df.to_csv(OUT / f"{name}.csv", index=False)
        counts[name] = len(df)
    # Promotion results are computed in SQL (baseline logic), then imported as their own table
    promo = pd.read_csv(PROJECT_ROOT / "reports" / "sql_outputs" / "q18_promotion_performance.csv")
    promo.to_csv(OUT / "promo_performance.csv", index=False)
    counts["promo_performance"] = len(promo)
    return counts


RECON_SQL = """
SELECT :scope AS scope,
       ROUND(SUM(net_revenue), 0) AS revenue, ROUND(SUM(gross_profit), 0) AS gross_profit,
       ROUND(100 * SUM(gross_profit) / SUM(net_revenue), 2) AS gross_margin_pct,
       SUM(quantity) AS units, COUNT(DISTINCT transaction_id) AS transactions,
       ROUND(SUM(net_revenue) / COUNT(DISTINCT transaction_id), 2) AS atv,
       ROUND(100 * SUM(discount_amount) / SUM(gross_sales), 2) AS discount_rate_pct
FROM retail.v_sales_lines v JOIN retail.products p USING (product_id)
WHERE {where}
"""
SCOPES = {
    "No filters": "TRUE",
    "Branch = Nyali (BR04)": "v.branch_id = 'BR04'",
    "Year 2 (Nov 2025 - Oct 2026)": "v.sale_date >= DATE '2025-11-01'",
    "Category = Staples": "p.category = 'Staples'",
    "Kisumu, Dairy, 2026": "v.branch_id = 'BR06' AND p.category = 'Dairy' AND v.sale_date >= DATE '2026-01-01'",
}


def write_reconciliation(engine) -> pd.DataFrame:
    rows = [query(engine, RECON_SQL.format(where=w), scope=s) for s, w in SCOPES.items()]
    rec = pd.concat(rows, ignore_index=True)
    inv = query(engine, """SELECT ROUND(100.0 * AVG(is_stockout::int), 2) AS stockout_rate_pct,
                           (SELECT ROUND(SUM(stock_value_at_cost), 0) FROM retail.v_inventory_position) AS latest_stock_value
                           FROM retail.v_inventory_weekly""")
    rec.loc[0, "stockout_rate_pct"] = inv.iloc[0, 0]
    rec.loc[0, "latest_stock_value"] = inv.iloc[0, 1]
    path = PROJECT_ROOT / "powerbi" / "kpi_reconciliation.csv"
    rec.to_csv(path, index=False)
    return rec


if __name__ == "__main__":
    eng = get_engine()
    create_powerbi_schema(eng)
    print(export_csv(eng))
    print(write_reconciliation(eng).to_string(index=False))
