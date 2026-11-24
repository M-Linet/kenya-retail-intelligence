"""Reusable analysis helpers: metric definitions, data access and a consistent chart style.

The metric functions mirror the definitions in sql/03_views.sql, and tests/test_transformations.py
checks that pandas and SQL give the same answers.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.data_loader import PROJECT_ROOT, get_engine, query

FIG_DIR = PROJECT_ROOT / "reports" / "figures"

# Colour roles (validated categorical palette, light mode). Charts use colour sparingly:
# one primary series, one highlight for "the thing the chart is about", grey for context.
PRIMARY = "#2a78d6"     # blue
HIGHLIGHT = "#eb6834"   # orange
SECOND = "#1baf7a"      # aqua
CONTEXT = "#b9b8b0"     # grey for de-emphasised marks
INK = "#2b2b29"
INK_MUTED = "#6b6a64"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ_BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def set_style() -> None:
    mpl.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.labelcolor": INK_MUTED, "axes.edgecolor": "#d8d7d0", "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#ecebe6", "grid.linewidth": 0.8, "axes.axisbelow": True,
        "xtick.color": INK_MUTED, "ytick.color": INK_MUTED, "text.color": INK,
        "axes.prop_cycle": mpl.cycler(color=SERIES), "lines.linewidth": 2,
        "legend.frameon": False,
    })


def kes(x: float, digits: int = 1) -> str:
    """Human-readable KES amount: 489.6M, 1.7K."""
    for div, suf in [(1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(x) >= div:
            return f"KES {x / div:.{digits}f}{suf}"
    return f"KES {x:,.0f}"


def kes_axis(ax, axis: str = "y", unit: str = "M") -> None:
    div = {"M": 1e6, "K": 1e3}[unit]
    fmt = mpl.ticker.FuncFormatter(lambda v, _: f"{v / div:,.0f}{unit}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def save(fig, name: str) -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / f"{name}.png"
    fig.savefig(path)
    return path


# ---------------------------------------------------------------------------
# Metric definitions (same as the SQL semantic layer)
# ---------------------------------------------------------------------------
def add_line_metrics(lines: pd.DataFrame) -> pd.DataFrame:
    """Add gross_sales, net_revenue, cogs and gross_profit columns to a line-level frame."""
    out = lines.copy()
    out["gross_sales"] = out["quantity"] * out["unit_price"]
    out["net_revenue"] = out["gross_sales"] - out["discount_amount"]
    out["cogs"] = out["quantity"] * out["unit_cost"]
    out["gross_profit"] = out["net_revenue"] - out["cogs"]
    return out


def margin_table(df: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    """Aggregate revenue and profit, then compute margin from the totals (never average line margins)."""
    g = df.groupby(by, observed=True).agg(revenue=("net_revenue", "sum"), gross_profit=("gross_profit", "sum"),
                                          gross_sales=("gross_sales", "sum"), discounts=("discount_amount", "sum"),
                                          units=("quantity", "sum"))
    g["gross_margin_pct"] = 100 * g["gross_profit"] / g["revenue"]
    g["discount_rate_pct"] = 100 * g["discounts"] / g["gross_sales"]
    g["revenue_share_pct"] = 100 * g["revenue"] / g["revenue"].sum()
    g["gp_share_pct"] = 100 * g["gross_profit"] / g["gross_profit"].sum()
    return g.sort_values("revenue", ascending=False)


def annual_turnover(cogs: float, avg_stock_value: float, days: int) -> float:
    """Annualised inventory turnover = COGS / average stock at cost, scaled to 364 days."""
    if avg_stock_value <= 0:
        return np.nan
    return cogs / avg_stock_value * 364.0 / days


def weeks_of_cover(stock_units: float, avg_weekly_units: float) -> float:
    return np.inf if avg_weekly_units == 0 and stock_units > 0 else (stock_units / avg_weekly_units if avg_weekly_units else np.nan)


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def load_sales_lines(engine=None, columns: str = "*") -> pd.DataFrame:
    engine = engine or get_engine()
    df = query(engine, f"SELECT {columns} FROM retail.v_sales_lines")
    for c in ["unit_price", "unit_cost", "gross_sales", "discount_amount", "net_revenue", "cogs", "gross_profit"]:
        if c in df:
            df[c] = df[c].astype(float)
    return df


def sql_output(name: str) -> pd.DataFrame:
    """Read a saved SQL result produced by `python -m src.run_sql`."""
    return pd.read_csv(PROJECT_ROOT / "reports" / "sql_outputs" / f"{name}.csv")
