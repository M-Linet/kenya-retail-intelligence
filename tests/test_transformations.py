"""Unit tests for cleaning rules and metric definitions. No database is needed."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import analysis as an  # noqa: E402
from src import data_cleaning as dc  # noqa: E402


# ---------- label standardisation ----------
@pytest.mark.parametrize("raw,expected", [
    ("dairy", "Dairy"), ("BEVERAGES ", "Beverages"), (" Bakery", "Bakery"),
    ("Snacks and Confectionery", "Snacks & Confectionery"), ("Meat and Poultry", "Meat & Poultry"),
    ("Household & cleaning", "Household & Cleaning"), ("Not a category", None),
])
def test_normalise_category(raw, expected):
    assert dc.normalise_category(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("mobile money", "Mobile Money"), ("M-Money", "Mobile Money"), ("CARD ", "Card"), ("cash ", "Cash"),
    (None, "Unknown"), (np.nan, "Unknown"), ("", "Unknown"), ("Voucher", "Voucher"),
])
def test_normalise_payment(raw, expected):
    assert dc.normalise_payment(raw) == expected


# ---------- duplicates ----------
def test_exact_duplicates_dropped_and_logged():
    df = pd.DataFrame({"id": ["a", "a", "b"], "v": [1, 1, 2]})
    exc = []
    out = dc.drop_exact_duplicates(df, "id", "t", exc)
    assert len(out) == 2 and len(exc) == 1


def test_conflicting_duplicates_raise():
    df = pd.DataFrame({"id": ["a", "a"], "v": [1, 2]})
    with pytest.raises(ValueError):
        dc.drop_exact_duplicates(df, "id", "t", [])


# ---------- transactions ----------
def _tx():
    return pd.DataFrame({
        "transaction_id": ["T1", "T2", "T3", "T4"],
        "transaction_ts": ["2025-03-01 10:00:00", "2062-03-01 10:00:00", "2025-03-02 11:00:00", "2025-03-03 12:00:00"],
        "branch_id": ["BR01", "BR01", "BR99", "BR01"],
        "customer_id": ["C1", None, None, "C2"],
        "payment_method": ["mobile money", "Cash", "Card", None],
    })


def test_transactions_quarantine_bad_dates_and_orphans():
    clean, q, exc = dc.clean_transactions(_tx(), {"BR01"}, {"C1", "C2"})
    assert set(clean.transaction_id) == {"T1", "T4"}
    assert set(q.transaction_id) == {"T2", "T3"}
    assert clean.set_index("transaction_id").loc["T4", "payment_method"] == "Unknown"
    assert clean.set_index("transaction_id").loc["T1", "payment_method"] == "Mobile Money"


# ---------- line items ----------
def _items():
    return pd.DataFrame({
        "transaction_item_id": ["1", "2", "3", "4", "5", "6"],
        "transaction_id": ["T1", "T1", "T1", "T4", "T4", "T2"],
        "product_id": ["P1", "P2", "P1", "P1", "P2", "P1"],
        "quantity": ["2", "-1", "300", "40", "1", "1"],
        "unit_price": ["100", "50", "100", "100", "0", "100"],
        "discount_amount": ["0", "0", "0", "0", "0", "0"],
        "promotion_id": [None] * 6,
    })


def test_items_rules():
    tx, _, _ = dc.clean_transactions(_tx(), {"BR01"}, {"C1", "C2"})
    customers = pd.DataFrame({"customer_id": ["C1", "C2"], "customer_segment": ["Household", "Small Business"]})
    sales, returns, q, exc = dc.clean_items(_items(), tx, customers, {"P1", "P2"}, set())
    # line 2 is a return; line 3 (qty 300, household basket) is quarantined; line 6 belongs to quarantined T2
    assert list(returns.return_line_id) == [2]
    assert {3, 6} <= set(q.transaction_item_id)
    # line 4 (qty 40) belongs to a Small Business basket and is kept
    assert 4 in set(sales.transaction_item_id)
    # line 5 has a zero price and P2 has no positive-price sale to impute from, so it must be quarantined,
    # never loaded with a zero or missing price
    assert 5 in set(q.transaction_item_id)
    assert (sales.unit_price > 0).all() and sales.unit_price.notna().all()


def test_zero_price_imputed_with_modal_price():
    tx, _, _ = dc.clean_transactions(_tx(), {"BR01"}, {"C1", "C2"})
    items = _items()
    items.loc[4, "product_id"] = "P1"  # zero-price line now belongs to P1, whose modal price is 100
    customers = pd.DataFrame({"customer_id": ["C1", "C2"], "customer_segment": ["Household", "Small Business"]})
    sales, _, _, _ = dc.clean_items(items, tx, customers, {"P1", "P2"}, set())
    row = sales.set_index("transaction_item_id").loc[5]
    assert row.unit_price == 100 and bool(row.price_imputed)


def test_promotion_dates_swapped():
    raw = pd.DataFrame({"promotion_id": ["PR1"], "product_id": ["P1"], "start_date": ["2026-01-29"],
                        "end_date": ["2026-01-16"], "discount_percentage": ["10"]})
    out, exc = dc.clean_promotions(raw)
    assert out.start_date.iloc[0] < out.end_date.iloc[0] and len(exc) == 1


def test_negative_inventory_set_to_zero():
    raw = pd.DataFrame({"inventory_id": ["1", "2"], "product_id": ["P1", "P1"], "branch_id": ["BR01", "BR01"],
                        "snapshot_date": ["2025-01-05", "2025-01-12"], "stock_quantity": ["-3", "5"], "reorder_level": ["2", "2"]})
    out, exc = dc.clean_inventory(raw, {"P1"}, {"BR01"})
    assert out.stock_quantity.tolist() == [0, 5] and len(exc) == 1


# ---------- metric definitions ----------
def test_line_metrics_and_margin_from_totals():
    lines = pd.DataFrame({"cat": ["A", "A", "B"], "quantity": [1, 10, 2], "unit_price": [100.0, 10.0, 50.0],
                          "discount_amount": [10.0, 0.0, 0.0], "unit_cost": [80.0, 5.0, 40.0]})
    m = an.add_line_metrics(lines)
    assert m.net_revenue.tolist() == [90.0, 100.0, 100.0]
    assert m.gross_profit.tolist() == [10.0, 50.0, 20.0]
    t = an.margin_table(m, "cat")
    # margin of A must be (10+50)/(90+100) = 31.58%, NOT the mean of line margins (11.1% and 50%)
    assert t.loc["A", "gross_margin_pct"] == pytest.approx(100 * 60 / 190)


def test_turnover_and_cover():
    assert an.annual_turnover(cogs=1000, avg_stock_value=100, days=182) == pytest.approx(20.0)
    assert np.isnan(an.annual_turnover(1000, 0, 364))
    assert an.weeks_of_cover(30, 10) == 3
    assert an.weeks_of_cover(5, 0) == np.inf
