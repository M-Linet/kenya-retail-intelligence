"""Generate the four report pages (PBIR format) of powerbi/SavannaFresh.pbip.

Each visual is declared below in a compact form and written as definition/pages/<page>/visuals/<id>/visual.json.
Close Power BI before running, then reopen the .pbip.

    python scripts/build_pbir_report.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "powerbi" / "SavannaFresh.Report"
DEFN = REP / "definition"
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.4.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.2.0/schema.json"
FIRST_PAGE = "1f454081e67d976f3ff0"          # page created by Power BI; reused as page 1
FIRST_VISUAL = "5b827285991325c48a29"        # visual created by Power BI; reused


def hid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


def lit(v: str) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def M(name: str) -> tuple:  # measure reference
    return ("Measure", "_Measures", name)


def C(table: str, col: str) -> tuple:  # column reference
    return ("Column", table, col)


def field(ref: tuple) -> dict:
    kind, ent, prop = ref
    return {kind: {"Expression": {"SourceRef": {"Entity": ent}}, "Property": prop}}


def projection(ref: tuple, active: bool = False) -> dict:
    p = {"field": field(ref), "queryRef": f"{ref[1]}.{ref[2]}", "nativeQueryRef": ref[2]}
    if active:
        p["active"] = True
    return p


def title_obj(text: str) -> dict:
    return {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'")}}]}


def visual(page, key, vtype, pos, roles=None, title=None, sort=None, objects=None, filters=None, vc_objects=None):
    x, y, w, h = pos
    v: dict = {"visualType": vtype}
    if roles:
        qs = {}
        for role, refs in roles.items():
            qs[role] = {"projections": [projection(r, active=(role == "Category" and i == 0 and vtype != "scatterChart"))
                                        for i, r in enumerate(refs)]}
        v["query"] = {"queryState": qs}
        if sort:
            ref, direction = sort
            v["query"]["sortDefinition"] = {"sort": [{"field": field(ref), "direction": direction}], "isDefaultSort": False}
    if vtype in ("lineChart", "clusteredBarChart", "clusteredColumnChart", "scatterChart"):
        # field names such as "branch_short" make poor axis titles; the visual title carries the meaning
        objects = {**(objects or {}),
                   "categoryAxis": [{"properties": {"showAxisTitle": lit("false")}}],
                   "valueAxis": [{"properties": {"showAxisTitle": lit("false")}}]}
    if vtype == "scatterChart":
        objects["categoryLabels"] = [{"properties": {"show": lit("true")}}]
    if objects:
        v["objects"] = objects
    vco = {}
    if title:
        vco.update(title_obj(title))
    if vc_objects:
        vco.update(vc_objects)
    if vco:
        v["visualContainerObjects"] = vco
    v["drillFilterOtherVisuals"] = True
    name = FIRST_VISUAL if (page == FIRST_PAGE and key == "title") else hid(page, key)
    out = {"$schema": VC_SCHEMA, "name": name,
           "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": 0}, "visual": v}
    if filters:
        out["filterConfig"] = {"filters": filters}
    return name, out


def textbox(page, key, text, pos, size="16pt"):
    objs = {"general": [{"properties": {"paragraphs": [{"textRuns": [
        {"value": text, "textStyle": {"fontWeight": "bold", "fontSize": size}}]}]}}]}
    return visual(page, key, "textbox", pos, objects=objs)


def subtitle(page, key, text, pos):
    objs = {"general": [{"properties": {"paragraphs": [{"textRuns": [
        {"value": text, "textStyle": {"fontSize": "10pt", "color": "#6b6a64"}}]}]}}]}
    return visual(page, key, "textbox", pos, objects=objs)


def card(page, key, measure, pos, label=None):
    return visual(page, key, "card", pos, roles={"Values": [M(measure)]},
                  objects={"categoryLabels": [{"properties": {"show": lit("true")}}],
                           "labels": [{"properties": {"fontSize": lit("20D")}}]},
                  title=None)


def slicer(page, key, ref, pos, dropdown=True):
    objs = {"data": [{"properties": {"mode": lit("'Dropdown'")}}]} if dropdown else None
    return visual(page, key, "slicer", pos, roles={"Values": [ref]}, objects=objs)


def not_equal_filter(table: str, col: str, value: str) -> dict:
    return {"name": hid(table, col, value), "field": field(C(table, col)), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "f", "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"Not": {"Expression": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": col}}],
                           "Values": [[{"Literal": {"Value": f"'{value}'"}}]]}}}}}]}}


def header(page, title, question):
    vs = [textbox(page, "title", title, (20, 2, 560, 40)),
          subtitle(page, "subtitle", question + "  ·  Fictional company, synthetic data", (20, 38, 560, 32)),
          slicer(page, "s_date", C("dim_date", "date"), (600, 4, 220, 62), dropdown=False),
          slicer(page, "s_county", C("dim_branch", "county"), (830, 8, 140, 56)),
          slicer(page, "s_type", C("dim_branch", "branch_type"), (980, 8, 140, 56)),
          slicer(page, "s_cat", C("dim_product", "category"), (1130, 8, 140, 56))]
    return vs


def cards_row(page, measures, y=76, h=92):
    n = len(measures)
    w = (1240 - 10 * (n - 1)) // n
    return [card(page, f"card_{m}", m, (20 + i * (w + 10), y, w, h)) for i, m in enumerate(measures)]


PAGES = []

# ---- Page 1: Executive overview -------------------------------------------------------------
p = FIRST_PAGE
v = header(p, "Executive overview", "Is the business growing, and is the growth profitable?")
v += cards_row(p, ["Revenue", "Gross Profit", "Gross Margin %", "LFL Growth Y2 vs Y1 %", "Transactions", "ATV", "Units Sold"])
v.append(visual(p, "trend", "lineChart", (20, 180, 740, 265),
                roles={"Category": [C("dim_date", "year_month")], "Y": [M("Revenue"), M("Revenue PY")]},
                title="Monthly revenue vs same month last year (KES)", sort=(C("dim_date", "year_month"), "Ascending")))
v.append(visual(p, "branch_rev", "clusteredBarChart", (770, 180, 490, 265),
                roles={"Category": [C("dim_branch", "branch_short")], "Y": [M("Revenue")]},
                title="Revenue by branch (KES)", sort=(M("Revenue"), "Descending")))
v.append(visual(p, "cat_rev_gp", "clusteredBarChart", (20, 455, 620, 260),
                roles={"Category": [C("dim_product", "category")], "Y": [M("Revenue"), M("Gross Profit")]},
                title="Revenue vs gross profit by category (KES)", sort=(M("Revenue"), "Descending")))
v.append(visual(p, "top_products", "tableEx", (650, 455, 610, 260),
                roles={"Values": [C("dim_product", "product_name"), C("dim_product", "category"), M("Revenue"),
                                  M("Gross Profit"), M("Gross Margin %")]},
                title="Products ranked by gross profit", sort=(M("Gross Profit"), "Descending")))
PAGES.append((p, "Executive overview", v))

# ---- Page 2: Product & profitability -----------------------------------------------------------
p = hid("page2")
v = header(p, "Product & profitability", "Where is margin made, and where is it lost?")
v += cards_row(p, ["Gross Margin %", "Discount Rate %", "Non-Promo Discount % of Sales", "GP-Positive Promotions %",
                   "Incremental GP per KES Discount"])
v.append(visual(p, "cat_share", "clusteredBarChart", (20, 180, 620, 265),
                roles={"Category": [C("dim_product", "category")], "Y": [M("Revenue Share of Selection"), M("GP Share of Selection")]},
                title="Share of revenue vs share of gross profit, by category", sort=(M("Revenue Share of Selection"), "Descending")))
v.append(visual(p, "branch_bridge", "clusteredBarChart", (650, 180, 610, 265),
                roles={"Category": [C("dim_branch", "branch_short")],
                       "Y": [M("Margin Before Discounts %"), M("Gross Margin %"), M("Non-Promo Discount % of Sales")]},
                title="Margin before discounts vs after, and non-promo discount, by branch", sort=(M("Gross Margin %"), "Ascending")))
v.append(visual(p, "scatter", "scatterChart", (20, 455, 620, 260),
                roles={"Category": [C("dim_product", "product_name")], "Series": [C("dim_product", "category")],
                       "X": [M("Revenue")], "Y": [M("Gross Margin %")]},
                title="Products: revenue vs gross margin (high revenue is mostly low margin)"))
v.append(visual(p, "promo_table", "tableEx", (650, 455, 610, 260),
                roles={"Values": [C("promo_performance", "promotion_id"), C("promo_performance", "product_name"),
                                  C("promo_performance", "category"), C("promo_performance", "discount_percentage"),
                                  C("promo_performance", "unit_uplift_pct"), C("promo_performance", "incremental_gp_kes"),
                                  C("promo_performance", "outcome")]},
                title="Promotion payback vs 28-day full-price baseline", sort=(C("promo_performance", "incremental_gp_kes"), "Ascending")))
PAGES.append((p, "Product & profitability", v))

# ---- Page 3: Inventory intelligence ------------------------------------------------------------
p = hid("page3")
v = header(p, "Inventory intelligence", "Are the shelves full of the right things?")
v += cards_row(p, ["Closing Stock Value", "Stockout Rate %", "Slow-Moving Stock Value", "Slow-Moving Share %",
                   "Inventory Turnover", "Avg Weeks of Stock"])
v.append(visual(p, "stockout_branch", "clusteredBarChart", (20, 180, 400, 265),
                roles={"Category": [C("dim_branch", "branch_short")], "Y": [M("Stockout Rate %")]},
                title="Stockout rate by branch (% of product-weeks at zero)", sort=(M("Stockout Rate %"), "Descending")))
v.append(visual(p, "stockout_trend", "lineChart", (430, 180, 450, 265),
                roles={"Category": [C("dim_date", "year_month")], "Series": [C("dim_branch", "county")], "Y": [M("Stockout Rate %")]},
                title="Stockout rate by month and county", sort=(C("dim_date", "year_month"), "Ascending")))
v.append(visual(p, "turnover_cat", "clusteredBarChart", (890, 180, 370, 265),
                roles={"Category": [C("dim_product", "category")], "Y": [M("Inventory Turnover")]},
                title="Inventory turnover by category (times / year)", sort=(M("Inventory Turnover"), "Descending")))
v.append(visual(p, "position_table", "tableEx", (20, 455, 1240, 260),
                roles={"Values": [C("dim_branch", "branch_short"), C("dim_product", "product_name"), C("dim_product", "category"),
                                  C("fact_inventory_position", "stock_status"), C("fact_inventory_position", "stock_quantity"),
                                  C("fact_inventory_position", "reorder_level"), C("fact_inventory_position", "avg_weekly_units_12w"),
                                  C("fact_inventory_position", "weeks_of_cover"), C("fact_inventory_position", "stockout_weeks_12w"),
                                  C("fact_inventory_position", "stock_value_at_cost")]},
                title="Action list: every branch-product not in a healthy position (latest count)",
                sort=(C("fact_inventory_position", "stock_value_at_cost"), "Descending"),
                filters=[not_equal_filter("fact_inventory_position", "stock_status", "Healthy")]))
PAGES.append((p, "Inventory intelligence", v))

# ---- Page 4: Branch performance -----------------------------------------------------------------
p = hid("page4")
v = header(p, "Branch performance", "Which branches need management attention, and why?")
v.append(visual(p, "scorecard", "pivotTable", (20, 76, 1240, 330),
                roles={"Rows": [C("dim_branch", "branch_short")],
                       "Values": [M("Revenue"), M("Revenue Growth Y2 vs Y1 %"), M("Gross Margin %"), M("Margin vs Chain (pts)"),
                                  M("Non-Promo Discount % of Sales"), M("Stockout Rate %"), M("Slow-Moving Share %"), M("ATV")]},
                title="Branch scorecard (watch: margin vs chain, non-promo discount, stockout rate, growth)",
                sort=(M("Revenue"), "Descending")))
v.append(visual(p, "branch_scatter", "scatterChart", (20, 415, 620, 300),
                roles={"Category": [C("dim_branch", "branch_short")], "X": [M("Revenue")], "Y": [M("Gross Margin %")],
                       "Size": [M("Transactions")]},
                title="Revenue vs gross margin by branch (bubble = transactions)"))
v.append(visual(p, "county", "clusteredBarChart", (650, 415, 610, 300),
                roles={"Category": [C("dim_branch", "county")], "Y": [M("Revenue"), M("Gross Profit")]},
                title="Revenue and gross profit by county (KES)", sort=(M("Revenue"), "Descending")))
PAGES.append((p, "Branch performance", v))


def write_theme() -> None:
    src = ROOT / "powerbi" / "savanna_theme.json"
    dst = REP / "StaticResources" / "RegisteredResources" / "savanna_theme.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    rj = json.loads((DEFN / "report.json").read_text(encoding="utf-8"))
    rj["themeCollection"]["customTheme"] = {"name": "savanna_theme.json", "reportVersionAtImport": "5.60",
                                            "type": "RegisteredResources"}
    pk = [r for r in rj["resourcePackages"] if r["name"] != "RegisteredResources"]
    pk.append({"name": "RegisteredResources", "type": "RegisteredResources",
               "items": [{"name": "savanna_theme.json", "path": "savanna_theme.json", "type": "CustomTheme"}]})
    rj["resourcePackages"] = pk
    (DEFN / "report.json").write_text(json.dumps(rj, indent=2), encoding="utf-8")


def main() -> None:
    for page, display, visuals in PAGES:
        pdir = DEFN / "pages" / page
        (pdir / "visuals").mkdir(parents=True, exist_ok=True)
        (pdir / "page.json").write_text(json.dumps({"$schema": PAGE_SCHEMA, "name": page, "displayName": display,
                                                    "displayOption": "FitToPage", "height": 720, "width": 1280}, indent=2),
                                        encoding="utf-8")
        for i, (name, vj) in enumerate(visuals):
            vj["position"]["tabOrder"] = i
            vj["position"]["z"] = i
            d = pdir / "visuals" / name
            d.mkdir(exist_ok=True)
            (d / "visual.json").write_text(json.dumps(vj, indent=2), encoding="utf-8")
    (DEFN / "pages" / "pages.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p for p, _, _ in PAGES], "activePageName": PAGES[0][0]}, indent=2), encoding="utf-8")
    write_theme()
    print(f"wrote {len(PAGES)} pages, {sum(len(v) for _, _, v in PAGES)} visuals")


if __name__ == "__main__":
    main()
