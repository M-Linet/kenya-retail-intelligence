"""Render Python layout prototypes of the four Power BI pages from the SQL outputs.

These images are NOT Power BI screenshots. They fix the layout and the numbers each page must show,
so that the Power BI build can be checked against them. Replace them with real screenshots afterwards.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import analysis as an  # noqa: E402
from src.data_loader import PROJECT_ROOT  # noqa: E402

OUT = PROJECT_ROOT / "powerbi" / "screenshots"
o = an.sql_output
short = lambda s: s.str.replace("Savanna Fresh ", "", regex=False)


def frame(title: str, question: str):
    fig = plt.figure(figsize=(16, 9), facecolor="#f7f7f4")
    fig.text(0.015, 0.955, title, fontsize=18, fontweight="bold", color=an.INK)
    fig.text(0.015, 0.925, question, fontsize=11, color=an.INK_MUTED)
    fig.text(0.985, 0.955, "PROTOTYPE · Python render of the planned Power BI page, not a Power BI screenshot",
             fontsize=9, color=an.HIGHLIGHT, ha="right")
    fig.text(0.985, 0.928, "Slicers: Date range · County · Branch type · Category", fontsize=9, color=an.INK_MUTED, ha="right")
    fig.text(0.015, 0.012, "Fictional company, synthetic data · Savanna Fresh Supermarkets · Nov 2024 – Oct 2026",
             fontsize=8, color=an.INK_MUTED)
    return fig


def kpis(fig, items, top=0.80, h=0.09):
    n = len(items); w = 0.97 / n
    for i, (label, value, sub) in enumerate(items):
        ax = fig.add_axes([0.015 + i * w, top, w - 0.008, h]); ax.set_axis_off()
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, color="white", transform=ax.transAxes))
        ax.text(0.06, 0.70, label, fontsize=10, color=an.INK_MUTED, transform=ax.transAxes)
        ax.text(0.06, 0.28, value, fontsize=19, fontweight="bold", color=an.INK, transform=ax.transAxes)
        if sub:
            ax.text(0.06, 0.06, sub, fontsize=8.5, color=an.INK_MUTED, transform=ax.transAxes)


def panel(fig, rect, title):
    ax = fig.add_axes(rect, facecolor="white")
    ax.set_title(title, fontsize=11, loc="left", pad=8)
    return ax


def page1():
    k = o("q01_headline_kpis").iloc[0]; y = o("q03_year_over_year").set_index("scope")
    fig = frame("Executive overview", "Is the business growing, and is the growth profitable?")
    lfl = y.loc["Like-for-like (excl. BR10)", "revenue_growth_pct"]
    kpis(fig, [("Revenue", an.kes(k.net_revenue_kes), f"LFL YoY +{lfl:.1f}% (Y2 vs Y1)"),
               ("Gross profit", an.kes(k.gross_profit_kes), None), ("Gross margin", f"{k.gross_margin_pct:.1f}%", None),
               ("Units sold", f"{k.units_sold/1e6:.2f}M", None), ("Transactions", f"{k.transactions/1e3:.0f}K", None),
               ("Avg transaction value", f"KES {k.avg_transaction_value_kes:,.0f}", None)])
    m = o("q02_monthly_revenue_mom"); m["sale_month"] = pd.to_datetime(m.sale_month)
    ax = panel(fig, [0.04, 0.42, 0.55, 0.30], "Monthly revenue: Year 2 vs Year 1")
    y1 = m.iloc[:12]; y2 = m.iloc[12:]
    lab = y2.sale_month.dt.strftime("%b")
    ax.plot(lab, y1.revenue_kes.values, color=an.CONTEXT, lw=2, label="Year 1 (Nov 24–Oct 25)")
    ax.plot(lab, y2.revenue_kes.values, color=an.PRIMARY, lw=2.2, marker="o", ms=4, label="Year 2 (Nov 25–Oct 26)")
    an.kes_axis(ax); ax.legend(fontsize=9, loc="upper right")
    b = o("q04_branch_ranking").sort_values("revenue_kes")
    ax = panel(fig, [0.68, 0.42, 0.30, 0.30], "Revenue by branch (KES)")
    ax.barh(short(b.branch_name), b.revenue_kes, color=an.PRIMARY, height=.6); an.kes_axis(ax, "x"); ax.grid(axis="y", visible=False)
    c = o("q06_category_revenue").sort_values("revenue_kes")
    ax = panel(fig, [0.10, 0.06, 0.40, 0.28], "Revenue vs gross profit by category (KES)")
    yy = np.arange(len(c))
    ax.barh(yy + .2, c.revenue_kes, .38, color=an.CONTEXT, label="Revenue"); ax.barh(yy - .2, c.gross_profit_kes, .38, color=an.PRIMARY, label="Gross profit")
    ax.set_yticks(yy, c.category, fontsize=8.5); an.kes_axis(ax, "x"); ax.legend(fontsize=8, loc="lower right"); ax.grid(axis="y", visible=False)
    t = o("q12_top_products_gross_profit").head(8)
    ax = fig.add_axes([0.56, 0.05, 0.42, 0.30]); ax.set_axis_off(); ax.set_title("Top products by gross profit", fontsize=11, loc="left")
    tab = ax.table(cellText=[[r.product_name, an.kes(r.revenue_kes), an.kes(r.gross_profit_kes), f"{r.gross_margin_pct:.1f}%"] for r in t.itertuples()],
                   colLabels=["Product", "Revenue", "Gross profit", "Margin"], loc="upper left", cellLoc="left", colLoc="left",
                   colWidths=[.5, .17, .17, .12])
    tab.auto_set_font_size(False); tab.set_fontsize(8.5); tab.scale(1, 1.35)
    for (r, _), cell in tab.get_celld().items():
        cell.set_edgecolor("#ecebe6"); cell.set_facecolor("white" if r else "#f0efea")
    return fig


def page2():
    fig = frame("Product & profitability", "Where is margin made, and where is it lost?")
    p = o("q16_branch_margin_drivers"); s = o("q19_promotion_summary_by_category")
    kpis(fig, [("Gross margin", f"{o('q01_headline_kpis').gross_margin_pct.iloc[0]:.1f}%", None),
               ("Discount rate", f"{o('q01_headline_kpis').discount_rate_pct.iloc[0]:.2f}%", "of gross sales"),
               ("Nyali non-promo discount", f"{p.set_index('branch_id').loc['BR04','non_promo_discount_pct_of_sales']:.2f}%", "other branches ≈ 0.4%"),
               ("GP-positive promotions", f"{(o('q18_promotion_performance').outcome=='GP-positive').mean()*100:.0f}%", "of 103 measured"),
               ("Promo incremental GP", an.kes(s.incremental_gp_kes.sum()), "vs 28-day baselines")])
    c = o("q15_category_performance").sort_values("revenue_share_pct")
    ax = panel(fig, [0.10, 0.42, 0.36, 0.30], "Share of revenue vs share of gross profit (%)")
    yy = np.arange(len(c)); ax.barh(yy + .2, c.revenue_share_pct, .38, color=an.CONTEXT, label="Revenue share")
    ax.barh(yy - .2, c.gp_share_pct, .38, color=an.PRIMARY, label="GP share"); ax.set_yticks(yy, c.category, fontsize=8.5)
    ax.legend(fontsize=8, loc="lower right"); ax.grid(axis="y", visible=False)
    d = p.sort_values("gross_margin_pct")
    ax = panel(fig, [0.58, 0.42, 0.40, 0.30], "Margin before discounts vs non-promo discount, by branch (%)")
    yy = np.arange(len(d)); ax.barh(yy + .2, d.margin_before_discounts_pct, .38, color=an.CONTEXT, label="Margin before discounts")
    ax.barh(yy - .2, d.gross_margin_pct, .38, color=an.PRIMARY, label="Gross margin after discounts")
    ax.set_yticks(yy, short(d.branch_name), fontsize=8.5); ax.set_xlim(16, 20.5); ax.legend(fontsize=8, loc="lower right"); ax.grid(axis="y", visible=False)
    ax = panel(fig, [0.10, 0.06, 0.36, 0.28], "Promotion payback by category (incremental GP per KES of discount)")
    s2 = s.sort_values("incremental_gp_per_kes_discount")
    ax.barh(s2.category, s2.incremental_gp_per_kes_discount, color=[an.HIGHLIGHT if v < 0 else an.PRIMARY for v in s2.incremental_gp_per_kes_discount], height=.6)
    ax.axvline(0, color=an.INK_MUTED, lw=.8); ax.grid(axis="y", visible=False); ax.tick_params(axis="y", labelsize=8.5)
    h = o("q13_high_revenue_low_margin").head(7)
    ax = fig.add_axes([0.56, 0.05, 0.42, 0.30]); ax.set_axis_off(); ax.set_title("High revenue, below-chain margin", fontsize=11, loc="left")
    tab = ax.table(cellText=[[r.product_name, r.category, an.kes(r.revenue_kes), f"{r.gross_margin_pct:.1f}%"] for r in h.itertuples()],
                   colLabels=["Product", "Category", "Revenue", "Margin"], loc="upper left", cellLoc="left", colLoc="left", colWidths=[.45, .2, .17, .12])
    tab.auto_set_font_size(False); tab.set_fontsize(8.5); tab.scale(1, 1.35)
    for (r, _), cell in tab.get_celld().items():
        cell.set_edgecolor("#ecebe6"); cell.set_facecolor("white" if r else "#f0efea")
    return fig


def page3():
    fig = frame("Inventory intelligence", "Are the shelves full of the right things?")
    pos = o("q22_slow_moving_stock_value").set_index("stock_status")
    slow = pos.loc[["Slow-moving (>26 wks cover)", "No sales in 12 weeks"], "stock_value_kes"].sum()
    kpis(fig, [("Closing stock value (at cost)", an.kes(pos.stock_value_kes.sum()), "latest Sunday count"),
               ("Stockout rate", f"{pd.read_csv(PROJECT_ROOT / 'powerbi' / 'kpi_reconciliation.csv').stockout_rate_pct.iloc[0]:.1f}%", "product-weeks closing at zero"),
               ("Slow / no-sale stock", an.kes(slow), f"{100*slow/pos.stock_value_kes.sum():.1f}% of stock value"),
               ("Est. GP lost to stockouts", an.kes(o("q28_lost_sales_estimate").est_lost_gross_profit_kes.sum()), "2 years, approximate")])
    s = o("q24_stockout_rate_by_branch").sort_values("stockout_rate_pct")
    ax = panel(fig, [0.08, 0.42, 0.38, 0.30], "Stockout rate by branch (%)")
    ax.barh(short(s.branch_name), s.stockout_rate_pct, color=[an.HIGHLIGHT if v > 10 else an.PRIMARY for v in s.stockout_rate_pct], height=.6)
    ax.axvline(10, color=an.INK_MUTED, ls="--", lw=.8); ax.grid(axis="y", visible=False)
    t = o("q20_inventory_turnover_by_category").sort_values("annual_turnover")
    ax = panel(fig, [0.60, 0.42, 0.38, 0.30], "Inventory turnover by category (times per year)")
    ax.barh(t.category, t.annual_turnover, color=an.PRIMARY, height=.6); ax.grid(axis="y", visible=False); ax.tick_params(axis="y", labelsize=8.5)
    w = o("q26_replenishment_watchlist").head(8)
    ax = fig.add_axes([0.02, 0.05, 0.46, 0.30]); ax.set_axis_off(); ax.set_title("Replenishment watchlist (≥3 stockout weeks in last 12)", fontsize=11, loc="left")
    tab = ax.table(cellText=[[r.branch_id, r.product_name, int(r.stockout_weeks_12w), int(r.reorder_level), f"{r.gp_per_selling_week_kes:,.0f}"] for r in w.itertuples()],
                   colLabels=["Branch", "Product", "Stockout wks", "Reorder lvl", "GP/week KES"], loc="upper left", cellLoc="left", colLoc="left",
                   colWidths=[.1, .45, .15, .14, .16])
    tab.auto_set_font_size(False); tab.set_fontsize(8.5); tab.scale(1, 1.35)
    for (r, _), cell in tab.get_celld().items():
        cell.set_edgecolor("#ecebe6"); cell.set_facecolor("white" if r else "#f0efea")
    sm = o("q23_slow_moving_products").head(7)
    ax = fig.add_axes([0.52, 0.05, 0.46, 0.30]); ax.set_axis_off(); ax.set_title("Slow-moving stock (latest count)", fontsize=11, loc="left")
    tab = ax.table(cellText=[[r.product_name, int(r.units_on_hand), f"{r.chain_weeks_of_cover:,.0f}", an.kes(r.stock_value_kes)] for r in sm.itertuples()],
                   colLabels=["Product", "Units on hand", "Weeks of cover", "Value at cost"], loc="upper left", cellLoc="left", colLoc="left", colWidths=[.46, .16, .18, .18])
    tab.auto_set_font_size(False); tab.set_fontsize(8.5); tab.scale(1, 1.35)
    for (r, _), cell in tab.get_celld().items():
        cell.set_edgecolor("#ecebe6"); cell.set_facecolor("white" if r else "#f0efea")
    return fig


def page4():
    fig = frame("Branch performance", "Which branches need management attention, and why?")
    sc = o("q29_branch_scorecard")
    ax = fig.add_axes([0.015, 0.47, 0.97, 0.42]); ax.set_axis_off(); ax.set_title("Branch scorecard", fontsize=11, loc="left")
    rows = [[short(pd.Series([r.branch_name]))[0], r.branch_type, an.kes(r.revenue_kes),
             "n/a" if pd.isna(r.yoy_growth_pct) else f"{r.yoy_growth_pct:+.1f}%", f"{r.gross_margin_pct:.2f}%",
             f"{r.non_promo_discount_pct:.2f}%", f"{r.stockout_rate_pct:.1f}%", f"{r.slow_stock_share_pct:.1f}%", r.flags] for r in sc.itertuples()]
    tab = ax.table(cellText=rows, colLabels=["Branch", "Type", "Revenue", "YoY", "Gross margin", "Non-promo disc.", "Stockout", "Slow stock", "Flags"],
                   loc="upper left", cellLoc="left", colLoc="left", colWidths=[.09, .08, .08, .06, .08, .09, .07, .07, .38])
    tab.auto_set_font_size(False); tab.set_fontsize(9); tab.scale(1, 1.45)
    for (r, ci), cell in tab.get_celld().items():
        cell.set_edgecolor("#ecebe6"); cell.set_facecolor("white" if r else "#f0efea")
        if r and ci == 8 and rows[r - 1][8] != "No flags":
            cell.get_text().set_color(an.HIGHLIGHT)
    b = o("q04_branch_ranking")
    ax = panel(fig, [0.05, 0.07, 0.42, 0.30], "Revenue vs gross margin (bubble = transactions)")
    ax.scatter(b.revenue_kes, b.gross_margin_pct, s=b.transactions / 120, color=an.PRIMARY, alpha=.75, edgecolor="white")
    nudge = {"Machakos": (6, -11), "Mombasa CBD": (-8, -14), "Thika": (-30, 6), "Eldoret": (6, -10)}
    for r in b.itertuples():
        nm = r.branch_name.replace("Savanna Fresh ", "")
        ax.annotate(nm, (r.revenue_kes, r.gross_margin_pct), xytext=nudge.get(nm, (6, 3)), textcoords="offset points", fontsize=8)
    an.kes_axis(ax, "x"); ax.set_ylabel("Gross margin %")
    c = o("q05_county_contribution").sort_values("revenue_kes")
    ax = panel(fig, [0.60, 0.07, 0.38, 0.30], "Revenue by county (KES)")
    ax.barh(c.county, c.revenue_kes, color=an.PRIMARY, height=.6); an.kes_axis(ax, "x"); ax.grid(axis="y", visible=False)
    return fig


if __name__ == "__main__":
    an.set_style(); OUT.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate([page1, page2, page3, page4], 1):
        fig = f(); name = ["executive_overview", "product_profitability", "inventory_intelligence", "branch_performance"][i - 1]
        fig.savefig(OUT / f"prototype_page{i}_{name}.png", dpi=110, facecolor=fig.get_facecolor()); plt.close(fig)
        print("wrote", f"prototype_page{i}_{name}.png")
