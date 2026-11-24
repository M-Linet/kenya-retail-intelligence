"""Cleaning rules for the Savanna Fresh raw export.

Each function takes a raw (all-text) DataFrame and returns a cleaned DataFrame plus a list of
exception records (source_table, record_key, issue, action_taken) written to retail.dq_exceptions.

Guiding rule: fix only what can be fixed with certainty; quarantine what would require a guess;
never silently delete. Every change is logged.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

PERIOD_START = pd.Timestamp("2024-11-01")
PERIOD_END = pd.Timestamp("2026-10-31 23:59:59")

CANONICAL_CATEGORIES = [
    "Staples", "Fresh Produce", "Dairy", "Bakery", "Beverages", "Meat & Poultry",
    "Household & Cleaning", "Personal Care", "Snacks & Confectionery", "Baby Care",
]
CANONICAL_SEGMENTS = ["Household", "Young Professional", "Small Business", "Senior"]
PAYMENT_MAP = {
    "mobile money": "Mobile Money", "m-money": "Mobile Money",
    "card": "Card", "cash": "Cash", "voucher": "Voucher",
}
# Quantity at or above this on a non-business basket is treated as a likely keying error.
# The threshold comes from the outlier investigation (notebook 02, sql/02 check 'dq_quantity_profile'):
# after cleaning, non-business baskets never exceed 10 units of one product and Small Business
# bulk purchases reach about 50, while the suspect values are all >= 100 (x100 keying pattern).
QTY_ERROR_THRESHOLD = 100

Exceptions = list[tuple[str, str, str, str]]


def _norm_key(s: str) -> str:
    """Lower-case, collapse whitespace, and treat 'and' and '&' as the same."""
    s = re.sub(r"\s+", " ", str(s).strip().lower())
    return s.replace(" and ", " & ")


def normalise_category(value: str | None) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    lookup = {_norm_key(c): c for c in CANONICAL_CATEGORIES}
    return lookup.get(_norm_key(value))


def normalise_payment(value: str | None) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or str(value).strip() == "":
        return "Unknown"
    return PAYMENT_MAP.get(str(value).strip().lower(), str(value).strip().title())


def drop_exact_duplicates(df: pd.DataFrame, key: str, table: str, exc: Exceptions) -> pd.DataFrame:
    dup_mask = df.duplicated(keep="first")
    for k in df.loc[dup_mask, key]:
        exc.append((table, str(k), "exact duplicate row", "removed duplicate copy"))
    out = df[~dup_mask].copy()
    # Same key but different content cannot be resolved automatically: fail loudly.
    conflict = out[key].duplicated(keep=False)
    if conflict.any():
        raise ValueError(f"{table}: {conflict.sum()} rows share a key with different content")
    return out


def clean_branches(raw: pd.DataFrame) -> tuple[pd.DataFrame, Exceptions]:
    exc: Exceptions = []
    df = drop_exact_duplicates(raw, "branch_id", "branches", exc)
    for c in ["branch_name", "county", "town", "branch_type"]:
        df[c] = df[c].str.strip()
    df["opening_date"] = pd.to_datetime(df["opening_date"]).dt.date
    return df, exc


def clean_products(raw: pd.DataFrame, items_raw: pd.DataFrame) -> tuple[pd.DataFrame, Exceptions]:
    exc: Exceptions = []
    df = drop_exact_duplicates(raw, "product_id", "products", exc)
    stripped = df["product_name"].str.strip()
    for k in df.loc[stripped != df["product_name"], "product_id"]:
        exc.append(("products", k, "leading/trailing whitespace in name", "trimmed"))
    df["product_name"] = stripped

    canon = df["category"].map(normalise_category)
    if canon.isna().any():
        raise ValueError(f"Unmapped categories: {df.loc[canon.isna(), 'category'].unique()}")
    for k in df.loc[canon != df["category"], "product_id"]:
        exc.append(("products", k, "non-standard category label", "mapped to canonical category"))
    df["category"] = canon

    no_brand = df["brand"].isna()
    for k in df.loc[no_brand, "product_id"]:
        exc.append(("products", k, "missing brand", "set to 'Unknown'"))
    df["brand"] = df["brand"].fillna("Unknown")

    # Missing unit cost: impute = modal selling price x (1 - median margin of the same category).
    # Flagged so that profit figures for these products can be excluded in sensitivity checks.
    df["unit_cost"] = pd.to_numeric(df["unit_cost"])
    prices = items_raw.assign(unit_price=pd.to_numeric(items_raw["unit_price"]))
    prices = prices[prices["unit_price"] > 0]
    modal_price = prices.groupby("product_id")["unit_price"].agg(lambda s: s.mode().iloc[0])
    df["modal_price"] = df["product_id"].map(modal_price)
    df["cost_ratio"] = df["unit_cost"] / df["modal_price"]
    cat_ratio = df.groupby("category")["cost_ratio"].median()
    missing = df["unit_cost"].isna()
    df.loc[missing, "unit_cost"] = (df.loc[missing, "modal_price"] * df.loc[missing, "category"].map(cat_ratio)).round(2)
    df["unit_cost_imputed"] = missing
    for k in df.loc[missing, "product_id"]:
        exc.append(("products", k, "missing unit_cost", "imputed from category median cost ratio"))
    return df[["product_id", "product_name", "category", "brand", "unit_cost", "unit_cost_imputed"]], exc


def clean_customers(raw: pd.DataFrame) -> tuple[pd.DataFrame, Exceptions]:
    exc: Exceptions = []
    df = drop_exact_duplicates(raw, "customer_id", "customers", exc)
    canon = {s.lower(): s for s in CANONICAL_SEGMENTS}
    seg = df["customer_segment"].str.strip().str.lower().map(canon)
    if seg.isna().any():
        raise ValueError("Unmapped customer segments")
    for k in df.loc[seg != df["customer_segment"], "customer_id"]:
        exc.append(("customers", k, "segment label casing", "standardised"))
    df["customer_segment"] = seg
    reg = pd.to_datetime(df["registration_date"], errors="coerce")
    placeholder = reg < pd.Timestamp("2000-01-01")
    for k in df.loc[placeholder, "customer_id"]:
        exc.append(("customers", k, "placeholder registration date 1900-01-01", "set to NULL"))
    reg[placeholder] = pd.NaT
    df["registration_date"] = reg.dt.date
    for k in df.loc[df["county"].isna(), "customer_id"]:
        exc.append(("customers", k, "missing county", "left NULL (reported as Unknown)"))
    return df, exc


def clean_promotions(raw: pd.DataFrame) -> tuple[pd.DataFrame, Exceptions]:
    exc: Exceptions = []
    df = drop_exact_duplicates(raw, "promotion_id", "promotions", exc)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    swapped = df["end_date"] < df["start_date"]
    for k in df.loc[swapped, "promotion_id"]:
        exc.append(("promotions", k, "end_date before start_date", "swapped dates"))
    df.loc[swapped, ["start_date", "end_date"]] = df.loc[swapped, ["end_date", "start_date"]].to_numpy()
    df["discount_percentage"] = pd.to_numeric(df["discount_percentage"])
    df["start_date"], df["end_date"] = df["start_date"].dt.date, df["end_date"].dt.date
    return df, exc


def clean_transactions(raw: pd.DataFrame, valid_branches: set[str], valid_customers: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, Exceptions]:
    """Returns (clean, quarantined, exceptions)."""
    exc: Exceptions = []
    df = drop_exact_duplicates(raw, "transaction_id", "transactions", exc)
    ts = pd.to_datetime(df["transaction_ts"], errors="coerce")
    bad_date = ts.isna() | (ts < PERIOD_START) | (ts > PERIOD_END)
    orphan_branch = ~df["branch_id"].isin(valid_branches)
    orphan_cust = df["customer_id"].notna() & ~df["customer_id"].isin(valid_customers)
    for k in df.loc[bad_date, "transaction_id"]:
        exc.append(("transactions", k, "timestamp outside data period (likely year typo)", "quarantined"))
    for k in df.loc[orphan_branch, "transaction_id"]:
        exc.append(("transactions", k, "branch_id not in branch master", "quarantined"))
    for k in df.loc[orphan_cust, "transaction_id"]:
        exc.append(("transactions", k, "customer_id not in customer master", "quarantined"))
    bad = bad_date | orphan_branch | orphan_cust
    clean = df[~bad].copy()
    clean["transaction_ts"] = ts[~bad]
    newpay = clean["payment_method"].map(normalise_payment)
    changed = newpay != clean["payment_method"]
    for k, old in zip(clean.loc[changed, "transaction_id"], clean.loc[changed, "payment_method"]):
        exc.append(("transactions", k, "missing payment method" if pd.isna(old) else "non-standard payment label",
                    "set to 'Unknown'" if pd.isna(old) else "standardised"))
    clean["payment_method"] = newpay
    return clean, df[bad].copy(), exc


def clean_items(raw: pd.DataFrame, clean_tx: pd.DataFrame, customers: pd.DataFrame,
                valid_products: set[str], valid_promos: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Exceptions]:
    """Returns (sales lines, return lines, quarantined lines, exceptions)."""
    exc: Exceptions = []
    df = drop_exact_duplicates(raw, "transaction_item_id", "transaction_items", exc)
    for c in ["quantity"]:
        df[c] = pd.to_numeric(df[c]).astype(int)
    for c in ["unit_price", "discount_amount"]:
        df[c] = pd.to_numeric(df[c])
    df["transaction_item_id"] = df["transaction_item_id"].astype(int)

    # 1. Lines whose header was quarantined (or never existed) cannot be analysed.
    no_header = ~df["transaction_id"].isin(set(clean_tx["transaction_id"]))
    bad_product = ~df["product_id"].isin(valid_products)
    bad_promo = df["promotion_id"].notna() & ~df["promotion_id"].isin(valid_promos)

    # 2. Suspected quantity keying errors (see QTY_ERROR_THRESHOLD)
    seg = clean_tx.set_index("transaction_id")["customer_id"].map(
        customers.set_index("customer_id")["customer_segment"]).fillna("Anonymous")
    line_seg = df["transaction_id"].map(seg)
    qty_error = (df["quantity"] >= QTY_ERROR_THRESHOLD) & (line_seg != "Small Business")

    quarantine = no_header | bad_product | bad_promo | qty_error
    for mask, issue in [(no_header, "parent transaction quarantined or missing"),
                        (bad_product, "product_id not in product master"),
                        (bad_promo, "promotion_id not in promotion master"),
                        (qty_error, f"quantity >= {QTY_ERROR_THRESHOLD} on non-business basket")]:
        for k in df.loc[mask, "transaction_item_id"]:
            exc.append(("transaction_items", str(k), issue, "quarantined"))
    q = df[quarantine].copy()
    df = df[~quarantine].copy()

    # 3. Negative quantities are returns, moved to their own table
    is_return = df["quantity"] < 0
    ret = df[is_return].copy()
    ret = ret.assign(return_line_id=ret["transaction_item_id"], quantity_returned=-ret["quantity"],
                     refund_value=(-ret["quantity"] * ret["unit_price"]).round(2))
    for k in ret["return_line_id"]:
        exc.append(("transaction_items", str(k), "negative quantity", "moved to retail.returns"))
    df = df[~is_return].copy()

    # 4. Zero prices: impute the product's modal price (the shelf price is stable in this data)
    modal = df[df["unit_price"] > 0].groupby("product_id")["unit_price"].agg(lambda s: s.mode().iloc[0])
    zero = df["unit_price"] <= 0
    no_ref = zero & ~df["product_id"].isin(modal.index)       # nothing to impute from -> quarantine
    for k in df.loc[no_ref, "transaction_item_id"]:
        exc.append(("transaction_items", str(k), "zero unit_price, no reference price", "quarantined"))
    q = pd.concat([q, df[no_ref]])
    df = df[~no_ref].copy()
    zero = df["unit_price"] <= 0
    df["price_imputed"] = zero
    df.loc[zero, "unit_price"] = df.loc[zero, "product_id"].map(modal)
    for k in df.loc[zero, "transaction_item_id"]:
        exc.append(("transaction_items", str(k), "zero unit_price", "imputed modal product price"))
    return df, ret, q, exc


def clean_inventory(raw: pd.DataFrame, valid_products: set[str], valid_branches: set[str]) -> tuple[pd.DataFrame, Exceptions]:
    exc: Exceptions = []
    df = drop_exact_duplicates(raw, "inventory_id", "inventory", exc)
    for c in ["inventory_id", "stock_quantity", "reorder_level"]:
        df[c] = pd.to_numeric(df[c]).astype(int)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
    neg = df["stock_quantity"] < 0
    for k in df.loc[neg, "inventory_id"]:
        exc.append(("inventory", str(k), "negative stock count (sold before receipt posted)", "set to 0"))
    df.loc[neg, "stock_quantity"] = 0
    orphan = ~df["product_id"].isin(valid_products) | ~df["branch_id"].isin(valid_branches)
    for k in df.loc[orphan, "inventory_id"]:
        exc.append(("inventory", str(k), "unknown product or branch", "removed"))
    return df[~orphan], exc
