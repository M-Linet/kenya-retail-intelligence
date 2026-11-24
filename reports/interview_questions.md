# Interview preparation: Kenya Retail Intelligence

Practise answering aloud in under two minutes each. The "strong answer covers" notes are what an interviewer listens for, not a script.

## Business questions

1. **Walk me through this project in two minutes.**
   *Covers:* the fictional chain and the commercial director's concerns → synthetic data and why → PostgreSQL pipeline with cleaning → three headline findings with numbers (Nyali discount leakage, Kisumu/Eldoret stockouts, GP-negative promotions) → recommendations worth about KES 1.6M GP a year → limitations.

2. **Why did you use synthetic data? Doesn't that make the findings meaningless?**
   *Covers:* the public datasets reviewed (UCI Online Retail II lacks branches, cost, inventory and promotions); synthetic data was the honest option; I designed the broad mechanisms, so the value is in showing the method recovers and sizes them correctly; the magnitudes are emergent; and the injection manifest let me *verify* that cleaning works, which is impossible with real data.

3. **Revenue grew 10%. Why do you say growth is 6%?**
   *Covers:* like-for-like excludes Ruiru, which opened in June 2025; new-store revenue is not growth of the existing estate.

4. **Nyali is your second-biggest branch. Why flag it?**
   *Covers:* the margin bridge separates mix from discounts; mix margin is normal (19.8%); non-promo discounts are 2.58% of sales vs about 0.4%; discounts on ambient goods have no expiry reason; lowest margin in 23 of 24 months; Welch t-test. I would check override logs before concluding anything about staff behaviour.

5. **Should the chain stop all promotions?**
   *Covers:* no. Snacks and Personal Care promotions pay back. Staples promotions may still have a footfall role the analysis cannot measure, so they should be treated as a budgeted marketing cost with shallow depth and post-event review. The baseline method also has limits (no cannibalisation or halo measurement).

6. **What is the single action you would take first, and why?**
   *Covers:* Nyali overrides. It is the largest recurring value, the cheapest to fix (a till control), and quick to measure.

7. **How do you know the Kisumu/Eldoret problem is lead time and not demand?**
   *Covers:* the stockout rate stays high even where reorder levels match other branches; the problem is persistent rather than a spike; it is geographically consistent (the western branches). It is still an inference: I would ask the supply chain team for delivery lead times.

8. **What would you need to make this analysis production-grade at a real retailer?**
   *Covers:* daily or perpetual stock, supplier lead times, cost history with rebates, till override logs, a promotion calendar with control stores, scheduled refresh and data contracts.

## SQL questions

9. **How did you make sure joins didn't double-count revenue?** The semantic view has one row per sold line, and `dq_b02` proves its row count equals the item table. Basket counts come from `v_baskets`, never from counting lines.
10. **Explain `RANK` vs `ROW_NUMBER` vs `DENSE_RANK`. Where did you use each?** `ROW_NUMBER` for exactly five products per branch (q14); `RANK` for branch and product rankings where ties should share a rank (q04, q21).
11. **How does your month-over-month growth query work?** `LAG(revenue) OVER (ORDER BY month)` inside a CTE; running total with `SUM() OVER (ORDER BY …)`; 3-month average with `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW`.
12. **Why compute averages per calendar day using a date table?** Days with zero sales still count, and weekdays occur unequal numbers of times. Averaging only over days that had sales would bias the result upward.
13. **What's the difference between `WHERE` and `FILTER (WHERE …)`?** `WHERE` removes rows before aggregation; `FILTER` applies a condition to one aggregate, so one pass can produce Year 1 and Year 2 side by side.
14. **How did you build the promotion baseline?** Two CTEs: promotion-period lines by `promotion_id`, and the same product's full-price lines in the 28 days before `start_date`, both normalised per day.
15. **Why a staging schema with all-TEXT columns?** So the raw load never fails on bad values. The problems can be profiled in SQL first, then fixed deliberately rather than lost at load time.
16. **How would you speed up these queries on 100M rows?** Index the join and filter columns (already done for branch/date), use materialised views for the daily aggregates, partition the fact table by month, and avoid `COUNT(DISTINCT)` on the full fact table by pre-aggregating baskets.

## Python and statistics questions

17. **How did you decide which quantity outliers to remove?** I profiled by customer segment: Small Business bulk buys reach about 50 units, while every non-business line above 10 units was ≥100 with a ×100 pattern. So I quarantined those lines and kept real bulk purchases. Outliers were investigated, not deleted automatically.
18. **Why Spearman rather than Pearson correlation for revenue vs margin?** Product revenue is heavily skewed and the relationship need not be linear; Spearman uses ranks, so it is robust to both.
19. **Explain the t-test you ran. What are its assumptions?** Welch's two-sample t-test on monthly margins (Nyali vs the average of the other branches); unequal variances allowed. Months are treated as independent, which is approximate because of seasonality, but the effect (23 of 24 months lowest) does not depend on the test.
20. **Why are reusable functions in `src/` and not in the notebooks?** They can be tested (39 pytest tests), they are reused by both the pipeline and the notebooks, and the notebooks stay readable.
21. **How do you know the pandas and SQL numbers agree?** `test_revenue_reconciles_between_sql_and_pandas` recomputes revenue and gross profit from base tables in pandas and matches the view to 1e-9.
22. **Your forecast extension: why only baselines?** Any model must beat a seasonal naive benchmark to be worth its complexity. On the 12-week holdout, seasonal naive scored about 5% MAPE and a moving average about 7%. The forecast is optional and does not drive any recommendation.

## Power BI and DAX questions

23. **Describe your data model.** A star schema: `fact_sales` (line grain) and `fact_inventory` (weekly snapshot grain) with shared `dim_date`, `dim_branch` and `dim_product`, plus `dim_customer` (with an ANON row) and `dim_promotion`. Single-direction one-to-many relationships.
24. **Why is stock a semi-additive measure, and how did you handle it?** Balances add across branches but not across time. *Closing Stock Value* filters to the latest snapshot date; *Avg Stock Value* uses `AVERAGEX` over snapshot dates.
25. **Write a YoY measure.** `Revenue PY = CALCULATE([Revenue], DATEADD(dim_date[date], -1, YEAR))`, then `DIVIDE([Revenue] - [Revenue PY], [Revenue PY])`. It needs a marked date table.
26. **Why `DIVIDE` instead of `/`?** It handles division by zero and blanks without errors.
27. **How did you check the dashboard is right?** Cards are compared with `kpi_reconciliation.csv` (computed in SQL) across five filter scenarios; branch totals must sum to the chain total; segments must include Anonymous.
28. **Why is promotion incremental GP calculated in SQL and imported, rather than in DAX?** The baseline needs a different date window per promotion; that is clearer and easier to test in SQL, and DAX only summarises the result.

## "What I learned" prompts (have a real story ready)
- The difference between a metric that is *calculated correctly* and one that is *defined correctly* (ATV per line vs per basket; margin of totals vs average of margins).
- Simulating inventory made me realise that lost sales are invisible in POS data, which changed how I read "low sales".
- A weekly closing-stock snapshot initially showed almost no stockouts, because I recorded opening stock after deliveries. Switching to closing stock fixed the measurement, which taught me to ask *when* a snapshot is taken.
