"""Write the seven analysis notebooks (as code, so they are reviewable in git), then execute them.

    python scripts/build_notebooks.py            # write + execute
    python scripts/build_notebooks.py --no-run   # write only
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import nbformat as nbf

NB_DIR = Path(__file__).resolve().parents[1] / "notebooks"

SETUP = """import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path.cwd().parent))   # project root, so `src` is importable
import numpy as np, pandas as pd, matplotlib.pyplot as plt, seaborn as sns
from src.data_loader import get_engine, query, PROJECT_ROOT
from src import analysis as an
an.set_style()
pd.set_option("display.float_format", "{:,.2f}".format)
pd.set_option("display.max_columns", 30)
engine = get_engine()"""


def md(s): return nbf.v4.new_markdown_cell(s.strip())
def code(s): return nbf.v4.new_code_cell(s.strip())


NOTEBOOKS: dict[str, list] = {}

# ---------------------------------------------------------------------------------------------
NOTEBOOKS["01_data_understanding"] = [
    md("""# 01 · Data understanding
**Project:** Kenya Retail Intelligence. **Company:** *Savanna Fresh Supermarkets* (fictional).

> All transaction-level data in this project is **synthetic**, produced by `src/generate_data.py` for a fictional chain.
> It does not describe any real retailer. Public datasets were reviewed first (see `reports/methodology.md`); none were
> Kenyan, store-based and complete with cost, inventory and promotion data.

This notebook answers: *what tables do we have, what does one row mean, what period is covered, and how do the tables relate?*"""),
    code(SETUP),
    md("## 1. Row counts and grain\nThe grain (what one row represents) decides how every later aggregation must be written."),
    code("""grain = {
 "branches": "one store", "products": "one SKU (product x brand x pack size)", "customers": "one loyalty member",
 "promotions": "one chain-wide price promotion on one product", "transactions": "one till receipt (basket)",
 "transaction_items": "one product line on a receipt", "returns": "one returned product line",
 "inventory_snapshots": "Sunday closing stock for one product in one branch"}
