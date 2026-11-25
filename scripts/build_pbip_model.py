"""Generate the Power BI semantic model (TMDL) for the PBIP project in powerbi/.

Power BI Desktop saved an empty project (powerbi/SavannaFresh.pbip). This script writes the model
definition into it: tables with Power Query (M) sources, relationships, a date table and all the DAX measures.
Close Power BI first, run the script, then reopen SavannaFresh.pbip and click Refresh.

    python scripts/build_pbip_model.py [--data-folder "C:\\path\\to\\data\\processed\\powerbi\\"]
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEF = ROOT / "powerbi" / "SavannaFresh.SemanticModel" / "definition"
NS = uuid.UUID("6f1c2a4e-1d1b-4c55-9d0a-2f7f6a0e7b11")
tag = lambda s: str(uuid.uuid5(NS, s))  # stable lineage tags, so regenerating does not churn git diffs

# column spec: (name, tmdl dataType, M type, summarizeBy, formatString, hidden)
T, I, D, C, DT, B = "string", "int64", "double", "decimal", "dateTime", "boolean"
M = {T: "type text", I: "Int64.Type", D: "type number", C: "Currency.Type", DT: "type date", B: "type logical"}

TABLES: dict[str, list[tuple]] = {
    "dim_date": [("date", DT), ("year", I), ("month_number", I), ("month_short", T), ("year_month", T),
                 ("month_start", DT), ("week_start", DT), ("iso_dow", I), ("day_short", T), ("is_weekend", B),
                 ("is_payday_window", B)],
    "dim_branch": [("branch_id", T), ("branch_name", T), ("branch_short", T), ("county", T), ("town", T),
                   ("branch_type", T), ("opening_date", DT), ("is_like_for_like", B)],
    "dim_product": [("product_id", T), ("product_name", T), ("category", T), ("brand", T), ("unit_cost", C),
                    ("unit_cost_imputed", B), ("product_group", T)],
    "dim_customer": [("customer_key", T), ("customer_segment", T), ("registration_date", DT), ("county", T)],
    "dim_promotion": [("promotion_id", T), ("product_id", T), ("start_date", DT), ("end_date", DT), ("discount_percentage", D)],
    "fact_sales": [("transaction_item_id", I), ("transaction_id", T), ("sale_date", DT), ("sale_hour", I), ("branch_id", T),
                   ("product_id", T), ("customer_key", T), ("payment_method", T), ("promotion_id", T), ("price_type", T),
                   ("quantity", I), ("gross_sales", C), ("discount_amount", C), ("net_revenue", C), ("cogs", C), ("gross_profit", C)],
    "fact_inventory": [("inventory_id", I), ("snapshot_date", DT), ("branch_id", T), ("product_id", T), ("stock_quantity", I),
                       ("reorder_level", I), ("stock_value_at_cost", C), ("units_sold_in_week", I), ("is_stockout", B),
                       ("at_or_below_reorder", B)],
    "fact_inventory_position": [("branch_id", T), ("product_id", T), ("snapshot_date", DT), ("stock_quantity", I),
                                ("reorder_level", I), ("stock_value_at_cost", C), ("avg_weekly_units_12w", D),
                                ("stockout_weeks_12w", I), ("weeks_of_cover", D), ("stock_status", T)],
    "promo_performance": [("promotion_id", T), ("product_id", T), ("product_name", T), ("category", T), ("start_date", DT),
                          ("days", I), ("discount_percentage", D), ("baseline_units_per_day", D), ("promo_units_per_day", D),
                          ("unit_uplift_pct", D), ("discount_cost_kes", C), ("incremental_gp_kes", C), ("outcome", T)],
}
HIDDEN_KEYS = {"fact_sales": {"branch_id", "product_id", "customer_key", "promotion_id", "sale_date", "transaction_item_id"},
               "fact_inventory": {"branch_id", "product_id", "snapshot_date", "inventory_id"},
               "fact_inventory_position": {"branch_id", "product_id"},
               "promo_performance": {"product_id"}}
SORT_BY = {("dim_date", "month_short"): "month_number", ("dim_date", "day_short"): "iso_dow"}

RELATIONSHIPS = [  # (many-side column, one-side column)
    ("fact_sales.sale_date", "dim_date.date"), ("fact_sales.branch_id", "dim_branch.branch_id"),
    ("fact_sales.product_id", "dim_product.product_id"), ("fact_sales.customer_key", "dim_customer.customer_key"),
    ("fact_sales.promotion_id", "dim_promotion.promotion_id"),
    ("fact_inventory.snapshot_date", "dim_date.date"), ("fact_inventory.branch_id", "dim_branch.branch_id"),
    ("fact_inventory.product_id", "dim_product.product_id"),
    ("fact_inventory_position.branch_id", "dim_branch.branch_id"), ("fact_inventory_position.product_id", "dim_product.product_id"),
    ("promo_performance.product_id", "dim_product.product_id"),
]

KES, PCT, NUM, DEC1 = "#,0", "0.0%", "#,0", "#,0.0"
# (name, expression, format, folder)
MEASURES = [
    ("Revenue", "SUM ( fact_sales[net_revenue] )", KES, "1 Sales"),
    ("Gross Sales", "SUM ( fact_sales[gross_sales] )", KES, "1 Sales"),
    ("Discounts", "SUM ( fact_sales[discount_amount] )", KES, "1 Sales"),
    ("Units Sold", "SUM ( fact_sales[quantity] )", NUM, "1 Sales"),
    ("Transactions", "DISTINCTCOUNT ( fact_sales[transaction_id] )", NUM, "1 Sales"),
    ("ATV", "DIVIDE ( [Revenue], [Transactions] )", KES, "1 Sales"),
    ("Units per Basket", "DIVIDE ( [Units Sold], [Transactions] )", "0.00", "1 Sales"),
    ("Revenue Share of Selection",
     "DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALLSELECTED ( dim_branch ), ALLSELECTED ( dim_product ) ) )", PCT, "1 Sales"),
    ("COGS", "SUM ( fact_sales[cogs] )", KES, "2 Profitability"),
    ("Gross Profit", "SUM ( fact_sales[gross_profit] )", KES, "2 Profitability"),
    ("Gross Margin %", "DIVIDE ( [Gross Profit], [Revenue] )", "0.00%", "2 Profitability"),
    ("Discount Rate %", "DIVIDE ( [Discounts], [Gross Sales] )", "0.00%", "2 Profitability"),
    ("Margin Before Discounts %", "DIVIDE ( [Gross Sales] - [COGS], [Gross Sales] )", "0.00%", "2 Profitability"),
    ("Promo Discount % of Sales",
     'DIVIDE ( CALCULATE ( [Discounts], fact_sales[price_type] = "Promotion" ), [Gross Sales] )', "0.00%", "2 Profitability"),
    ("Non-Promo Discount % of Sales",
     'DIVIDE ( CALCULATE ( [Discounts], fact_sales[price_type] = "Non-promotional discount" ), [Gross Sales] )', "0.00%", "2 Profitability"),
    ("GP Share of Selection", "DIVIDE ( [Gross Profit], CALCULATE ( [Gross Profit], ALLSELECTED ( dim_product ) ) )", PCT, "2 Profitability"),
    ("Chain Gross Margin %", "CALCULATE ( [Gross Margin %], REMOVEFILTERS ( dim_branch ), REMOVEFILTERS ( dim_product ) )", "0.00%", "2 Profitability"),
    ("Margin vs Chain (pts)", "( [Gross Margin %] - [Chain Gross Margin %] ) * 100", "+0.00;-0.00;0.00", "2 Profitability"),
    ("Revenue PY", "CALCULATE ( [Revenue], DATEADD ( dim_date[date], -1, YEAR ) )", KES, "3 Time intelligence"),
    ("Revenue YoY %", "IF ( NOT ISBLANK ( [Revenue PY] ), DIVIDE ( [Revenue] - [Revenue PY], [Revenue PY] ) )", "+0.0%;-0.0%;0.0%", "3 Time intelligence"),
    ("Gross Profit PY", "CALCULATE ( [Gross Profit], DATEADD ( dim_date[date], -1, YEAR ) )", KES, "3 Time intelligence"),
    ("Gross Profit YoY %", "IF ( NOT ISBLANK ( [Gross Profit PY] ), DIVIDE ( [Gross Profit] - [Gross Profit PY], [Gross Profit PY] ) )", "+0.0%;-0.0%;0.0%", "3 Time intelligence"),
    ("Revenue PM", "CALCULATE ( [Revenue], DATEADD ( dim_date[date], -1, MONTH ) )", KES, "3 Time intelligence"),
    ("Revenue MoM %", "IF ( NOT ISBLANK ( [Revenue PM] ), DIVIDE ( [Revenue] - [Revenue PM], [Revenue PM] ) )", "+0.0%;-0.0%;0.0%", "3 Time intelligence"),
    ("Revenue Running Total",
     "CALCULATE ( [Revenue], FILTER ( ALLSELECTED ( dim_date[date] ), dim_date[date] <= MAX ( dim_date[date] ) ) )", KES, "3 Time intelligence"),
    ("Revenue LFL", "CALCULATE ( [Revenue], dim_branch[is_like_for_like] = TRUE () )", KES, "3 Time intelligence"),
    ("Revenue LFL PY", "CALCULATE ( [Revenue LFL], DATEADD ( dim_date[date], -1, YEAR ) )", KES, "3 Time intelligence"),
    ("Revenue LFL YoY %", "IF ( NOT ISBLANK ( [Revenue LFL PY] ), DIVIDE ( [Revenue LFL] - [Revenue LFL PY], [Revenue LFL PY] ) )", "+0.0%;-0.0%;0.0%", "3 Time intelligence"),
    ("Revenue Growth Y2 vs Y1 %",
     "VAR y2 = CALCULATE ( [Revenue], KEEPFILTERS ( dim_date[date] >= DATE ( 2025, 11, 1 ) ) )\n"
     "VAR y1 = CALCULATE ( [Revenue], KEEPFILTERS ( dim_date[date] < DATE ( 2025, 11, 1 ) ) )\n"
     "RETURN IF ( SELECTEDVALUE ( dim_branch[is_like_for_like], TRUE () ) && NOT ISBLANK ( y1 ) && NOT ISBLANK ( y2 ), DIVIDE ( y2 - y1, y1 ) )",
     "+0.0%;-0.0%;0.0%", "3 Time intelligence"),
    ("LFL Growth Y2 vs Y1 %", "CALCULATE ( [Revenue Growth Y2 vs Y1 %], dim_branch[is_like_for_like] = TRUE () )",
     "+0.0%;-0.0%;0.0%", "3 Time intelligence"),
    ("Avg Daily Revenue", "DIVIDE ( [Revenue], COUNTROWS ( dim_date ) )", KES, "3 Time intelligence"),
    ("Branch Revenue Rank", "IF ( HASONEVALUE ( dim_branch[branch_short] ), RANKX ( ALLSELECTED ( dim_branch[branch_short] ), [Revenue] ) )", NUM, "4 Rankings"),
    ("Product GP Rank", "IF ( HASONEVALUE ( dim_product[product_name] ), RANKX ( ALLSELECTED ( dim_product[product_name] ), [Gross Profit] ) )", NUM, "4 Rankings"),
    ("Latest Snapshot Date", "CALCULATE ( MAX ( fact_inventory[snapshot_date] ) )", "dd mmm yyyy", "5 Inventory"),
    ("Closing Stock Value",
     "VAR d = [Latest Snapshot Date]\nRETURN CALCULATE ( SUM ( fact_inventory[stock_value_at_cost] ), fact_inventory[snapshot_date] = d )", KES, "5 Inventory"),
    ("Closing Stock Units",
     "VAR d = [Latest Snapshot Date]\nRETURN CALCULATE ( SUM ( fact_inventory[stock_quantity] ), fact_inventory[snapshot_date] = d )", NUM, "5 Inventory"),
    ("Avg Stock Value", "AVERAGEX ( VALUES ( fact_inventory[snapshot_date] ), CALCULATE ( SUM ( fact_inventory[stock_value_at_cost] ) ) )", KES, "5 Inventory"),
    ("Weeks in Selection", "DISTINCTCOUNT ( fact_inventory[snapshot_date] )", NUM, "5 Inventory"),
    ("Inventory Turnover", "DIVIDE ( [COGS], [Avg Stock Value] ) * DIVIDE ( 52, [Weeks in Selection] )", DEC1, "5 Inventory"),
    ("Avg Weeks of Stock", "DIVIDE ( 52, [Inventory Turnover] )", DEC1, "5 Inventory"),
    ("Stockout Weeks", "CALCULATE ( COUNTROWS ( fact_inventory ), fact_inventory[is_stockout] = TRUE () )", NUM, "5 Inventory"),
    ("Stockout Rate %", "DIVIDE ( [Stockout Weeks], COUNTROWS ( fact_inventory ) )", PCT, "5 Inventory"),
    ("Slow-Moving Stock Value",
     'CALCULATE ( SUM ( fact_inventory_position[stock_value_at_cost] ), fact_inventory_position[stock_status] IN { "Slow-moving (>26 wks cover)", "No sales in 12 weeks" } )',
     KES, "5 Inventory"),
    ("Slow-Moving Share %", "DIVIDE ( [Slow-Moving Stock Value], SUM ( fact_inventory_position[stock_value_at_cost] ) )", PCT, "5 Inventory"),
    ("Chain Weeks of Cover",
     "DIVIDE ( SUM ( fact_inventory_position[stock_quantity] ), SUM ( fact_inventory_position[avg_weekly_units_12w] ) )", DEC1, "5 Inventory"),
    ("Promo Revenue", 'CALCULATE ( [Revenue], fact_sales[price_type] = "Promotion" )', KES, "6 Promotions"),
    ("Promo Share of Revenue %", "DIVIDE ( [Promo Revenue], [Revenue] )", "0.00%", "6 Promotions"),
    ("Promo Incremental GP", "SUM ( promo_performance[incremental_gp_kes] )", KES, "6 Promotions"),
    ("Promo Discount Cost", "SUM ( promo_performance[discount_cost_kes] )", KES, "6 Promotions"),
    ("Incremental GP per KES Discount", "DIVIDE ( [Promo Incremental GP], [Promo Discount Cost] )", "0.00", "6 Promotions"),
    ("GP-Positive Promotions %",
     'DIVIDE ( CALCULATE ( COUNTROWS ( promo_performance ), promo_performance[outcome] = "GP-positive" ), COUNTROWS ( promo_performance ) )',
     PCT, "6 Promotions"),
    ("Promotions Measured", "COUNTROWS ( promo_performance )", NUM, "6 Promotions"),
    ("Δ Revenue", "VAR y2 = CALCULATE ( [Revenue], KEEPFILTERS ( dim_date[date] >= DATE ( 2025, 11, 1 ) ) )\nVAR y1 = CALCULATE ( [Revenue], KEEPFILTERS ( dim_date[date] < DATE ( 2025, 11, 1 ) ) )\nRETURN IF ( NOT ISBLANK ( y1 ) && NOT ISBLANK ( y2 ), FORMAT ( DIVIDE ( y2 - y1, y1 ), \"▲ 0.0%;▼ 0.0%;0.0%\" ) & \"  year 2 vs year 1\" )", None, "8 Editorial"),
    ("Δ Gross Profit", "VAR y2 = CALCULATE ( [Gross Profit], KEEPFILTERS ( dim_date[date] >= DATE ( 2025, 11, 1 ) ) )\nVAR y1 = CALCULATE ( [Gross Profit], KEEPFILTERS ( dim_date[date] < DATE ( 2025, 11, 1 ) ) )\nRETURN IF ( NOT ISBLANK ( y1 ) && NOT ISBLANK ( y2 ), FORMAT ( DIVIDE ( y2 - y1, y1 ), \"▲ 0.0%;▼ 0.0%;0.0%\" ) & \"  year 2 vs year 1\" )", None, "8 Editorial"),
    ("Δ Gross Margin", "VAR y2 = CALCULATE ( [Gross Margin %], KEEPFILTERS ( dim_date[date] >= DATE ( 2025, 11, 1 ) ) )\nVAR y1 = CALCULATE ( [Gross Margin %], KEEPFILTERS ( dim_date[date] < DATE ( 2025, 11, 1 ) ) )\nRETURN IF ( NOT ISBLANK ( y1 ) && NOT ISBLANK ( y2 ), FORMAT ( ( y2 - y1 ) * 100, \"▲ 0.0 pts;▼ 0.0 pts;0.0 pts\" ) & \"  year 2 vs year 1\" )", None, "8 Editorial"),
    ("Δ ATV", "VAR y2 = CALCULATE ( [ATV], KEEPFILTERS ( dim_date[date] >= DATE ( 2025, 11, 1 ) ) )\nVAR y1 = CALCULATE ( [ATV], KEEPFILTERS ( dim_date[date] < DATE ( 2025, 11, 1 ) ) )\nRETURN IF ( NOT ISBLANK ( y1 ) && NOT ISBLANK ( y2 ), FORMAT ( DIVIDE ( y2 - y1, y1 ), \"▲ 0.0%;▼ 0.0%;0.0%\" ) & \"  year 2 vs year 1\" )", None, "8 Editorial"),
    ("Revenue Share of All Categories", "DIVIDE ( [Revenue], CALCULATE ( [Revenue], REMOVEFILTERS ( dim_product ) ) )", "0.0%", "8 Editorial"),
    ("GP Share of All Categories", "DIVIDE ( [Gross Profit], CALCULATE ( [Gross Profit], REMOVEFILTERS ( dim_product ) ) )", "0.0%", "8 Editorial"),
    ("LFL Text", 'FORMAT ( [LFL Growth Y2 vs Y1 %], "▲ 0.0%;▼ 0.0%" ) & "  like-for-like (excl. Ruiru)"', None, "8 Editorial"),
    ("Promo Outcome Text", 'FORMAT ( [Promotions Measured] - CALCULATE ( [Promotions Measured], promo_performance[outcome] = "GP-positive" ), "0" ) & " of " & FORMAT ( [Promotions Measured], "0" ) & " promotions lost gross profit"', None, "8 Editorial"),
    ("Position Stock Value", "SUM ( fact_inventory_position[stock_value_at_cost] )", KES, "8 Editorial"),
    ("Colour Nyali", 'IF ( SELECTEDVALUE ( dim_branch[branch_short] ) = "Nyali", "#eb6834", "#2a78d6" )', None, "8 Editorial"),
    ("Colour Stockout Branch", 'IF ( [Stockout Rate %] > 0.15, "#eb6834", "#2a78d6" )', None, "8 Editorial"),
    ("Colour Growth", 'IF ( [Revenue Growth Y2 vs Y1 %] < 0, "#eb6834", "#2a78d6" )', None, "8 Editorial"),
    ("Colour Margin vs Chain", 'IF ( [Margin vs Chain (pts)] < -1, "#eb6834", "#2a78d6" )', None, "8 Editorial"),
    ("Colour Promo Outcome", 'IF ( SELECTEDVALUE ( promo_performance[outcome] ) = "GP-negative", "#eb6834", "#2a78d6" )', None, "8 Editorial"),
    ("Colour Stock Status", 'IF ( SELECTEDVALUE ( fact_inventory_position[stock_status] ) IN { "Slow-moving (>26 wks cover)", "No sales in 12 weeks" }, "#eb6834", "#2a78d6" )', None, "8 Editorial"),
    ("Branch Status", 'IF ( HASONEVALUE ( dim_branch[branch_short] ), IF ( [Stockout Rate %] > 0.15 || [Margin vs Chain (pts)] < -1 || [Revenue Growth Y2 vs Y1 %] < 0, "▲ Watch", "● On track" ) )', None, "8 Editorial"),
    ("Colour Branch Status", 'IF ( [Stockout Rate %] > 0.15 || [Margin vs Chain (pts)] < -1 || [Revenue Growth Y2 vs Y1 %] < 0, "#eb6834", "#55534c" )', None, "8 Editorial"),
    ("YoY Colour", 'IF ( [Revenue YoY %] < 0, "#eb6834", "#2a78d6" )', None, "7 Formatting"),
    ("Stockout Colour", 'IF ( [Stockout Rate %] > 0.10, "#eb6834", "#2a78d6" )', None, "7 Formatting"),
]


def q(name: str) -> str:
    """Quote a TMDL object name when it is not a plain identifier."""
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def m_source(table: str, cols: list[tuple]) -> str:
    types = ", ".join(f'{{"{c}", {M[t]}}}' for c, t in cols)
    return "\n".join([
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "{table}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f'    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")',
        "in",
        "    Typed",
    ])


def table_tmdl(name: str, cols: list[tuple]) -> str:
    out = [f"table {name}", f"\tlineageTag: {tag(name)}"]
    if name == "dim_date":
        out.append("\tdataCategory: Time")
    out.append("")
    for c, t in cols:
        out.append(f"\tcolumn {q(c)}")
        out.append(f"\t\tdataType: {t}")
        if name == "dim_date" and c == "date":
            out.append("\t\tisKey")
        if t == DT:
            out.append("\t\tformatString: dd mmm yyyy")
        elif t == C:
            out.append("\t\tformatString: #,0.00")
        elif t == I:
            out.append("\t\tformatString: 0")
        if c in HIDDEN_KEYS.get(name, set()):
            out.append("\t\tisHidden")
        out.append(f"\t\tlineageTag: {tag(name + '.' + c)}")
        numeric_measure_col = t in (C, D) or (t == I and name.startswith("fact") and c in {"quantity", "stock_quantity", "units_sold_in_week"})
        out.append(f"\t\tsummarizeBy: {'sum' if numeric_measure_col and name.startswith(('fact', 'promo')) else 'none'}")
        out.append(f"\t\tsourceColumn: {c}")
        if (name, c) in SORT_BY:
            out.append(f"\t\tsortByColumn: {SORT_BY[(name, c)]}")
        out.append("")
    out.append(f"\tpartition {name} = m")
    out.append("\t\tmode: import")
    out.append("\t\tsource =")
    out += ["\t\t\t\t" + l for l in m_source(name, cols).splitlines()]
    out.append("")
    return "\n".join(out) + "\n"


def measures_table() -> str:
    out = ["table _Measures", f"\tlineageTag: {tag('_Measures')}", ""]
    for name, expr, fmt, folder in MEASURES:
        lines = expr.splitlines()
        if len(lines) == 1:
            out.append(f"\tmeasure {q(name)} = {expr}")
        else:
            out.append(f"\tmeasure {q(name)} =")
            out += ["\t\t\t" + l for l in lines]
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out.append(f"\t\tdisplayFolder: {folder}")
        out.append(f"\t\tlineageTag: {tag('m.' + name)}")
        out.append("")
    out += ["\tcolumn Dummy", "\t\tdataType: string", "\t\tisHidden", f"\t\tlineageTag: {tag('_Measures.Dummy')}",
            "\t\tsummarizeBy: none", "\t\tsourceColumn: Dummy", "",
            "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =",
            "\t\t\t\tlet", '\t\t\t\t    Source = #table(type table [Dummy = text], {})', "\t\t\t\tin", "\t\t\t\t    Source", ""]
    return "\n".join(out) + "\n"


def main(data_folder: str) -> None:
    (DEF / "tables").mkdir(parents=True, exist_ok=True)
    for name, cols in TABLES.items():
        (DEF / "tables" / f"{name}.tmdl").write_text(table_tmdl(name, cols), encoding="utf-8")
    (DEF / "tables" / "_Measures.tmdl").write_text(measures_table(), encoding="utf-8")
    rel = []
    for frm, to in RELATIONSHIPS:
        rel += [f"relationship {tag(frm + to)}", f"\tfromColumn: {frm}", f"\ttoColumn: {to}", ""]
    (DEF / "relationships.tmdl").write_text("\n".join(rel) + "\n", encoding="utf-8")
    folder = data_folder.replace('"', '""')
    (DEF / "expressions.tmdl").write_text(
        f'expression DataFolder = "{folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
        f"\tlineageTag: {tag('DataFolder')}\n\n\tannotation PBI_ResultType = Text\n", encoding="utf-8")
    refs = "\n".join(f"ref table {n}" for n in ["_Measures", *TABLES])
    (DEF / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\n"
        "annotation __PBI_TimeIntelligenceEnabled = 0\n\nannotation PBI_ProTooling = [\"DevMode\"]\n\n"
        f"{refs}\n\nref cultureInfo en-US\n", encoding="utf-8")
    print(f"wrote {len(TABLES) + 1} tables, {len(RELATIONSHIPS)} relationships, {len(MEASURES)} measures to {DEF}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-folder", default=str(ROOT / "data" / "processed" / "powerbi") + "\\")
    a = ap.parse_args()
    main(a.data_folder)
