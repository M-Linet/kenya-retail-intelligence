"""End-to-end build: raw CSV -> staging -> cleaning -> retail model -> views.

Usage (from the project root):
    python -m src.generate_data          # 1. create synthetic raw data
    python -m src.pipeline               # 2. build the PostgreSQL database
    python -m src.run_sql                # 3. execute the SQL analysis library
"""
from __future__ import annotations

import json
import time

import pandas as pd
import psycopg2
from sqlalchemy import text

from src import data_cleaning as dc
from src.data_loader import (PROJECT_ROOT, SQL_DIR, copy_dataframe, get_engine,
                             load_raw_to_staging, read_table, run_sql_file)


def create_database() -> None:
    admin = get_engine("postgres")
    url = admin.url
    conn = psycopg2.connect(host=url.host, port=url.port, user=url.username,
                            password=url.password or None, dbname="postgres")
    conn.autocommit = True  # DROP/CREATE DATABASE cannot run inside a transaction
    with conn.cursor() as cur:
        for stmt in (SQL_DIR / "00_create_database.sql").read_text().split(";"):
            body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if body:
                cur.execute(body)
    conn.close()


def build() -> dict:
    t0 = time.time()
    create_database()
    eng = get_engine()
    run_sql_file(eng, SQL_DIR / "01_create_tables.sql")
    staged = load_raw_to_staging(eng)

    raw = {t: read_table(eng, f"staging.{t}") for t in staged}
    exc: list = []

    branches, e = dc.clean_branches(raw["branches"]); exc += e
    products, e = dc.clean_products(raw["products"], raw["transaction_items"]); exc += e
    customers, e = dc.clean_customers(raw["customers"]); exc += e
    promotions, e = dc.clean_promotions(raw["promotions"]); exc += e
    tx, tx_q, e = dc.clean_transactions(raw["transactions"], set(branches["branch_id"]), set(customers["customer_id"])); exc += e
    items, returns, items_q, e = dc.clean_items(raw["transaction_items"], tx, customers,
                                                set(products["product_id"]), set(promotions["promotion_id"])); exc += e
    inv, e = dc.clean_inventory(raw["inventory"], set(products["product_id"]), set(branches["branch_id"])); exc += e

    # Load in foreign-key order
    copy_dataframe(eng, branches, "retail.branches")
    copy_dataframe(eng, products, "retail.products")
    copy_dataframe(eng, customers, "retail.customers")
    copy_dataframe(eng, promotions, "retail.promotions")
    copy_dataframe(eng, tx, "retail.transactions",
                   ["transaction_id", "transaction_ts", "branch_id", "customer_id", "payment_method"])
    copy_dataframe(eng, items, "retail.transaction_items",
                   ["transaction_item_id", "transaction_id", "product_id", "quantity", "unit_price",
                    "discount_amount", "promotion_id", "price_imputed"])
    copy_dataframe(eng, returns, "retail.returns",
                   ["return_line_id", "transaction_id", "product_id", "quantity_returned", "unit_price", "refund_value"])
    copy_dataframe(eng, inv, "retail.inventory_snapshots")
    exc_df = pd.DataFrame(exc, columns=["source_table", "record_key", "issue", "action_taken"])
    copy_dataframe(eng, exc_df, "retail.dq_exceptions")

    run_sql_file(eng, SQL_DIR / "03_views.sql")

    with eng.connect() as c:
        c.execute(text("ANALYZE"))
    summary = {
        "staged_rows": staged,
        "clean_rows": {"branches": len(branches), "products": len(products), "customers": len(customers),
                       "promotions": len(promotions), "transactions": len(tx), "transaction_items": len(items),
                       "returns": len(returns), "inventory_snapshots": len(inv)},
        "quarantined": {"transactions": len(tx_q), "transaction_items": len(items_q)},
        "exceptions_by_issue": exc_df.groupby(["source_table", "issue"]).size().rename("n").reset_index().to_dict("records"),
        "seconds": round(time.time() - t0, 1),
    }
    out = PROJECT_ROOT / "data" / "processed" / "build_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    s = build()
    print(json.dumps({k: v for k, v in s.items() if k != "exceptions_by_issue"}, indent=2))
    for r in s["exceptions_by_issue"]:
        print(f"  {r['source_table']:<18} {r['issue']:<55} {r['n']:>6}")
