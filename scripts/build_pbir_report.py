"""Generate the four report pages (PBIR format) of powerbi/SavannaFresh.pbip in the editorial style.

Layout and colour rules live in scripts/pbi_editorial.py (shared with the other portfolio projects).
Close Power BI before running, then reopen the .pbip.

    python scripts/build_pbir_report.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pbi_editorial as ed  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PB = ROOT / "powerbi"
REP = PB / "SavannaFresh.Report"
DEFN = REP / "definition"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.2.0/schema.json"
FIRST_PAGE = "1f454081e67d976f3ff0"          # page created by Power BI; reused as page 1
STRIP = "kikoi_strip.png"
THEME = "savanna_theme.json"

# Colour-blind-safe data colours (validated, see powerbi/README.md): blue = focus, orange = problem, grey = context
FOCUS, PROBLEM, CONTEXT = "#2a78d6", "#eb6834", "#a3a199"


def page_id(*parts) -> str:  # same ids as the original report, so Power BI keeps its page folders
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


BRAND = ed.Brand(
    name="SAVANNA FRESH", tagline="Supermarket performance · 12 branches · Nov 2024 – Oct 2026",
    disclaimer="fictional retailer · synthetic data",
    masthead="#173d2a", accent="#eda100", accent_text="#173d2a", tab="#24543b", tab_hover="#2f6a4b",
    paper="#f7f3ea", panel="#ffffff", panel_alt="#faf7f0", ink="#2b2b29", ink2="#5f5d56", hairline="#e4ddcc", grid="#ece6d8",
    kicker="#a86f00", headline="#173d2a", number="#173d2a", focus=FOCUS, problem=PROBLEM, context=CONTEXT,
    strip=STRIP, todo_bg="#173d2a", todo_ink="#f4efe2", todo_head="#eda100", shadow=True)
ed.configure(BRAND, {
    "month_start": "Month", "branch_short": "Branch", "county": "County", "category": "Category", "date": "Date",
    "outcome": "Outcome", "stock_status": "Stock status", "Revenue PY": "Same month last year",
    "Revenue Share of All Categories": "Share of sales", "GP Share of All Categories": "Share of gross profit",
    "Non-Promo Discount % of Sales": "Non-promo discount", "Stockout Rate %": "Stockout rate",
    "Promotions Measured": "Promotions", "Position Stock Value": "Stock value (KES)",
    "Revenue Growth Y2 vs Y1 %": "Growth", "Margin vs Chain (pts)": "Margin vs chain", "Gross Margin %": "Margin",
    "Branch Status": "Status", "Slow-Moving Share %": "Slow stock", "Inventory Turnover": "Turnover (x/yr)"}, seed="SavannaFresh")
Ms, Co, lit = ed.Ms, ed.Co, ed.lit
visual, tile, todo, story, xline = ed.visual, ed.tile, ed.todo, ed.story, ed.xline
HERO, LOW1, LOW2 = ed.HERO, ed.LOW1, ed.LOW2
MS = Co("dim_date", "month_start")
BR = Co("dim_branch", "branch_short")


def masthead(p):
    return ed.masthead(p, [("s_date", Co("dim_date", "date"), 236, False), ("s_county", Co("dim_branch", "county"), 120, True),
                           ("s_cat", Co("dim_product", "category"), 120, True)])


def not_in(key, table, column, values):
    return {"name": ed.hid(key), "field": ed.fld(Co(table, column)), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"Not": {"Expression": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}],
                           "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}}}]}}


def only(key, table, column, values):
    f = not_in(key, table, column, values)
    f["filter"]["Where"][0]["Condition"] = f["filter"]["Where"][0]["Condition"]["Not"]["Expression"]
    return f


TOP6 = ["Staples", "Dairy", "Beverages", "Household & Cleaning", "Fresh Produce", "Baby Care"]


def build_pages():
    pages = []

    # ---- 1 Overview ------------------------------------------------------------------------------
    p = FIRST_PAGE
    v = masthead(p)
    v.append(story(p, "Overview", "Sales up 10%, but only 6% like-for-like",
                   "KES 489.6M of sales and KES 91.2M of gross profit over two years (18.6% margin). Ruiru, opened in June 2025, "
                   "added the other four points of growth."))
    v.append(visual(p, "trend", "lineChart", HERO, roles={"Category": [MS], "Y": [Ms("Revenue"), Ms("Revenue PY")]},
                    title="Monthly sales (KES)", subtitle="Blue: this year · grey: same month last year · dashed line: Ruiru opens",
                    sort=(MS, "Ascending"),
                    objects={**ed.measure_series_fill({"Revenue": FOCUS, "Revenue PY": CONTEXT}),
                             "xAxisReferenceLine": [xline("2025-06-01", "Ruiru opens", 1, PROBLEM)]}))
    v.append(visual(p, "branch_rev", "clusteredBarChart", LOW1, roles={"Category": [Co("dim_branch", "county")], "Y": [Ms("Revenue")]},
                    title="Nairobi's three branches bring 30%", subtitle="Sales by county, KES",
                    sort=(Ms("Revenue"), "Descending"), objects=ed.measure_series_fill({"Revenue": FOCUS})))
    v.append(visual(p, "cat_share", "clusteredBarChart", LOW2,
                    roles={"Category": [Co("dim_product", "category")], "Y": [Ms("Revenue Share of All Categories"), Ms("GP Share of All Categories")]},
                    title="Staples sell, fresh food earns", subtitle="Grey: share of all sales · blue: share of all profit",
                    sort=(Ms("Revenue Share of All Categories"), "Descending"),
                    objects=ed.measure_series_fill({"Revenue Share of All Categories": CONTEXT, "GP Share of All Categories": FOCUS}),
                    filters=[only("f_four", "dim_product", "category", ["Staples", "Dairy", "Beverages", "Fresh Produce"])]))
    v += [tile(p, "Revenue", 90, "Sales (KES millions)", sub_measure="Δ Revenue", units=(1000000, 1)),
          tile(p, "LFL Growth Y2 vs Y1 %", 192, "Like-for-like growth", sub="11 branches open both years"),
          tile(p, "Gross Profit", 294, "Gross profit (KES millions)", sub_measure="Δ Gross Profit", units=(1000000, 1)),
          tile(p, "Gross Margin %", 396, "Gross margin", sub_measure="Δ Gross Margin"),
          todo(p, ["Stop Nyali's off-promotion discounting",
                   "Fix the Kisumu and Eldoret supply route",
                   "Visit Machakos: the only branch shrinking"], 498, 214)]
    pages.append((p, "Overview", v))

    # ---- 2 Profitability -------------------------------------------------------------------------
    p = page_id("page2")
    v = masthead(p)
    v.append(story(p, "Profitability", "Nyali discounts away its margin",
                   "Nyali discounts 2.6% of sales outside any promotion, six times the chain norm, so its margin sits 1.2 points below "
                   "the chain. Promotions are no better: 74 of 103 lost gross profit."))
    v.append(visual(p, "npd", "clusteredColumnChart", HERO, roles={"Category": [BR], "Y": [Ms("Non-Promo Discount % of Sales")]},
                    title="Discounts given outside any promotion", subtitle="% of gross sales · orange: Nyali",
                    sort=(Ms("Non-Promo Discount % of Sales"), "Descending"), objects=ed.measure_fill("Colour Nyali")))
    v.append(visual(p, "outcome", "clusteredBarChart", LOW1, roles={"Category": [Co("promo_performance", "outcome")], "Y": [Ms("Promotions Measured")]},
                    title="Most promotions lose gross profit", subtitle="vs a 28-day full-price baseline · orange: GP-negative",
                    sort=(Ms("Promotions Measured"), "Descending"), objects=ed.measure_fill("Colour Promo Outcome")))
    v.append(visual(p, "margin_cat", "clusteredBarChart", LOW2, roles={"Category": [Co("dim_product", "category")], "Y": [Ms("Gross Margin %")]},
                    title="Staples carry the thinnest margin", subtitle="Gross margin, six largest categories", sort=(Ms("Gross Margin %"), "Descending"),
                    objects=ed.measure_series_fill({"Gross Margin %": FOCUS}), filters=[only("f_top6b", "dim_product", "category", TOP6)]))
    v += [tile(p, "Gross Margin %", 90, "Gross margin", sub_measure="Δ Gross Margin"),
          tile(p, "Non-Promo Discount % of Sales", 192, "Non-promo discount (% of sales)", sub="chain norm about 0.4%"),
          tile(p, "GP-Positive Promotions %", 294, "Promotions that paid back", sub_measure="Promo Outcome Text"),
          tile(p, "Incremental GP per KES Discount", 396, "Extra profit per KES of discount", sub="below 0 = promotions lost profit overall"),
          todo(p, ["Cap manager discounts at Nyali; review weekly",
                   "Cut promotion depth on eggs, rice, juice and sugar",
                   "Measure every promotion against its baseline"], 498, 214)]
    pages.append((p, "Profitability", v))

    # ---- 3 Inventory -----------------------------------------------------------------------------
    p = page_id("page3")
    v = masthead(p)
    v.append(story(p, "Inventory", "Kisumu and Eldoret keep running out of stock",
                   "Shelves were empty in 23% of Kisumu's and 19% of Eldoret's product-weeks, against about 6% at most branches. Both "
                   "sit at the end of the western supply route. KES 0.5M of stock is slow or unsold."))
    v.append(visual(p, "stockout_branch", "clusteredColumnChart", HERO, roles={"Category": [BR], "Y": [Ms("Stockout Rate %")]},
                    title="Stockout rate by branch", subtitle="% of product-weeks at zero stock · orange: above 15%",
                    sort=(Ms("Stockout Rate %"), "Descending"), objects=ed.measure_fill("Colour Stockout Branch")))
    v.append(visual(p, "stockout_trend", "lineChart", LOW1, roles={"Category": [MS], "Y": [Ms("Stockout Rate %")]},
                    title="Stockout rate by month", subtitle="All selected branches", sort=(MS, "Ascending"),
                    objects=ed.measure_series_fill({"Stockout Rate %": FOCUS})))
    v.append(visual(p, "status", "clusteredBarChart", LOW2,
                    roles={"Category": [Co("fact_inventory_position", "stock_status")], "Y": [Ms("Position Stock Value")]},
                    title="Stock that is not healthy", subtitle="Value at cost, latest count · orange: slow or not selling",
                    sort=(Ms("Position Stock Value"), "Descending"), objects=ed.measure_fill("Colour Stock Status"),
                    filters=[not_in("f_healthy", "fact_inventory_position", "stock_status", ["Healthy"])]))
    v += [tile(p, "Stockout Rate %", 90, "Stockout rate", sub="product-weeks at zero stock"),
          tile(p, "Closing Stock Value", 192, "Stock on hand (KES millions)", sub="at cost, latest weekly count", units=(1000000, 1)),
          tile(p, "Slow-Moving Stock Value", 294, "Slow or unsold stock (KES millions)", sub=">26 weeks of cover or no sales in 12 weeks", units=(1000000, 2)),
          tile(p, "Inventory Turnover", 396, "Inventory turnover (times a year)", sub="cost of sales ÷ average stock"),
          todo(p, ["Raise reorder levels in Kisumu and Eldoret",
                   "Add a second weekly delivery on the western route",
                   "Clear slow stock with markdowns, not promotions"], 498, 214)]
    pages.append((p, "Inventory", v))

    # ---- 4 Branches ------------------------------------------------------------------------------
    p = page_id("page4")
    v = masthead(p)
    v.append(story(p, "Branches", "Four branches to watch, for four reasons",
                   "Nyali for margin, Kisumu and Eldoret for availability, and Machakos for falling sales (−11.9%) despite normal margin "
                   "and stock. Ruiru opened in June 2025, so it has no year-on-year figure."))
    score = visual(p, "scorecard", "tableEx", (20, 200, 840, 316),
                   roles={"Values": [BR, Ms("Revenue"), Ms("Revenue Growth Y2 vs Y1 %"), Ms("Gross Margin %"), Ms("Margin vs Chain (pts)"),
                                     Ms("Non-Promo Discount % of Sales"), Ms("Stockout Rate %"), Ms("Branch Status")]},
                   title="Branch scorecard", subtitle="Watch = stockouts above 15%, margin more than 1 pt below chain, or sales falling",
                   sort=(Ms("Revenue"), "Descending"),
                   objects={"values": [{"properties": {"fontColor": ed.mcol("Colour Branch Status")}, "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "_Measures.Branch Status"}}],
                            "total": [{"properties": {"totals": lit("false")}}]})
    v.append(score)
    v.append(visual(p, "growth", "clusteredColumnChart", (20, 526, 840, 186), roles={"Category": [BR], "Y": [Ms("Revenue Growth Y2 vs Y1 %")]},
                    title="Every established branch grew except Machakos", subtitle="Sales growth, year 2 vs year 1 · orange: falling · Ruiru excluded",
                    sort=(Ms("Revenue Growth Y2 vs Y1 %"), "Descending"), objects=ed.measure_fill("Colour Growth"),
                    filters=[not_in("f_ruiru", "dim_branch", "branch_short", ["Ruiru"])]))
    v += [tile(p, "Revenue Growth Y2 vs Y1 %", 90, "Chain sales growth", sub_measure="LFL Text"),
          tile(p, "Chain Gross Margin %", 192, "Chain gross margin", sub="every branch is compared with this"),
          tile(p, "ATV", 294, "Average basket (KES)", sub_measure="Δ ATV"),
          todo(p, ["Nyali: discount controls and a margin target",
                   "Kisumu, Eldoret: supply fix before any expansion",
                   "Machakos: competitor and footfall check in 30 days",
                   "Ruiru: judge it on year-2 like-for-like"], 396, 316)]
    pages.append((p, "Branches", v))
    return pages


def write_report() -> tuple[int, int]:
    reg = REP / "StaticResources" / "RegisteredResources"
    reg.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PB / THEME, reg / THEME)
    shutil.copyfile(PB / STRIP, reg / STRIP)
    rj_path = DEFN / "report.json"
    rj = json.loads(rj_path.read_text(encoding="utf-8"))
    rj["themeCollection"]["customTheme"] = {"name": THEME, "reportVersionAtImport": "5.60", "type": "RegisteredResources"}
    rj["resourcePackages"] = [r for r in rj["resourcePackages"] if r["name"] != "RegisteredResources"] + [
        {"name": "RegisteredResources", "type": "RegisteredResources",
         "items": [{"name": THEME, "path": THEME, "type": "CustomTheme"}, {"name": STRIP, "path": STRIP, "type": "Image"}]}]
    rj_path.write_text(json.dumps(rj, indent=2), encoding="utf-8")

    if (DEFN / "pages").exists():
        shutil.rmtree(DEFN / "pages")
    pages = build_pages()
    for page, display, visuals in pages:
        pdir = DEFN / "pages" / page
        (pdir / "visuals").mkdir(parents=True)
        (pdir / "page.json").write_text(json.dumps({"$schema": PAGE_SCHEMA, "name": page, "displayName": display, "displayOption": "FitToPage",
                                                    "height": 720, "width": 1280, "objects": ed.page_objects()}, indent=2), encoding="utf-8")
        for i, vj in enumerate(visuals):
            if vj["visual"]["visualType"] in ("clusteredBarChart", "clusteredColumnChart"):  # labels outside the bar: readable on any fill
                vj["visual"]["objects"]["labels"][0]["properties"]["labelPosition"] = lit("'OutsideEnd'")
            vj["position"]["tabOrder"] = i
            vj["position"]["z"] = i
            (pdir / "visuals" / vj["name"]).mkdir()
            (pdir / "visuals" / vj["name"] / "visual.json").write_text(json.dumps(vj, indent=2), encoding="utf-8")
    (DEFN / "pages" / "pages.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p for p, _, _ in pages], "activePageName": pages[0][0]}, indent=2), encoding="utf-8")
    return len(pages), sum(len(v) for _, _, v in pages)


if __name__ == "__main__":
    n_pages, n_visuals = write_report()
    print(f"wrote {n_pages} pages, {n_visuals} visuals")
