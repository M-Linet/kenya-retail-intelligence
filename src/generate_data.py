"""
Synthetic data generator for *Savanna Fresh Supermarkets* (a FICTIONAL Kenyan chain).

Nothing produced here represents any real retailer, brand, customer or transaction.
The generator exists because no public dataset is transaction-level, Kenyan, and
contains branch, cost, inventory and promotion fields together (see
reports/methodology.md for the dataset review).

Design principles
-----------------
1. Reproducible: one seed controls everything (`python -m src.generate_data --seed 2027`).
2. Internally consistent: weekly inventory is SIMULATED from the generated demand with a
   reorder-point policy. When a branch runs out of a product, the unmet demand is removed
   from the sales lines (lost sales are invisible in real POS data too).
3. Realistic but controlled problems: after the "true" data is built, documented
   data-quality issues are injected into the raw export and counted in
   data/synthetic/raw/injection_manifest.json so cleaning can be verified.

Business mechanisms built in (the analysis has to *discover* their size and location):
- Category margin structure (staples low margin, fresh/personal care high margin).
- Day-of-week, payday (25th-3rd) and December festive seasonality; Easter bump.
- One branch with discretionary (non-promotion) discounting, two branches with longer
  supplier lead times, one branch with declining footfall, one branch opened mid-period.
- Products with over-ordering, stale reorder levels, or demand that collapses mid-period.
- Promotions whose demand response differs by category.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2024-11-01")
END = pd.Timestamp("2026-10-31")
WEEK0 = pd.Timestamp("2024-10-28")  # Monday on/before START; inventory weeks run Mon-Sun
TARGET_TRANSACTIONS = 300_000

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "raw"

# --------------------------------------------------------------------------------------
# Master data definitions
# --------------------------------------------------------------------------------------
BRANCHES = [
    # id, name, county, town, type, opening_date, traffic, lead_time_weeks
    ("BR01", "Savanna Fresh Westlands", "Nairobi", "Westlands", "Hypermarket", "2018-03-01", 1.60, 1),
    ("BR02", "Savanna Fresh Embakasi", "Nairobi", "Embakasi", "Supermarket", "2019-07-15", 1.15, 1),
    ("BR03", "Savanna Fresh Kasarani", "Nairobi", "Kasarani", "Express", "2021-02-01", 0.80, 1),
    ("BR04", "Savanna Fresh Nyali", "Mombasa", "Nyali", "Hypermarket", "2019-11-01", 1.45, 1),
    ("BR05", "Savanna Fresh Mombasa CBD", "Mombasa", "Mombasa", "Supermarket", "2020-04-01", 1.00, 1),
    ("BR06", "Savanna Fresh Kisumu", "Kisumu", "Kisumu", "Supermarket", "2020-09-01", 1.05, 2),
    ("BR07", "Savanna Fresh Nakuru", "Nakuru", "Nakuru", "Hypermarket", "2019-05-01", 1.30, 1),
    ("BR08", "Savanna Fresh Naivasha", "Nakuru", "Naivasha", "Express", "2022-03-01", 0.70, 1),
    ("BR09", "Savanna Fresh Thika", "Kiambu", "Thika", "Supermarket", "2021-08-01", 1.00, 1),
    ("BR10", "Savanna Fresh Ruiru", "Kiambu", "Ruiru", "Express", "2025-06-02", 0.85, 1),
    ("BR11", "Savanna Fresh Eldoret", "Uasin Gishu", "Eldoret", "Supermarket", "2020-01-15", 1.00, 2),
    ("BR12", "Savanna Fresh Machakos", "Machakos", "Machakos", "Express", "2022-10-01", 0.90, 1),
]
DISCOUNTING_BRANCH = "BR04"      # discretionary discounting outside promotions
DECLINING_BRANCH = "BR12"        # footfall declines across the period

# category: (target margin, demand share, promo elasticity, qty_extra_lambda, items)
# items: (item name, base price KES)
CATEGORIES = {
    "Staples": (0.09, 0.20, 4.0, 0.5, [
        ("Maize Flour 2kg", 180), ("Wheat Flour 2kg", 200), ("Rice 2kg", 350), ("Sugar 2kg", 330),
        ("Cooking Oil 1L", 330), ("Cooking Oil 3L", 900), ("Salt 1kg", 40), ("Beans 1kg", 200),
        ("Spaghetti 400g", 110)]),
    "Fresh Produce": (0.32, 0.13, 2.0, 0.8, [
        ("Tomatoes 1kg", 120), ("Onions 1kg", 110), ("Potatoes 2kg", 220), ("Bananas 1kg", 100),
        ("Sukuma Wiki Bunch", 30), ("Avocado Each", 40), ("Oranges 1kg", 160), ("Cabbage Each", 80)]),
    "Dairy": (0.16, 0.13, 3.0, 0.4, [
        ("Fresh Milk 500ml", 65), ("Long-life Milk 500ml", 70), ("Yoghurt 500ml", 160),
        ("Butter 250g", 330), ("Cheese 200g", 450), ("Eggs Tray 30", 480)]),
    "Bakery": (0.24, 0.10, 2.5, 0.2, [
        ("White Bread 400g", 65), ("Brown Bread 600g", 85), ("Chapati 5pc", 100),
        ("Mandazi 6pc", 90), ("Queen Cakes 6pc", 120)]),
    "Beverages": (0.21, 0.10, 5.0, 0.4, [
        ("Soda 500ml", 70), ("Soda 2L", 200), ("Fruit Juice 1L", 230), ("Bottled Water 1L", 60),
        ("Tea Leaves 250g", 150), ("Instant Coffee 100g", 400)]),
    "Meat & Poultry": (0.18, 0.06, 2.0, 0.2, [
        ("Beef 1kg", 750), ("Whole Chicken", 650), ("Sausages 500g", 350), ("Minced Meat 500g", 420)]),
    "Household & Cleaning": (0.23, 0.09, 3.5, 0.2, [
        ("Bar Soap 800g", 200), ("Detergent 1kg", 330), ("Bleach 750ml", 180),
        ("Dishwashing Liquid 500ml", 150), ("Toilet Paper 10pk", 450), ("Matches 10pk", 60)]),
    "Personal Care": (0.30, 0.07, 2.5, 0.1, [
        ("Toothpaste 100ml", 140), ("Body Lotion 400ml", 380), ("Bathing Soap 3pk", 210),
        ("Sanitary Pads 10pk", 120), ("Roll-on Deodorant", 350), ("Hair Food 250g", 180)]),
    "Snacks & Confectionery": (0.27, 0.08, 6.0, 0.3, [
        ("Potato Crisps 150g", 120), ("Biscuits 200g", 80), ("Chocolate Bar 80g", 130),
        ("Assorted Sweets 250g", 100), ("Roasted Peanuts 200g", 110)]),
    "Baby Care": (0.19, 0.04, 2.0, 0.1, [
        ("Diapers 40pk", 1300), ("Baby Wipes 80pc", 250), ("Baby Cereal 400g", 450),
        ("Baby Lotion 200ml", 350)]),
}
# Fictional brands per category: (brand, price multiplier, margin adjustment, popularity)
BRANDS = {
    "Staples": [("Mlima Gold", 1.00, 0.00, 1.0), ("Shamba Pride", 0.95, 0.00, 0.8),
                ("Savanna Value", 0.88, 0.05, 0.6), ("Royal Harvest", 1.15, 0.03, 0.35)],
    "Fresh Produce": [("Savanna Farm", 1.00, 0.00, 1.0), ("Highland Growers", 1.12, 0.02, 0.5),
                      ("Lakeside Organics", 1.35, 0.05, 0.2)],
    "Dairy": [("Tamu Dairy", 1.00, 0.00, 1.0), ("Rift Creamery", 1.06, 0.01, 0.7),
              ("Savanna Value", 0.90, 0.05, 0.4)],
    "Bakery": [("Savanna Bakery", 1.00, 0.04, 1.0), ("Golden Crust", 1.08, 0.00, 0.7),
               ("Mkate Bora", 0.95, 0.00, 0.5)],
    "Beverages": [("Pwani Springs", 1.00, 0.00, 1.0), ("Tropika", 1.05, 0.00, 0.8),
                  ("Savanna Value", 0.88, 0.05, 0.4), ("Kilele Premium", 1.30, 0.04, 0.25)],
    "Meat & Poultry": [("Savanna Butchery", 1.00, 0.00, 1.0), ("Kuku Fresh", 1.05, 0.00, 0.7),
                       ("Ranch Select", 1.25, 0.03, 0.3)],
    "Household & Cleaning": [("Safi Home", 1.00, 0.00, 1.0), ("Nyota Clean", 0.95, 0.00, 0.7),
                             ("Savanna Value", 0.85, 0.06, 0.5), ("Crystal Pro", 1.30, 0.04, 0.25)],
    "Personal Care": [("Afya Care", 1.00, 0.00, 1.0), ("Lulu Beauty", 1.20, 0.03, 0.6),
                      ("Savanna Value", 0.85, 0.06, 0.4)],
    "Snacks & Confectionery": [("Crunchy Bites", 1.00, 0.00, 1.0), ("Tamu Treats", 1.05, 0.00, 0.8),
                               ("Savanna Value", 0.88, 0.05, 0.4), ("Velvet Cocoa", 1.40, 0.03, 0.25)],
    "Baby Care": [("Mtoto Soft", 1.00, 0.00, 1.0), ("Little Star", 1.15, 0.02, 0.6),
                  ("Savanna Value", 0.85, 0.05, 0.35)],
}
SEGMENTS = [("Household", 0.65), ("Young Professional", 0.20), ("Small Business", 0.08), ("Senior", 0.07)]
PAYMENTS = [("Mobile Money", 0.58), ("Cash", 0.22), ("Card", 0.17), ("Voucher", 0.03)]


def build_branches() -> pd.DataFrame:
    cols = ["branch_id", "branch_name", "county", "town", "branch_type", "opening_date", "traffic", "lead_time"]
    return pd.DataFrame(BRANCHES, columns=cols)


def build_products(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    pid = 1
    for cat, (margin, share, elast, qlam, items) in CATEGORIES.items():
        n_items = len(items)
        for i, (item, price) in enumerate(items):
            item_weight = rng.lognormal(0, 0.5) * (1.4 if i < 3 else 1.0)  # first items are staples of the aisle
            for brand, pmult, madj, bpop in BRANDS[cat]:
                list_price = float(np.round(price * pmult * rng.uniform(0.97, 1.03), 0))
                m = float(np.clip(margin + madj + rng.normal(0, 0.025), 0.03, 0.55))
                unit_cost = round(list_price * (1 - m), 2)
                rows.append({
                    "product_id": f"P{pid:04d}",
                    "product_name": f"{brand} {item}",
                    "category": cat,
                    "brand": brand,
                    "unit_cost": unit_cost,
                    "list_price": list_price,
                    "weight": share / n_items * item_weight * bpop,
                })
                pid += 1
    df = pd.DataFrame(rows)
    df["weight"] = df["weight"] / df["weight"].sum()
    # A tail of genuinely slow sellers (~8% of range)
    slow = rng.choice(df.index, size=int(len(df) * 0.08), replace=False)
    df.loc[slow, "weight"] *= 0.12
    df["weight"] = df["weight"] / df["weight"].sum()
    return df


def build_customers(rng: np.random.Generator, branches: pd.DataFrame, n: int = 9000) -> pd.DataFrame:
    seg_names, seg_p = zip(*SEGMENTS)
    seg = rng.choice(seg_names, size=n, p=seg_p)
    # Home branch roughly proportional to branch traffic
    bw = branches["traffic"].to_numpy() / branches["traffic"].sum()
    home = rng.choice(branches["branch_id"], size=n, p=bw)
    county_map = dict(zip(branches["branch_id"], branches["county"]))
    counties = np.array([county_map[h] for h in home], dtype=object)
    other = rng.random(n) < 0.08  # some customers live in a different county
    counties[other] = rng.choice(branches["county"].unique(), size=other.sum())
    reg = pd.to_datetime("2019-01-01") + pd.to_timedelta(rng.integers(0, (END - pd.Timestamp("2019-01-01")).days, n), unit="D")
    activity = rng.lognormal(0, 0.9, n) * np.where(seg == "Small Business", 3.0, 1.0)
    return pd.DataFrame({
        "customer_id": [f"C{i:05d}" for i in range(1, n + 1)],
        "customer_segment": seg,
        "registration_date": reg,
        "county": counties,
        "home_branch": home,
        "activity": activity,
    })


def daily_multiplier(dates: pd.DatetimeIndex) -> np.ndarray:
    dow = np.array([0.85, 0.85, 0.90, 0.95, 1.10, 1.35, 1.10])[np.asarray(dates.dayofweek)]
    day = np.asarray(dates.day)
    payday = np.where((day >= 25) | (day <= 3), 1.20, 1.0)
    month = np.asarray(dates.month)
    season = np.ones(len(dates))
    season[month == 12] = 1.30
    season[(month == 12) & (day >= 15)] = 1.50
    season[month == 1] = 0.85
    # Easter weeks (2025-04-18..21, 2026-04-03..06)
    for s, e in [("2025-04-14", "2025-04-21"), ("2026-03-30", "2026-04-06")]:
        season[np.asarray((dates >= s) & (dates <= e))] = 1.20
    trend = 1 + 0.08 * np.asarray((dates - START).days) / 365.0
    return np.asarray(dow * payday * season * trend, dtype=float)


def build_promotions(rng: np.random.Generator, products: pd.DataFrame) -> pd.DataFrame:
    promo_cats = {"Snacks & Confectionery": 3, "Beverages": 3, "Household & Cleaning": 2.5,
                  "Personal Care": 2, "Staples": 2.5, "Dairy": 1.5, "Baby Care": 1, "Bakery": 0.5}
    w = products["category"].map(promo_cats).fillna(0).to_numpy() * np.sqrt(products["weight"].to_numpy())
    w = w / w.sum()
    rows, used = [], {}
    pid = 1
    while len(rows) < 110:
        prod = rng.choice(products["product_id"], p=w)
        start = START + pd.Timedelta(days=int(rng.integers(0, (END - START).days - 21)))
        dur = int(rng.choice([7, 14], p=[0.6, 0.4]))
        end = start + pd.Timedelta(days=dur - 1)
        # no overlapping promotions on the same product
        if any(not (end < s or start > e) for s, e in used.get(prod, [])):
            continue
        used.setdefault(prod, []).append((start, end))
        pct = float(rng.choice([5, 10, 15, 20, 25], p=[0.1, 0.3, 0.3, 0.2, 0.1]))
        rows.append({"promotion_id": f"PR{pid:03d}", "product_id": prod, "start_date": start.normalize(),
                     "end_date": end.normalize(), "discount_percentage": pct})
        pid += 1
    return pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Transactions and lines
# --------------------------------------------------------------------------------------
def build_transactions(rng, branches, customers):
    dates = pd.date_range(START, END, freq="D")
    mult = daily_multiplier(dates)
    base = TARGET_TRANSACTIONS / (mult.sum() * branches["traffic"].sum())
    recs = []
    for b in branches.itertuples():
        open_d = pd.Timestamp(b.opening_date)
        lam = base * b.traffic * mult
        if b.branch_id == DECLINING_BRANCH:
            lam = lam * (1 - 0.35 * np.asarray((dates - START).days) / (END - START).days)
        if open_d > START:
            age = np.asarray((dates - open_d).days)
            ramp = np.clip(age / 90.0, 0.3, 1.0)
            lam = np.where(np.asarray(dates < open_d), 0, lam * ramp)
        n = rng.poisson(lam)
        recs.append(pd.DataFrame({"branch_id": b.branch_id, "date": np.repeat(dates, n)}))
    tx = pd.concat(recs, ignore_index=True)
    n = len(tx)
    # time of day: weekday evening peak, weekend midday peak
    hours = np.arange(7, 23)
    wk = np.array([1, 2, 3, 4, 4, 5, 5, 4, 4, 5, 7, 9, 8, 5, 3, 1], float)
    we = np.array([1, 2, 4, 6, 8, 9, 9, 8, 7, 6, 6, 6, 5, 3, 2, 1], float)
    is_we = tx["date"].dt.dayofweek.to_numpy() >= 5
    h = np.where(is_we, rng.choice(hours, n, p=we / we.sum()), rng.choice(hours, n, p=wk / wk.sum()))
    tx["transaction_ts"] = tx["date"] + pd.to_timedelta(h, unit="h") + pd.to_timedelta(rng.integers(0, 3600, n), unit="s")
    # customers: ~62% of baskets scanned with a loyalty card
    tx["customer_id"] = None
    loyal = rng.random(n) < 0.62
    cust_by_branch = {bid: g for bid, g in customers.groupby("home_branch")}
    cust_col = np.empty(n, dtype=object)
    for bid, idx in tx[loyal].groupby("branch_id").groups.items():
        pool = cust_by_branch[bid]
        p = pool["activity"].to_numpy() / pool["activity"].sum()
        cust_col[np.asarray(tx.index.get_indexer(idx))] = rng.choice(pool["customer_id"].to_numpy(), size=len(idx), p=p)
    tx["customer_id"] = cust_col
    pay, pp = zip(*PAYMENTS)
    tx["payment_method"] = rng.choice(pay, n, p=pp)
    tx = tx.sort_values("transaction_ts").reset_index(drop=True)
    tx["transaction_id"] = [f"T{i:07d}" for i in range(1, n + 1)]
    return tx


def build_lines(rng, tx, products, branches, customers, promotions):
    seg_map = dict(zip(customers["customer_id"], customers["customer_segment"]))
    btype = dict(zip(branches["branch_id"], branches["branch_type"]))
    seg = tx["customer_id"].map(seg_map).fillna("Anonymous").to_numpy()
    type_lam = {"Hypermarket": 4.0, "Supermarket": 3.0, "Express": 1.8}
    lam = tx["branch_id"].map(lambda b: type_lam[btype[b]]).to_numpy(dtype=float)
    lam = lam + np.where(seg == "Small Business", 2.5, 0) + np.where(seg == "Young Professional", -0.5, 0)
    n_lines = 1 + rng.poisson(np.clip(lam, 0.5, None))
    li = pd.DataFrame({"tx_idx": np.repeat(np.arange(len(tx)), n_lines)})
    li["branch_id"] = tx["branch_id"].to_numpy()[li["tx_idx"]]
    li["date"] = tx["date"].to_numpy()[li["tx_idx"]]
    li["segment"] = seg[li["tx_idx"]]

    pids = products["product_id"].to_numpy()
    base_w = products["weight"].to_numpy()
    # branch-level taste variation (e.g., more fresh produce in some branches)
    branch_w = {b: base_w * rng.lognormal(0, 0.25, len(base_w)) for b in branches["branch_id"]}
    # demand collapse: a handful of products lose most demand after month 14
    collapse_idx = rng.choice(np.where(products["category"].isin(["Snacks & Confectionery", "Beverages", "Personal Care", "Household & Cleaning"]))[0], 6, replace=False)
    collapse_date = START + pd.DateOffset(months=14)
    cat_el = products["category"].map({c: v[2] for c, v in CATEGORIES.items()}).to_numpy()
    pidx = {p: i for i, p in enumerate(pids)}

    # promo lookup by day: array days x products of discount pct
    days = pd.date_range(START, END, freq="D")
    promo_pct = np.zeros((len(days), len(pids)))
    promo_id = np.full((len(days), len(pids)), None, dtype=object)
    for pr in promotions.itertuples():
        d0, d1 = (pr.start_date - START).days, (pr.end_date - START).days
        promo_pct[d0:d1 + 1, pidx[pr.product_id]] = pr.discount_percentage / 100
        promo_id[d0:d1 + 1, pidx[pr.product_id]] = pr.promotion_id

    li["day_idx"] = (li["date"] - START).dt.days.to_numpy()
    prod_choice = np.empty(len(li), dtype=np.int32)
    for (b, d), idx in li.groupby(["branch_id", "day_idx"]).indices.items():
        w = branch_w[b] * (1 + cat_el * promo_pct[d])
        if days[d] >= collapse_date:
            w = w.copy()
            w[collapse_idx] *= 0.05
        prod_choice[idx] = rng.choice(len(pids), size=len(idx), p=w / w.sum())
    li["p_idx"] = prod_choice

    qlam = products["category"].map({c: v[3] for c, v in CATEGORIES.items()}).to_numpy()[prod_choice]
    q = 1 + rng.poisson(qlam)
    on_promo = promo_pct[li["day_idx"].to_numpy(), prod_choice] > 0
    q = q + np.where(on_promo, rng.poisson(0.4, len(li)), 0)
    bulk_cats = products["category"].isin(["Staples", "Beverages", "Household & Cleaning"]).to_numpy()[prod_choice]
    sb = (li["segment"].to_numpy() == "Small Business") & bulk_cats
    q = np.where(sb, q * rng.integers(3, 9, len(li)), q)
    li["quantity"] = q

    # merge duplicate products within a basket into one line
    li = li.groupby(["tx_idx", "p_idx"], as_index=False).agg(
        quantity=("quantity", "sum"), branch_id=("branch_id", "first"), day_idx=("day_idx", "first"), segment=("segment", "first"))

    pi = li["p_idx"].to_numpy()
    di = li["day_idx"].to_numpy()
    li["product_id"] = pids[pi]
    li["unit_price"] = products["list_price"].to_numpy()[pi]
    pct = promo_pct[di, pi]
    li["promotion_id"] = promo_id[di, pi]
    # markdowns on perishables near expiry (no promotion_id)
    cat = products["category"].to_numpy()[pi]
    perish = np.isin(cat, ["Fresh Produce", "Bakery", "Dairy"])
    md = perish & (pct == 0) & (rng.random(len(li)) < 0.05)
    pct = np.where(md, rng.uniform(0.2, 0.4, len(li)), pct)
    # discretionary discounting at one branch (manager overrides, no promotion_id)
    disc_branch = (li["branch_id"].to_numpy() == DISCOUNTING_BRANCH) & (pct == 0) & (rng.random(len(li)) < 0.16)
    pct = np.where(disc_branch, rng.uniform(0.08, 0.20, len(li)), pct)
    li["disc_rate"] = pct
    return li, collapse_idx


# --------------------------------------------------------------------------------------
# Inventory simulation (reorder-point policy) and lost-sales trimming
# --------------------------------------------------------------------------------------
def simulate_inventory(rng, li, tx, products, branches, collapse_idx):
    li["week"] = ((pd.to_datetime(START) + pd.to_timedelta(li["day_idx"], unit="D") - WEEK0).dt.days // 7).to_numpy()
    n_weeks = int((END - WEEK0).days // 7) + 1
    bids = branches["branch_id"].tolist()
    bpos = {b: i for i, b in enumerate(bids)}
    nb, npd = len(bids), len(products)
    li["b_idx"] = li["branch_id"].map(bpos).to_numpy()
    D = np.zeros((nb, npd, n_weeks))
    np.add.at(D, (li["b_idx"].to_numpy(), li["p_idx"].to_numpy(), li["week"].to_numpy()), li["quantity"].to_numpy())

    open_week = np.array([max(0, (pd.Timestamp(d) - WEEK0).days // 7) for d in branches["opening_date"]])
    lead = branches["lead_time"].to_numpy()
    # expected weekly demand from first 8 open weeks (policy is set early, then not revisited)
    mu = np.zeros((nb, npd))
    for b in range(nb):
        w0 = open_week[b] if open_week[b] > 0 else 0
        w1 = w0 + 8
        mu[b] = D[b, :, w0:w1].mean(axis=1)
        if open_week[b] > 0:  # new branch ramping up: planners use chain average instead
            mu[b] = D[:, :, 8:16].mean(axis=(0, 2)) * branches["traffic"].iloc[b] / branches["traffic"].mean()
    mu = np.maximum(mu, 0.3)
    R = np.ceil(mu * 1.5)                     # reorder level = 1.5 weeks of demand
    S = R + np.ceil(mu * 2.5)                 # order-up-to level
    over = rng.random(npd) < 0.08             # over-ordered SKUs (buyer error)
    over[collapse_idx] = True                 # collapsing products were also bought deep
    S[:, over] = R[:, over] + np.ceil(mu[:, over] * 14)
    stale = rng.random((nb, npd)) < 0.06      # stale (too low) reorder levels
    R[stale] = np.floor(mu[stale] * 0.3)
    S[stale] = R[stale] + np.ceil(mu[stale] * 1.5)

    stock = S.copy()
    pipeline = np.zeros((nb, npd, n_weeks + 3))
    outstanding = np.zeros((nb, npd), bool)
    snap_stock = np.zeros((nb, npd, n_weeks))
    sales = np.zeros((nb, npd, n_weeks))
    for w in range(n_weeks):
        arrived = pipeline[:, :, w]
        stock = stock + arrived
        outstanding &= ~(arrived > 0)
        s = np.minimum(stock, D[:, :, w])
        sales[:, :, w] = s
        stock = stock - s
        snap_stock[:, :, w] = stock          # closing stock at end of week (Sunday count)
        need = (stock <= R) & ~outstanding
        for b in range(nb):
            nb_need = need[b]
            pipeline[b, nb_need, w + lead[b]] += (S[b, nb_need] - stock[b, nb_need])
        outstanding |= need

    # Trim lines where demand exceeded available stock (lost sales)
    li = li.sample(frac=1.0, random_state=int(rng.integers(1e9))).reset_index(drop=True)
    li["cum"] = li.groupby(["b_idx", "p_idx", "week"])["quantity"].cumsum()
    li["prev"] = li["cum"] - li["quantity"]
    allowed = sales[li["b_idx"].to_numpy(), li["p_idx"].to_numpy(), li["week"].to_numpy()]
    li["quantity"] = np.clip(allowed - li["prev"].to_numpy(), 0, li["quantity"].to_numpy()).astype(int)
    lost_units = float(D.sum() - sales.sum())
    li = li[li["quantity"] > 0].copy()

    # Snapshot table (only weeks where branch is open)
    snaps = []
    # snapshot = closing stock on the Sunday that ends each week (last week capped at END)
    snap_dates = (WEEK0 + pd.to_timedelta(np.arange(n_weeks) * 7 + 6, unit="D")).map(lambda d: min(d, END))
    for b in range(nb):
        for w in range(open_week[b], n_weeks):
            snaps.append(pd.DataFrame({"product_id": products["product_id"].to_numpy(), "branch_id": bids[b],
                                       "snapshot_date": snap_dates[w], "stock_quantity": snap_stock[b, :, w].astype(int),
                                       "reorder_level": R[b].astype(int)}))
    inv = pd.concat(snaps, ignore_index=True)
    inv.insert(0, "inventory_id", np.arange(1, len(inv) + 1))
    sim_meta = {"lost_units": lost_units, "demand_units": float(D.sum()),
                "over_ordered_products": products.loc[over, "product_id"].tolist(),
                "stale_reorder_pairs": int(stale.sum())}
    return li, inv, sim_meta


# --------------------------------------------------------------------------------------
# Data-quality injection (raw export only)
# --------------------------------------------------------------------------------------
def inject_issues(rng, t, products, customers, tx, items, inv, promotions, branches):
    m = {}
    # products: inconsistent categories, whitespace, missing brand/cost
    p = products.copy()
    idx = rng.choice(p.index, 18, replace=False)
    variants = {"Dairy": "dairy", "Fresh Produce": "Fresh produce", "Beverages": "BEVERAGES ", "Staples": "staples",
                "Snacks & Confectionery": "Snacks and Confectionery", "Personal Care": "Personal care",
                "Household & Cleaning": "Household & cleaning", "Bakery": " Bakery", "Meat & Poultry": "Meat and Poultry",
                "Baby Care": "baby care"}
    p.loc[idx, "category"] = p.loc[idx, "category"].map(variants)
    m["products_inconsistent_category"] = len(idx)
    idx = rng.choice(p.index, 12, replace=False)
    p.loc[idx, "product_name"] = p.loc[idx, "product_name"] + "  "
    m["products_trailing_whitespace"] = len(idx)
    idx = rng.choice(p.index, 6, replace=False)
    p.loc[idx, "brand"] = None
    m["products_missing_brand"] = len(idx)
    idx = rng.choice(p.index, 3, replace=False)
    p.loc[idx, "unit_cost"] = None
    m["products_missing_unit_cost"] = len(idx)

    # customers: missing county, case issues, placeholder dates, exact duplicates
    c = customers.copy()
    idx = rng.choice(c.index, int(len(c) * 0.04), replace=False)
    c.loc[idx, "county"] = None
    m["customers_missing_county"] = len(idx)
    idx = rng.choice(c.index, 150, replace=False)
    c.loc[idx, "customer_segment"] = c.loc[idx, "customer_segment"].str.upper()
    m["customers_segment_case"] = len(idx)
    idx = rng.choice(c.index, 7, replace=False)
    c.loc[idx, "registration_date"] = pd.Timestamp("1900-01-01")
    m["customers_placeholder_date"] = len(idx)
    dup = c.sample(90, random_state=1)
    c = pd.concat([c, dup], ignore_index=True)
    m["customers_exact_duplicates"] = 90

    # transactions: duplicates, orphan branch, invalid future dates, payment labels, nulls
    x = tx.copy()
    pay_variants = {"Mobile Money": ["mobile money", "MOBILE MONEY", "M-Money"], "Card": ["card", "CARD "], "Cash": ["CASH", "cash "]}
    idx = rng.choice(x.index, int(len(x) * 0.05), replace=False)
    x.loc[idx, "payment_method"] = [rng.choice(pay_variants.get(v, [v])) for v in x.loc[idx, "payment_method"]]
    m["transactions_payment_label_variants"] = len(idx)
    idx = rng.choice(x.index, int(len(x) * 0.02), replace=False)
    x.loc[idx, "payment_method"] = None
    m["transactions_missing_payment"] = len(idx)
    idx = rng.choice(x.index, 40, replace=False)
    x.loc[idx, "branch_id"] = "BR99"
    m["transactions_orphan_branch"] = len(idx)
    orphan_tx = set(x.loc[idx, "transaction_id"])
    idx = rng.choice(x.index.difference(idx), 25, replace=False)
    x["transaction_ts"] = x["transaction_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    x.loc[idx, "transaction_ts"] = x.loc[idx, "transaction_ts"].str.replace(r"^2026", "2062", regex=True).str.replace(r"^2025", "2052", regex=True)
    m["transactions_invalid_future_year"] = int(x.loc[idx, "transaction_ts"].str[:2].eq("20").mul(
        x.loc[idx, "transaction_ts"].str[:4].astype(int) > 2030).sum())  # only 2025/2026 rows can be corrupted
    dup = x.sample(int(len(x) * 0.004), random_state=2)
    x = pd.concat([x, dup], ignore_index=True)
    m["transactions_exact_duplicates"] = len(dup)

    # items: duplicates, typo quantities, zero prices, returns
    it = items.copy()
    seg_map = dict(zip(customers["customer_id"], customers["customer_segment"]))
    tx_seg = tx.set_index("transaction_id")["customer_id"].map(seg_map).fillna("Anonymous")
    non_sb = it["transaction_id"].map(tx_seg) != "Small Business"
    idx = rng.choice(it.index[non_sb], 60, replace=False)
    it.loc[idx, "quantity"] = it.loc[idx, "quantity"] * 100
    m["items_quantity_typo_x100"] = len(idx)
    idx = rng.choice(it.index, 35, replace=False)
    it.loc[idx, "unit_price"] = 0.0
    m["items_zero_price"] = len(idx)
    ret = it.sample(int(len(it) * 0.0025), random_state=3).copy()
    ret["quantity"] = -ret["quantity"].clip(upper=3)
    ret["discount_amount"] = 0.0
    ret["promotion_id"] = None
    ret["transaction_item_id"] = np.arange(it["transaction_item_id"].max() + 1, it["transaction_item_id"].max() + 1 + len(ret))
    it = pd.concat([it, ret], ignore_index=True)
    m["items_return_lines"] = len(ret)
    dup = it.sample(int(len(it) * 0.003), random_state=4)
    it = pd.concat([it, dup], ignore_index=True)
    m["items_exact_duplicates"] = len(dup)

    # inventory: duplicates and negative stock
    iv = inv.copy()
    idx = rng.choice(iv.index, 50, replace=False)
    iv.loc[idx, "stock_quantity"] = -rng.integers(1, 6, 50)
    m["inventory_negative_stock"] = 50
    dup = iv.sample(int(len(iv) * 0.002), random_state=5)
    iv = pd.concat([iv, dup], ignore_index=True)
    m["inventory_exact_duplicates"] = len(dup)

    # promotions: swapped dates
    pr = promotions.copy()
    idx = rng.choice(pr.index, 2, replace=False)
    pr.loc[idx, ["start_date", "end_date"]] = pr.loc[idx, ["end_date", "start_date"]].to_numpy()
    m["promotions_swapped_dates"] = 2
    m["orphan_transaction_ids_sample"] = sorted(orphan_tx)[:5]
    return p, c, x, it, iv, pr, m


def main(seed: int = 2027) -> dict:
    rng = np.random.default_rng(seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    branches = build_branches()
    products = build_products(rng)
    customers = build_customers(rng, branches)
    promotions = build_promotions(rng, products)
    tx = build_transactions(rng, branches, customers)
    li, collapse_idx = build_lines(rng, tx, products, branches, customers, promotions)
    li, inv, sim_meta = simulate_inventory(rng, li, tx, products, branches, collapse_idx)

    # Assemble final line items
    li = li.sort_values(["tx_idx", "p_idx"]).reset_index(drop=True)
    li["transaction_id"] = tx["transaction_id"].to_numpy()[li["tx_idx"]]
    li["discount_amount"] = np.round(li["quantity"] * li["unit_price"] * li["disc_rate"], 2)
    items = li[["transaction_id", "product_id", "quantity", "unit_price", "discount_amount", "promotion_id"]].copy()
    items.insert(0, "transaction_item_id", np.arange(1, len(items) + 1))
    # drop transactions whose every line was lost to stockouts
    tx = tx[tx["transaction_id"].isin(items["transaction_id"].unique())].copy()

    # registration must precede first purchase
    first = tx.dropna(subset=["customer_id"]).groupby("customer_id")["date"].min()
    customers = customers.set_index("customer_id")
    late = first[first < customers.loc[first.index, "registration_date"]].index
    customers.loc[late, "registration_date"] = first[late] - pd.to_timedelta(rng.integers(0, 60, len(late)), unit="D")
    customers = customers.reset_index()

    br_out = branches[["branch_id", "branch_name", "county", "town", "branch_type", "opening_date"]]
    pr_out = products[["product_id", "product_name", "category", "brand", "unit_cost"]]
    cu_out = customers[["customer_id", "customer_segment", "registration_date", "county"]]
    tx_out = tx[["transaction_id", "transaction_ts", "branch_id", "customer_id", "payment_method"]]

    p, c, x, it, iv, pr, manifest = inject_issues(rng, None, pr_out, cu_out, tx_out, items, inv, promotions, branches)
    br_out.to_csv(OUT_DIR / "branches.csv", index=False)
    p.to_csv(OUT_DIR / "products.csv", index=False)
    c.to_csv(OUT_DIR / "customers.csv", index=False, date_format="%Y-%m-%d")
    x.to_csv(OUT_DIR / "transactions.csv", index=False)
    it.to_csv(OUT_DIR / "transaction_items.csv", index=False)
    iv.to_csv(OUT_DIR / "inventory.csv", index=False, date_format="%Y-%m-%d")
    pr.to_csv(OUT_DIR / "promotions.csv", index=False, date_format="%Y-%m-%d")

    manifest.update({
        "seed": seed, "period": [str(START.date()), str(END.date())],
        "clean_row_counts": {"branches": len(br_out), "products": len(pr_out), "customers": len(cu_out),
                             "transactions": len(tx_out), "transaction_items": len(items),
                             "inventory": len(inv), "promotions": len(promotions)},
        "simulation": {"demand_units": sim_meta["demand_units"], "lost_units_due_to_stockout": sim_meta["lost_units"],
                       "over_ordered_product_count": len(sim_meta["over_ordered_products"]),
                       "stale_reorder_branch_product_pairs": sim_meta["stale_reorder_pairs"]},
        "note": "Synthetic data for a fictional chain. Counts above describe injected issues for cleaning validation.",
    })
    (OUT_DIR / "injection_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2027)
    args = ap.parse_args()
    out = main(args.seed)
    print(json.dumps(out["clean_row_counts"], indent=2))
    print(json.dumps(out["simulation"], indent=2))
