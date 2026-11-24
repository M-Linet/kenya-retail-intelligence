"""Database integrity and reconciliation tests. They need the built database
(`python -m src.pipeline`) and are skipped automatically if PostgreSQL is unreachable."""
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_loader import get_engine, query  # noqa: E402


@pytest.fixture(scope="module")
def engine():
    try:
        eng = get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1 FROM retail.transactions LIMIT 1"))
        return eng
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"database not available: {exc}")


def scalar(engine, sql):
    return query(engine, sql).iloc[0, 0]


@pytest.mark.parametrize("table,key", [
    ("retail.transactions", "transaction_id"), ("retail.transaction_items", "transaction_item_id"),
    ("retail.products", "product_id"), ("retail.customers", "customer_id"), ("retail.branches", "branch_id"),
    ("retail.inventory_snapshots", "inventory_id"), ("retail.promotions", "promotion_id"),
])
def test_primary_keys_unique(engine, table, key):
    assert scalar(engine, f"SELECT COUNT(*) - COUNT(DISTINCT {key}) FROM {table}") == 0


def test_integrity_checks_all_zero(engine):
    sql = (Path(__file__).resolve().parents[1] / "sql" / "02_data_quality_checks.sql").read_text()
    block = sql.split("-- @query dq_b01_integrity_summary")[1].split("-- @query")[0].strip().rstrip(";")
    res = query(engine, block)
    assert res.failures.sum() == 0, res[res.failures > 0]


def test_foreign_keys_enforced(engine):
    fks = scalar(engine, "SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema='retail' AND constraint_type='FOREIGN KEY'")
    assert fks >= 9


def test_sales_view_does_not_fan_out(engine):
    assert scalar(engine, "SELECT COUNT(*) FROM retail.transaction_items") == scalar(engine, "SELECT COUNT(*) FROM retail.v_sales_lines")


def test_revenue_reconciles_between_sql_and_pandas(engine):
    """Recompute revenue and gross profit from base tables in pandas and compare with the SQL view."""
    items = query(engine, "SELECT product_id, quantity, unit_price::float, discount_amount::float FROM retail.transaction_items")
    cost = query(engine, "SELECT product_id, unit_cost::float FROM retail.products")
    df = items.merge(cost, on="product_id", how="left", validate="many_to_one")
    rev = (df.quantity * df.unit_price - df.discount_amount).sum()
    gp = rev - (df.quantity * df.unit_cost).sum()
    sql = query(engine, "SELECT SUM(net_revenue)::float AS rev, SUM(gross_profit)::float AS gp FROM retail.v_sales_lines").iloc[0]
    assert rev == pytest.approx(sql.rev, rel=1e-9)
    assert gp == pytest.approx(sql.gp, rel=1e-9)


def test_basket_count_matches_transactions(engine):
    assert scalar(engine, "SELECT COUNT(*) FROM retail.v_baskets") == scalar(
        engine, "SELECT COUNT(DISTINCT transaction_id) FROM retail.transaction_items")


def test_branch_totals_sum_to_chain(engine):
    by_branch = query(engine, "SELECT branch_id, SUM(net_revenue)::float AS r FROM retail.v_sales_lines GROUP BY 1").r.sum()
    total = scalar(engine, "SELECT SUM(net_revenue)::float FROM retail.v_sales_lines")
    assert by_branch == pytest.approx(total)


def test_stock_never_negative_and_one_snapshot_per_week(engine):
    assert scalar(engine, "SELECT COUNT(*) FROM retail.inventory_snapshots WHERE stock_quantity < 0") == 0
    assert scalar(engine, """SELECT COUNT(*) FROM (SELECT branch_id, product_id, date_trunc('week', snapshot_date)
                             FROM retail.inventory_snapshots GROUP BY 1,2,3 HAVING COUNT(*) > 1) x""") == 0


def test_powerbi_reconciliation_matches_sql(engine):
    rec = pd.read_csv(Path(__file__).resolve().parents[1] / "powerbi" / "kpi_reconciliation.csv")
    assert rec.loc[0, "revenue"] == pytest.approx(round(scalar(engine, "SELECT SUM(net_revenue)::float FROM retail.v_sales_lines")), abs=1)