counts = query(engine, \"\"\"
SELECT 'branches' t, COUNT(*) n FROM retail.branches UNION ALL SELECT 'products', COUNT(*) FROM retail.products
UNION ALL SELECT 'customers', COUNT(*) FROM retail.customers UNION ALL SELECT 'promotions', COUNT(*) FROM retail.promotions
UNION ALL SELECT 'transactions', COUNT(*) FROM retail.transactions UNION ALL SELECT 'transaction_items', COUNT(*) FROM retail.transaction_items
UNION ALL SELECT 'returns', COUNT(*) FROM retail.returns UNION ALL SELECT 'inventory_snapshots', COUNT(*) FROM retail.inventory_snapshots\"\"\")
counts["grain"] = counts["t"].map(grain)
counts"""),
    md("## 2. Column types (clean `retail` schema)"),
    code("""cols = query(engine, \"\"\"SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns WHERE table_schema = 'retail' AND table_name NOT LIKE 'v_%%'
ORDER BY table_name, ordinal_position\"\"\")
cols.groupby("table_name").apply(lambda g: ", ".join(f"{c} ({t})" for c, t in zip(g.column_name, g.data_type))).to_frame("columns")"""),
    md("## 3. Master data"),
    code("query(engine, 'SELECT * FROM retail.branches ORDER BY branch_id')"),
    code("""prod = query(engine, 'SELECT category, COUNT(*) AS skus, COUNT(DISTINCT brand) AS brands, ROUND(AVG(unit_cost),0) AS avg_unit_cost FROM retail.products GROUP BY category ORDER BY skus DESC')
prod"""),
    code("query(engine, 'SELECT customer_segment, COUNT(*) AS customers FROM retail.customers GROUP BY 1 ORDER BY 2 DESC')"),
    md("## 4. Period coverage\nTwo complete years, November 2024 to October 2026. Ruiru (BR10) opened on 2 June 2025, so it has no full comparison year, and like-for-like comparisons exclude it."),
    code("""query(engine, \"\"\"SELECT branch_id, MIN(transaction_ts)::date AS first_sale, MAX(transaction_ts)::date AS last_sale,
 COUNT(*) AS transactions FROM retail.transactions GROUP BY 1 ORDER BY 1\"\"\")"""),
    md("## 5. A sample basket, end to end\nFollowing one receipt through the joins is the quickest way to check that the relationships behave as expected."),
    code("""tid = query(engine, "SELECT transaction_id FROM retail.transactions WHERE customer_id IS NOT NULL ORDER BY transaction_id LIMIT 1 OFFSET 5000").iloc[0, 0]
query(engine, \"\"\"SELECT t.transaction_id, t.transaction_ts, b.branch_name, c.customer_segment, t.payment_method,
  p.product_name, ti.quantity, ti.unit_price, ti.discount_amount, ti.promotion_id
FROM retail.transactions t JOIN retail.branches b USING (branch_id)
LEFT JOIN retail.customers c USING (customer_id)
JOIN retail.transaction_items ti USING (transaction_id) JOIN retail.products p USING (product_id)
WHERE t.transaction_id = :tid\"\"\", tid=tid)"""),
    md("""## 6. Relationships
```
branches 1──* transactions *──0..1 customers
transactions 1──* transaction_items *──1 products
transaction_items *──0..1 promotions *──1 products
branches 1──* inventory_snapshots *──1 products
```
`customer_id` is nullable because about 38% of baskets are not scanned with a loyalty card. Customer-level analysis therefore covers only identified baskets, while revenue analysis covers all of them.

**Takeaways for the next steps:** analysis must aggregate lines before counting baskets (fan-out risk), compare branches like-for-like because of BR10, and treat customer metrics as a loyalty-member subset."""),
]

# ---------------------------------------------------------------------------------------------
NOTEBOOKS["02_data_quality_assessment"] = [
    md("""# 02 · Data quality assessment
Profiling the **raw staging layer** before deciding any cleaning rule. Each issue is quantified, its business impact is stated,
and a rule is proposed. The rules are implemented in `src/data_cleaning.py` and applied in notebook 03."""),
    code(SETUP),
    md("## 1. Duplicates\nDistinct keys versus raw rows. Duplicate keys whose content is identical are safe to drop; keys with *different* content would need a business decision."),
    code("an.sql_output('dq_a01_row_counts').assign(extra_rows=lambda d: d.raw_rows - d.distinct_keys)"),
    code("an.sql_output('dq_a02_exact_duplicate_items')"),
    md("All duplicated item keys are exact copies (`conflicting_keys = 0`). Left in, they would overstate revenue by roughly the duplicate share, so the rule is **drop exact copies and fail loudly on conflicts**."),
    md("## 2. Missing values"),
    code("an.sql_output('dq_a03_missing_values').assign(pct=lambda d: 100*d.missing/d.total)"),
    md("""- **Anonymous baskets** (`customer_id` NULL) are *not* an error. They are cash or card customers without a loyalty card, so they are kept.
- **Missing payment method** (about 2%): kept as `Unknown`. It does not affect revenue.
- **Missing unit_cost** (3 SKUs): gross profit cannot be computed for these, so cost is imputed from the category's median cost-to-price ratio and **flagged** (`unit_cost_imputed`).
- **Missing customer county** (4%): left NULL and reported as Unknown. Imputing it from the home branch would be a guess."""),
    md("## 3. Inconsistent labels"),
    code("an.sql_output('dq_a04_category_labels')"),
    code("an.sql_output('dq_a05_payment_labels')"),
    md("Ten real categories appear under 19 spellings. Without standardisation a category chart would split Dairy across three bars. Rule: map to the canonical list by case-, whitespace- and '&'/'and'-insensitive matching, and **stop if any label cannot be mapped**."),
    md("## 4. Invalid dates and orphan keys"),
    code("an.sql_output('dq_a06_invalid_dates')"),
    code("an.sql_output('dq_a07_orphan_keys')"),
    md("Years such as 2052 and 2062 are clearly keying errors (digits transposed). They *could* be corrected, but which digit is wrong is a guess, so they are **quarantined**. The 40 receipts pointing to branch `BR99` cannot be attributed to a store and are also quarantined, together with their lines."),
    md("## 5. Quantity outliers: investigate, don't delete\nThe key question: which large quantities are real bulk purchases, and which are errors?"),
    code("an.sql_output('dq_a08_quantity_profile')"),
    code("""q = query(engine, \"\"\"SELECT i.quantity::int AS quantity, COALESCE(c.customer_segment, 'Anonymous') AS segment
FROM staging.transaction_items i
JOIN (SELECT DISTINCT ON (transaction_id) transaction_id, customer_id FROM staging.transactions) t USING (transaction_id)
LEFT JOIN (SELECT DISTINCT ON (customer_id) customer_id, initcap(customer_segment) AS customer_segment FROM staging.customers) c USING (customer_id)
WHERE i.quantity::int > 10\"\"\")
q["segment"] = q["segment"].str.title()
summary = q.groupby("segment").quantity.describe(percentiles=[.5, .99])
summary"""),
    code("""fig, ax = plt.subplots(figsize=(8, 3.6))
sb = q[q.segment == "Small Business"].quantity
other = q[q.segment != "Small Business"].quantity
bins = np.logspace(np.log10(11), np.log10(q.quantity.max() + 1), 40)
ax.hist(sb, bins=bins, color=an.PRIMARY, label="Small Business baskets", alpha=.9)
ax.hist(other, bins=bins, color=an.HIGHLIGHT, label="Other baskets", alpha=.9)
ax.set_xscale("log"); ax.axvline(100, color=an.INK_MUTED, ls="--", lw=1)
ax.text(105, ax.get_ylim()[1]*.85, "rule threshold = 100", color=an.INK_MUTED, fontsize=9)
ax.set_xlabel("Units of one product on one line (log scale, lines > 10 units only)"); ax.set_ylabel("Lines")
ax.set_title("Large quantities: real bulk buying vs keying errors"); ax.legend()
an.save(fig, "dq_quantity_outliers");"""),
    md("""**Finding.** Small Business customers legitimately buy up to about 50 units of a staple. Every line from a *non-business* basket with more than 10 units sits at 100 or above, a clean ×100 pattern (2 typed as 200). Rule: quarantine lines with quantity ≥ 100 **unless** the basket belongs to a Small Business customer. Bulk lines are kept, because deleting them would understate Staples sales to the trade segment.

Negative quantities (-1 to -3) are **returns**. They move to `retail.returns`, so they neither inflate nor offset sales revenue."""),
    md("## 6. Prices, inventory and promotions"),
    code("pd.concat([an.sql_output('dq_a09_zero_or_negative_prices'), an.sql_output('dq_a10_inventory_anomalies')], axis=1)"),
    code("an.sql_output('dq_a11_promotion_date_logic')"),
    md("""| Issue | Rule | Why |
|---|---|---|
| Zero unit price (35 lines) | impute the product's modal shelf price, flag `price_imputed` | shelf prices are stable per SKU; zero would understate revenue and make margin −100% |
| Negative closing stock (50 rows) | set to 0 and log it | stock cannot physically be negative; it happens when sales post before goods are receipted |
| Promotion end date before start date (2) | swap the dates | the duration and product are valid, only the order is wrong |

## 7. Cross-check against the generator's injection manifest
Because the data is synthetic, the generator recorded what it injected. Detection should match it."""),
    code("""manifest = json.loads((PROJECT_ROOT / "data/synthetic/raw/injection_manifest.json").read_text())
log = an.sql_output("dq_b03_exception_log")
pairs = [("items_exact_duplicates", "transaction_items", "exact duplicate row"),
         ("items_return_lines", "transaction_items", "negative quantity"),
         ("items_quantity_typo_x100", "transaction_items", "quantity >= 100 on non-business basket"),
         ("items_zero_price", "transaction_items", "zero unit_price"),
         ("transactions_exact_duplicates", "transactions", "exact duplicate row"),
         ("transactions_orphan_branch", "transactions", "branch_id not in branch master"),
         ("transactions_invalid_future_year", "transactions", "timestamp outside data period (likely year typo)"),
         ("inventory_negative_stock", "inventory", "negative stock count (sold before receipt posted)"),
         ("customers_exact_duplicates", "customers", "exact duplicate row"),
         ("products_missing_unit_cost", "products", "missing unit_cost")]
rows = []
for key, tbl, issue in pairs:
    found = log[(log.source_table == tbl) & (log.issue == issue)].records.sum()
    rows.append({"injected_issue": key, "injected": manifest[key], "detected_and_handled": found})
pd.DataFrame(rows).assign(match=lambda d: d.injected == d.detected_and_handled)"""),
    md("Every injected problem is detected and handled, and the counts match. The quantity rule caught exactly the injected keying errors and none of the genuine bulk lines. This check is possible only because the data is synthetic; with real data, the equivalent is a sample audit with the business."),
]

# ---------------------------------------------------------------------------------------------
NOTEBOOKS["03_data_cleaning"] = [
    md("""# 03 · Data cleaning
Applies the rules from notebook 02. The production run is `python -m src.pipeline`, which reads staging, calls the functions
in `src/data_cleaning.py`, loads `retail.*` and writes every change to `retail.dq_exceptions`. This notebook re-runs the same
functions in memory to show *before vs after*, then proves the clean layer passes its integrity checks."""),
    code(SETUP + "\nfrom src import data_cleaning as dc"),
    code("""raw = {t: query(engine, f"SELECT * FROM staging.{t}") for t in
       ["branches", "products", "customers", "promotions", "transactions", "transaction_items", "inventory"]}
{k: len(v) for k, v in raw.items()}"""),
    md("## 1. Products: label standardisation and cost imputation"),
    code("""products, e1 = dc.clean_products(raw["products"], raw["transaction_items"])
before = raw["products"]["category"].nunique(); after = products["category"].nunique()
print(f"category labels: {before} -> {after}")
products[products.unit_cost_imputed]"""),
    md("## 2. Customers, promotions and transactions"),
    code("""customers, e2 = dc.clean_customers(raw["customers"])
promotions, e3 = dc.clean_promotions(raw["promotions"])
branches, _ = dc.clean_branches(raw["branches"])
tx, tx_q, e4 = dc.clean_transactions(raw["transactions"], set(branches.branch_id), set(customers.customer_id))
print("customers", len(raw["customers"]), "->", len(customers))
print("transactions", len(raw["transactions"]), "->", len(tx), "| quarantined:", len(tx_q))
tx["payment_method"].value_counts()"""),
    md("## 3. Line items: duplicates, returns, keying errors and zero prices"),
    code("""items, returns, items_q, e5 = dc.clean_items(raw["transaction_items"], tx, customers,
                                           set(products.product_id), set(promotions.promotion_id))
print("raw lines", len(raw["transaction_items"]), "| sales lines", len(items), "| returns", len(returns), "| quarantined", len(items_q))
raw_q = pd.to_numeric(raw["transaction_items"].quantity); raw_p = pd.to_numeric(raw["transaction_items"].unit_price)
raw_value = (raw_q * raw_p).sum(); clean_value = (items.quantity * items.unit_price).sum()
print(f"gross line value: raw {an.kes(raw_value)} -> clean {an.kes(clean_value)} ({100*(raw_value/clean_value-1):+.2f}% overstatement removed)")"""),
    md("Most of the overstatement in the raw export comes from the 60 ×100 quantity typos and the duplicate lines. Left uncleaned, those few rows would have inflated reported sales."),
    code("""fig, ax = plt.subplots(figsize=(7.5, 3.2))
impact = pd.Series({"Raw export": raw_value, "after removing duplicates": None, "Clean sales lines": clean_value})
dup_value = (lambda d: (pd.to_numeric(d.quantity) * pd.to_numeric(d.unit_price)).sum())(raw["transaction_items"].drop_duplicates())
vals = [raw_value, dup_value, clean_value]; labels = ["Raw export", "Exact duplicates removed", "Clean (typos, returns, orphans handled)"]
ax.barh(labels[::-1], vals[::-1], color=[an.PRIMARY, an.CONTEXT, an.CONTEXT], height=.55)
for i, v in enumerate(vals[::-1]): ax.text(v, i, f"  {an.kes(v)}", va="center", fontsize=9)
ax.set_xlim(min(vals) * .97, max(vals) * 1.03); an.kes_axis(ax, "x")
ax.set_title("Gross line value at each cleaning step"); ax.grid(axis="y", visible=False)
an.save(fig, "cleaning_value_impact");"""),
    md("## 4. Inventory"),
    code("""inv, e6 = dc.clean_inventory(raw["inventory"], set(products.product_id), set(branches.branch_id))
print("inventory rows", len(raw["inventory"]), "->", len(inv), "| negatives corrected:", sum(1 for x in e6 if x[2].startswith("negative")))"""),
    md("## 5. The exception log (written by the pipeline)"),
    code("an.sql_output('dq_b03_exception_log')"),
    md("## 6. Clean-layer validation: every check must be 0"),
    code("""checks = an.sql_output("dq_b01_integrity_summary")
assert checks.failures.sum() == 0, checks[checks.failures > 0]
checks"""),
    code("an.sql_output('dq_b02_join_fanout_check')"),
    md("The sales view has exactly as many rows as the line table, so the joins to transactions and products do not fan out. Every downstream total can be trusted not to double-count."),
]

# ---------------------------------------------------------------------------------------------
NOTEBOOKS["04_exploratory_data_analysis"] = [
    md("# 04 · Exploratory data analysis\nDistributions, time patterns, outliers and relationships, looked at before any business conclusions are drawn."),
    code(SETUP),
    code("""baskets = query(engine, "SELECT b.*, br.branch_type, COALESCE(c.customer_segment,'Anonymous') AS segment FROM retail.v_baskets b JOIN retail.branches br USING (branch_id) LEFT JOIN retail.customers c USING (customer_id)")
for c in ["basket_revenue", "basket_gross_profit"]: baskets[c] = baskets[c].astype(float)
baskets.basket_revenue.describe(percentiles=[.25, .5, .75, .95, .99])"""),
    md("## 1. Basket value distribution\nThe distribution is strongly right-skewed: the mean sits above the median, so **ATV is pulled up by a minority of large baskets**. This is why the dashboard shows the median next to the mean."),
    code("""fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
ax = axes[0]
ax.hist(baskets.basket_revenue, bins=np.logspace(1.3, np.log10(baskets.basket_revenue.max()), 60), color=an.PRIMARY)
ax.set_xscale("log"); ax.set_xlabel("Basket value, KES (log scale)"); ax.set_ylabel("Baskets")
ax.axvline(baskets.basket_revenue.median(), color=an.INK, lw=1, ls="--"); ax.axvline(baskets.basket_revenue.mean(), color=an.HIGHLIGHT, lw=1.5)
ax.text(baskets.basket_revenue.median(), ax.get_ylim()[1]*.92, " median", fontsize=9); ax.text(baskets.basket_revenue.mean(), ax.get_ylim()[1]*.8, " mean", color=an.HIGHLIGHT, fontsize=9)
ax.set_title("Basket value is right-skewed")
ax = axes[1]
order = ["Express", "Supermarket", "Hypermarket"]
sns.boxplot(data=baskets, x="branch_type", y="basket_revenue", order=order, ax=ax, color=an.SEQ_BLUES[2], showfliers=False, width=.5)
ax.set_xlabel(""); ax.set_ylabel("Basket value, KES"); ax.set_title("Bigger formats, bigger baskets (outliers hidden)")
fig.tight_layout(); an.save(fig, "eda_basket_distribution");"""),
    code("baskets.groupby('segment').agg(baskets=('transaction_id','count'), median_value=('basket_revenue','median'), mean_value=('basket_revenue','mean'), mean_units=('units','mean')).sort_values('mean_value', ascending=False)"),
    md("## 2. Outliers: who are the largest baskets?"),
    code("""top = baskets.nlargest(200, "basket_revenue")
top.segment.value_counts(normalize=True).mul(100).round(1).to_frame("% of top-200 baskets")"""),
    md("All of the 200 largest baskets belong to Small Business customers (kiosk owners restocking). They are **genuine and kept**, and they are a segment to serve deliberately rather than noise to remove."),
    md("## 3. Time patterns"),
    code("""m = an.sql_output("q02_monthly_revenue_mom"); m["sale_month"] = pd.to_datetime(m["sale_month"])
fig, ax = plt.subplots(figsize=(10, 3.6))
ax.plot(m.sale_month, m.revenue_kes, color=an.PRIMARY, marker="o", ms=4, label="Monthly revenue")
ax.plot(m.sale_month, m.revenue_3m_avg_kes, color=an.CONTEXT, lw=1.5, label="3-month average")
for _, r in m[m.sale_month.dt.month == 12].iterrows():
    ax.annotate("December peak", (r.sale_month, r.revenue_kes), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8, color=an.INK_MUTED)
an.kes_axis(ax); ax.set_ylabel("Net revenue (KES)"); ax.set_title("Monthly net revenue, Nov 2024 – Oct 2026"); ax.legend(loc="upper left")
an.save(fig, "eda_monthly_revenue");"""),
    code("""hm = query(engine, "SELECT EXTRACT(ISODOW FROM transaction_ts)::int AS dow, EXTRACT(HOUR FROM transaction_ts)::int AS hour, COUNT(*) AS n FROM retail.transactions GROUP BY 1,2")
pivot = hm.pivot(index="dow", columns="hour", values="n")
days = query(engine, "SELECT iso_dow AS dow, COUNT(*) AS days FROM retail.v_dim_date GROUP BY 1").set_index("dow").days
pivot = pivot.div(days, axis=0)   # average transactions per calendar day, per hour
pivot.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
fig, ax = plt.subplots(figsize=(10, 3.4))
sns.heatmap(pivot, cmap=sns.color_palette(an.SEQ_BLUES, as_cmap=True), ax=ax, cbar_kws={"label": "avg transactions per day (chain)"}, linewidths=.5, linecolor="white")
ax.set_xlabel("Hour of day"); ax.set_ylabel(""); ax.set_title("When customers shop: weekday evenings and Saturday midday")
an.save(fig, "eda_dow_hour_heatmap");"""),
    md("## 4. Relationships between variables"),
    code("""print("Spearman correlation, basket units vs basket value:", round(baskets[["units", "basket_revenue"]].corr(method="spearman").iloc[0, 1], 3))
lines = an.load_sales_lines(engine, "product_id, category, quantity, gross_sales, discount_amount, net_revenue, gross_profit")
prod = lines.groupby(["product_id", "category"]).agg(rev=("net_revenue", "sum"), gp=("gross_profit", "sum"), disc=("discount_amount", "sum"), gs=("gross_sales", "sum")).reset_index()
prod["margin"] = 100 * prod.gp / prod.rev; prod["disc_rate"] = 100 * prod.disc / prod.gs
fig, ax = plt.subplots(figsize=(9, 4))
cats = prod.groupby("category").rev.sum().sort_values(ascending=False).index
hi = {"Staples": an.HIGHLIGHT, "Fresh Produce": an.SECOND}
for c in cats:
    d = prod[prod.category == c]
    ax.scatter(d.rev, d.margin, s=22, color=hi.get(c, an.CONTEXT), label=c if c in hi else None, edgecolor="white", lw=.5, zorder=3 if c in hi else 2)
ax.set_xscale("log"); ax.set_xlabel("Product revenue over 2 years, KES (log scale)"); ax.set_ylabel("Gross margin %")
ax.scatter([], [], color=an.CONTEXT, label="Other categories"); ax.legend(loc="upper right")
ax.set_title("High-revenue products are mostly low-margin Staples")
an.save(fig, "eda_revenue_vs_margin");
print("Spearman correlation, product revenue vs margin:", round(prod[["rev", "margin"]].corr(method="spearman").iloc[0, 1], 3))"""),
    md("""**Observations to carry forward**
1. Revenue is seasonal: December is the peak, January dips, and paydays and weekends lift daily sales. Comparisons should be year-over-year, not month-over-month, where seasonality matters.
2. Product revenue and margin are **negatively correlated**. The biggest sellers (cooking oil, sugar, flour) carry single-digit margins, so *revenue rank is a poor guide to profit contribution*.
3. Large baskets are real Small Business purchases, a segment worth managing explicitly."""),
]

# ---------------------------------------------------------------------------------------------
NOTEBOOKS["05_sales_and_profitability_analysis"] = [
    md("# 05 · Sales and profitability analysis\nBusiness questions 1–13. The SQL results (`reports/sql_outputs`) are the source of truth; pandas is used for charts and statistical tests."),
    code(SETUP + "\nfrom scipy import stats"),
    md("## 1. Headline KPIs (Q1)"),
    code("an.sql_output('q01_headline_kpis').T.rename(columns={0: 'value'})"),
    md("## 2. Growth: headline vs like-for-like (Q2)"),
    code("an.sql_output('q03_year_over_year')"),
    md("Part of the headline growth is simply Ruiru opening. Like-for-like growth is the honest measure of how the existing estate performed."),
    md("## 3. Branches and counties (Q3, Q4, Q11)"),
    code("""b = an.sql_output("q04_branch_ranking")
g = an.sql_output("q11_branch_growth_trend")[["branch_id", "yoy_growth_pct"]]
b = b.merge(g, on="branch_id")
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
order = b.sort_values("revenue_kes").branch_name.str.replace("Savanna Fresh ", "")
bb = b.set_index(b.branch_name.str.replace("Savanna Fresh ", "")).loc[order]
axes[0].barh(order, bb.revenue_kes, color=an.PRIMARY, height=.6); an.kes_axis(axes[0], "x"); axes[0].set_title("Net revenue, 2 years (KES)")
cols = [an.HIGHLIGHT if v < 0 else an.PRIMARY for v in bb.yoy_growth_pct.fillna(0)]
axes[1].barh(order, bb.yoy_growth_pct.fillna(0), color=cols, height=.6); axes[1].axvline(0, color=an.INK_MUTED, lw=.8)
axes[1].set_title("Revenue growth, Year 2 vs Year 1 (%)")
axes[1].text(1, list(order).index("Ruiru"), "opened Jun 2025: n/a", va="center", fontsize=8, color=an.INK_MUTED)
for a in axes: a.grid(axis="y", visible=False)
fig.tight_layout(); an.save(fig, "branch_revenue_growth");
an.sql_output("q05_county_contribution")"""),
    md("Machakos (BR12) is the only established branch with falling sales, and its latest quarter is worse than its annual decline. Mombasa has the highest revenue per branch, but also the lowest county margin, which points to Nyali (next section)."),
    md("## 4. Categories: revenue share vs profit share (Q5, Q13)"),
    code("""c = an.sql_output("q15_category_performance").sort_values("revenue_share_pct")
fig, ax = plt.subplots(figsize=(9, 4.2))
y = np.arange(len(c))
ax.barh(y + .2, c.revenue_share_pct, height=.38, color=an.CONTEXT, label="Share of revenue")
ax.barh(y - .2, c.gp_share_pct, height=.38, color=an.PRIMARY, label="Share of gross profit")
ax.set_yticks(y, c.category); ax.set_xlabel("% of chain total"); ax.legend(loc="lower right"); ax.grid(axis="y", visible=False)
ax.set_title("Staples drive revenue; Fresh, Household and Beverages drive profit")
an.save(fig, "category_revenue_vs_profit_share");
c.sort_values("lfl_gp_growth_pct")[["category", "gross_margin_pct", "revenue_share_pct", "gp_share_pct", "lfl_revenue_growth_pct", "lfl_gp_growth_pct"]]"""),
    md("""**Underperforming categories**
- **Household & Cleaning** is the only category whose like-for-like revenue *and* gross profit fell year-on-year, although it is the third-largest profit contributor. Notebook 06 links this to two SKUs whose sales collapsed while stock kept arriving.
- **Snacks & Confectionery** grew far below the chain average.
- **Staples** are 31% of revenue but only about 17% of gross profit at a 9.9% margin. This is a traffic-driver category, not a problem in itself, but it is where every point of discount hurts most."""),
    md("## 5. High revenue, low margin products (Q9, Q10)"),
    code("an.sql_output('q13_high_revenue_low_margin').head(12)"),
    md("## 6. Why is Nyali's margin lowest? (Q11)\nMargin can differ because of **product mix** (what is sold) or **price realisation** (discounts). The margin bridge separates the two."),
    code("""d = an.sql_output("q16_branch_margin_drivers").sort_values("gross_margin_pct")
d[["branch_name", "margin_before_discounts_pct", "promo_discount_pct_of_sales", "non_promo_discount_pct_of_sales", "gross_margin_pct", "pct_lines_non_promo_discounted", "non_promo_discount_kes"]]"""),
    code("an.sql_output('q17_non_promo_discount_by_category_branch').head(4)"),
    md("Nyali's *mix* margin before discounts (19.8%) is in line with the other branches. The gap comes entirely from **non-promotional discounts**: 2.58% of sales against about 0.4% elsewhere, on 17.8% of lines against about 2.2%. Elsewhere, non-promotional discounts are perishable markdowns only. At Nyali, 1.59% of sales goes to discounts on ambient (non-perishable) goods, which have no expiry reason to be marked down. This pattern is consistent with manual price overrides at the till."),
    code("""ml = query(engine, \"\"\"SELECT branch_id, sale_month, SUM(gross_profit)/SUM(net_revenue)*100 AS gm
FROM retail.v_sales_lines GROUP BY 1,2\"\"\")
ml["gm"] = ml.gm.astype(float)
nyali = ml[ml.branch_id == "BR04"].gm; others = ml[ml.branch_id != "BR04"].groupby("sale_month").gm.mean()
t = stats.ttest_ind(nyali.values, others.values, equal_var=False)
print(f"Monthly gross margin, Nyali mean {nyali.mean():.2f}% vs other-branch average {others.mean():.2f}%")
print(f"Welch t = {t.statistic:.1f}, p = {t.pvalue:.2e}  (24 months each)")
print("Months in which Nyali had the lowest margin of all 12 branches:",
      (ml.pivot(index="sale_month", columns="branch_id", values="gm").idxmin(axis=1) == "BR04").sum(), "of 24")"""),
    md("The gap is not month-to-month noise: Nyali's margin is lower in practically every month, and the difference is statistically decisive. The test treats months as independent, which is approximately reasonable here."),
    md("## 7. Promotions (Q12, Q21)"),
    code("""p = an.sql_output("q18_promotion_performance")
s = an.sql_output("q19_promotion_summary_by_category")
fig, ax = plt.subplots(figsize=(9, 4.2))
cats = s.category.tolist()
pal = {c: col for c, col in zip(["Snacks & Confectionery", "Staples", "Dairy", "Beverages"], [an.PRIMARY, an.HIGHLIGHT, an.SECOND, an.SERIES[3]])}
for c in p.category.unique():
    d = p[p.category == c]
    ax.scatter(d.unit_uplift_pct, d.incremental_gp_kes, s=30, color=pal.get(c, an.CONTEXT), label=c if c in pal else None, edgecolor="white", lw=.5, zorder=3 if c in pal else 2)
ax.scatter([], [], color=an.CONTEXT, label="Other categories")
ax.axhline(0, color=an.INK_MUTED, lw=.8); ax.set_xlabel("Unit uplift vs 28-day baseline (%)"); ax.set_ylabel("Incremental gross profit (KES)")
ax.set_title("Most promotions lift units but lose gross profit"); ax.legend(fontsize=8, loc="lower left")
an.save(fig, "promotion_uplift_vs_gp");
print(p.outcome.value_counts().to_string()); s"""),
    md("""A promotion pays back only when the extra units' margin exceeds the margin given away on units that would have sold anyway. With a 10% margin, a 15% discount on cooking oil makes *every* unit loss-making, so no level of uplift can recover it. **Snacks & Confectionery** is the only category with a positive net return (high uplift, healthy margin), and Personal Care roughly breaks even. Staples and Dairy promotions destroy the most gross profit.

Caveats: chain-level 28-day baseline; cannibalisation, pantry loading and footfall effects are not measured. Treat this as a screening result to test with controlled promotions, not a final causal estimate."""),
]

# ---------------------------------------------------------------------------------------------
NOTEBOOKS["06_inventory_analysis"] = [
    md("# 06 · Inventory analysis\nBusiness questions 14–18 and 22. Snapshots are Sunday closing-stock counts, and a stockout week means the shelf was empty at the week's close."),
    code(SETUP),
    md("## 1. Turnover by category (Q14)"),
    code("an.sql_output('q20_inventory_turnover_by_category')"),
    md("Personal Care and Household & Cleaning turn least often, holding about 4.5 and 3.3 weeks of stock against about 2 weeks for perishables and staples."),
    md("## 2. Where does the shelf go empty? (Q16)"),
    code("""s = an.sql_output("q24_stockout_rate_by_branch").sort_values("stockout_rate_pct")
fig, ax = plt.subplots(figsize=(9, 4))
names = s.branch_name.str.replace("Savanna Fresh ", "")
cols = [an.HIGHLIGHT if v > 10 else an.PRIMARY for v in s.stockout_rate_pct]
ax.barh(names, s.stockout_rate_pct, color=cols, height=.6)
for i, v in enumerate(s.stockout_rate_pct): ax.text(v, i, f" {v:.1f}%", va="center", fontsize=8.5)
ax.axvline(10, color=an.INK_MUTED, ls="--", lw=.8); ax.text(10.2, -.9, "10% flag", fontsize=8, color=an.INK_MUTED)
ax.set_xlabel("% of product-weeks closing with zero stock"); ax.set_title("Kisumu and Eldoret run out 3–4× more often than the chain"); ax.grid(axis="y", visible=False)
an.save(fig, "stockout_rate_by_branch");"""),
    code("""tr = query(engine, "SELECT branch_id, date_trunc('month', snapshot_date)::date AS m, AVG(is_stockout::int)*100 AS rate FROM retail.v_inventory_weekly GROUP BY 1,2")
tr["rate"] = tr.rate.astype(float); tr["m"] = pd.to_datetime(tr.m)
fig, ax = plt.subplots(figsize=(10, 3.4))
for bid, g in tr.groupby("branch_id"):
    hl = {"BR06": (an.HIGHLIGHT, "Kisumu"), "BR11": (an.SERIES[3], "Eldoret")}
    col, lab = hl.get(bid, (an.CONTEXT, None))
    ax.plot(g.m, g.rate, color=col, lw=2 if lab else 1, label=lab, zorder=3 if lab else 1)
ax.plot([], [], color=an.CONTEXT, lw=1, label="Other branches")
ax.set_ylabel("Stockout rate %"); ax.set_title("The gap is persistent, not a one-off disruption"); ax.legend(loc="upper left", ncol=3)
an.save(fig, "stockout_trend");"""),
    md("The elevated rate holds through the whole period, which points to a structural cause (lead time or replenishment parameters) rather than a single supply disruption."),
    md("## 3. Root cause: reorder levels (Q22)"),
    code("""r = an.sql_output("q27_reorder_level_adequacy")
piv = r.pivot(index="branch_id", columns="reorder_cover_band", values="avg_stockout_rate_pct")
cnt = r.pivot(index="branch_id", columns="reorder_cover_band", values="branch_product_pairs")
display(piv.round(1)); display(cnt)"""),
    md("""Two separate mechanisms appear:
1. **Stale reorder levels everywhere.** In every branch, the SKUs whose reorder level is below 0.75 weeks of demand stock out in roughly 27–55% of weeks (30–40% in most branches), against 2–7% for SKUs with at least 1.25 weeks of cover. These are a small number of pairs per branch, cheap to fix.
2. **Kisumu and Eldoret stock out even when reorder levels look normal** (17–20% in the ≥1.25-week band versus 2–7% elsewhere). The reorder level is the same multiple of demand as elsewhere, so the shortfall is consistent with **longer delivery lead times** to the two western branches. The reorder point has to cover demand during the lead time, and a one-week buffer cannot cover a two-week delivery cycle. Lead time is not in the dataset, so this is an inference to confirm with the supply chain team."""),
    code("an.sql_output('q28_lost_sales_estimate')"),
    md("Estimated gross profit lost to empty shelves (stockout weeks × the pair's normal in-stock weekly profit): Kisumu and Eldoret together account for about KES 2.9M over two years, roughly 48% of the chain-wide estimate of KES 6.0M, although they hold only 15% of sales. The estimate is approximate, because demand during a stockout is unobservable."),
    md("## 4. Slow-moving stock and the Household & Cleaning decline (Q15, Q18)"),
    code("an.sql_output('q22_slow_moving_stock_value')"),
    code("an.sql_output('q23_slow_moving_products').head(8)"),
    code("""ids = ["P0147", "P0134"]
mm = query(engine, \"\"\"SELECT product_id, sale_month, SUM(quantity) AS units FROM retail.v_sales_lines
WHERE product_id IN ('P0147','P0134') GROUP BY 1,2 ORDER BY 2\"\"\")
st = query(engine, \"\"\"SELECT product_id, date_trunc('month', snapshot_date)::date AS m, AVG(stock_sum) AS stock FROM
 (SELECT product_id, snapshot_date, SUM(stock_quantity) AS stock_sum FROM retail.inventory_snapshots WHERE product_id IN ('P0147','P0134') GROUP BY 1,2) x GROUP BY 1,2 ORDER BY 1,2\"\"\")
names = query(engine, "SELECT product_id, product_name FROM retail.products WHERE product_id IN ('P0147','P0134')").set_index("product_id").product_name
fig, axes = plt.subplots(1, 2, figsize=(11, 3.4), sharex=True)
for ax, pid in zip(axes, ids):
    a = mm[mm.product_id == pid]; b = st[st.product_id == pid]
    ax.plot(pd.to_datetime(a.sale_month), a.units, color=an.PRIMARY, label="Units sold per month (chain)")
    ax.plot(pd.to_datetime(b.m), b.stock.astype(float), color=an.HIGHLIGHT, label="Avg units on hand (chain)")
    ax.set_title(names[pid], fontsize=10); ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(__import__("matplotlib.dates", fromlist=["x"]).DateFormatter("%b %y"))
fig.suptitle("Demand collapsed in January 2026; the stock already ordered never sold through", x=0.01, ha="left", fontweight="bold")
fig.tight_layout(); an.save(fig, "slow_movers_collapse");"""),
    md("""Two Household & Cleaning SKUs (*Nyota Clean Toilet Paper 10pk*, *Safi Home Detergent 1kg*) lost most of their demand from January 2026, but stock on hand did not fall with it. They alone hold about KES 384K of the KES 497K slow-moving or no-sale stock, and their sales drop explains Household & Cleaning's year-on-year decline seen in notebook 05.

Overall, slow and no-sale stock is about 5.7% of stock value (about KES 0.5M at cost), so it is not a balance-sheet problem in itself. The bigger cost is the opportunity: the shelf space and cash could hold faster lines. The data cannot say *why* demand collapsed (a competitor product, price, quality), which is a question for the category buyer."""),
    code("an.sql_output('q26_replenishment_watchlist').head(15)"),
]

# ---------------------------------------------------------------------------------------------
NOTEBOOKS["07_business_insights"] = [
    md("# 07 · Business insights and recommendations\nPulls the evidence together into the management view (questions 19–22) and closes with an *optional* forecasting extension."),
    code(SETUP),
    md("## 1. Branch scorecard (Q19)"),
    code("an.sql_output('q29_branch_scorecard')"),
    md("## 2. Category scorecard (Q20)"),
    code("an.sql_output('q30_category_scorecard')"),
    md("## 3. Sizing the opportunities\nEach figure below is computed from the data. The assumptions are stated next to it, so that they can be challenged."),
    code("""d = an.sql_output("q16_branch_margin_drivers").set_index("branch_id")
others_rate = d.drop("BR04").non_promo_discount_pct_of_sales.mean() / 100
gs_nyali = query(engine, "SELECT SUM(gross_sales) FROM retail.v_sales_lines WHERE branch_id='BR04'").iloc[0, 0]
excess = float(gs_nyali) * (d.loc["BR04", "non_promo_discount_pct_of_sales"] / 100 - others_rate)
lost = an.sql_output("q28_lost_sales_estimate").set_index("branch_id")
promo = an.sql_output("q19_promotion_summary_by_category").set_index("category")
slow = an.sql_output("q22_slow_moving_stock_value").set_index("stock_status")
opps = pd.DataFrame([
  ["Bring Nyali non-promo discounting to the chain norm", excess / 2, "excess discount vs other-branch average, per year (2-yr total / 2)"],
  ["Halve stockout-related loss at Kisumu + Eldoret", lost.loc[["BR06", "BR11"], "est_lost_gross_profit_kes"].sum() / 2 / 2, "50% of estimated lost GP, per year"],
  ["Stop GP-negative Staples & Dairy promotions", -promo.loc[["Staples", "Dairy"], "incremental_gp_kes"].sum() / 2, "measured negative incremental GP, per year"],
  ["Clear slow / no-sale stock", slow.loc[["Slow-moving (>26 wks cover)", "No sales in 12 weeks"], "stock_value_kes"].sum(), "one-off cash release at cost (before any markdown)"],
], columns=["opportunity", "kes", "basis"])
opps["kes_fmt"] = opps.kes.map(an.kes)
opps"""),
    code("""annual_gp = an.sql_output("q01_headline_kpis").gross_profit_kes.iloc[0] / 2
print(f"Recurring opportunities total {an.kes(opps.kes.iloc[:3].sum())} per year = {100*opps.kes.iloc[:3].sum()/annual_gp:.1f}% of annual gross profit ({an.kes(annual_gp)})")"""),
    md("""## 4. Recommendations

| # | Recommendation | Evidence | Owner | How to measure |
|---|---|---|---|---|
| 1 | **Audit and restrict manual price overrides at Nyali**: require supervisor approval and a reason code, and review the top override cashiers weekly | Non-promo discount of 2.58% of sales vs ~0.4% elsewhere, including 1.59% on ambient goods; margin lowest in all 24 months | Regional ops manager, Coast | Nyali non-promo discount rate below 0.6% within 3 months |
| 2 | **Re-set reorder points at Kisumu and Eldoret for lead time**: reorder point = demand × (lead time + safety buffer), starting with the watchlist SKUs | Stockout rate 23% / 19% vs ~5–6%; persistent across all months; high even where reorder levels are normal | Supply chain planner | Stockout rate below 8%; lost-GP estimate falls |
| 3 | **Fix stale reorder levels chain-wide**: a monthly job flags SKUs whose reorder level is below 0.75 weeks of demand | Those SKUs stock out in 27–55% of weeks, in every branch | Inventory controller | Count of flagged pairs near 0 |
| 4 | **Rebalance promotional spend toward Snacks & Confectionery and Personal Care; stop deep discounts on Staples and Dairy** (use those for footfall only, with explicit budget) | Only Snacks returns positive incremental GP; Staples and Dairy promotions lost the most (all 25 Staples promotions were GP-negative) | Commercial / category managers | Incremental GP per KES of discount, tracked per promotion |
| 5 | **Clear the two collapsed Household SKUs** (markdown or supplier return), lower their order-up-to levels or delist them before the next reorder, and ask the buyer why demand fell | ~KES 384K at cost of slow stock in two SKUs; Household & Cleaning is the only category with declining LFL GP | Category buyer, Household | Category LFL GP growth back to ≥0 |
| 6 | **Investigate Machakos**: a local market visit, competitor check and staffing review before any capital decision | Only established branch with falling sales (−11.9% YoY, worse in the latest quarter), while its margin and availability are normal | Regional manager | Footfall trend; quarterly YoY |

**What the data cannot tell us:** *why* Machakos footfall fell, *why* the two Household SKUs collapsed, and the true supplier lead times. Each recommendation above includes the step that would confirm the cause."""),
    md("""## 5. Optional extension: a simple weekly demand forecast
*Purpose:* show how a planner could anticipate weekly sales by branch for replenishment. It is deliberately simple, and it **does not replace** the analysis above.
Method: compare a seasonal naive baseline (same week last year × recent growth) with a 4-week moving average, on the last 12 weeks held out."""),
    code("""w = query(engine, "SELECT sale_week, SUM(net_revenue) AS rev FROM retail.v_sales_lines WHERE branch_id <> 'BR10' GROUP BY 1 ORDER BY 1")
w["rev"] = w.rev.astype(float); w = w.iloc[1:-1].reset_index(drop=True)   # drop partial first/last weeks
test = w.iloc[-12:]; train = w.iloc[:-12]
ma4 = [w.rev.iloc[i-4:i].mean() for i in test.index]
growth = train.rev.iloc[-12:].sum() / train.rev.iloc[-64:-52].sum()
snaive = [w.rev.iloc[i-52] * growth for i in test.index]
mape = lambda a, f: np.mean(np.abs((np.array(a) - np.array(f)) / np.array(a))) * 100
print(f"MAPE, 4-week moving average: {mape(test.rev, ma4):.1f}%")
print(f"MAPE, seasonal naive x growth: {mape(test.rev, snaive):.1f}%")
fig, ax = plt.subplots(figsize=(10, 3.4))
ax.plot(pd.to_datetime(w.sale_week.iloc[-40:]), w.rev.iloc[-40:], color=an.PRIMARY, label="Actual (like-for-like branches)")
ax.plot(pd.to_datetime(test.sale_week), snaive, color=an.HIGHLIGHT, ls="--", label="Seasonal naive x growth")
ax.plot(pd.to_datetime(test.sale_week), ma4, color=an.SECOND, ls=":", label="4-week moving average")
an.kes_axis(ax); ax.set_title("Weekly revenue forecast on the last 12 weeks (holdout)"); ax.legend(fontsize=8)
an.save(fig, "forecast_extension");"""),
    md("Both baselines miss actual weekly revenue by about 5–7% on average (MAPE) on the holdout, with the seasonal baseline doing better. Any more complex model would have to beat these numbers to justify itself. Since the data is synthetic, forecast accuracy here says little about real-world performance. The value of the exercise is the evaluation method, not the score."),
]


def main(run: bool = True) -> None:
    NB_DIR.mkdir(exist_ok=True)
    for name, cells in NOTEBOOKS.items():
        nb = nbf.v4.new_notebook()
        nb["cells"] = cells
        nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
        path = NB_DIR / f"{name}.ipynb"
        nbf.write(nb, path)
        if run:
            print("executing", path.name, flush=True)
            subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                            "--ExecutePreprocessor.timeout=900", str(path)], check=True)


if __name__ == "__main__":
    main(run="--no-run" not in sys.argv)
