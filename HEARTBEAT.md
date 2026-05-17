# HEARTBEAT.md — The Auditor 🧾
# Per-print P&L calculation schedule
# Model: Local free models — $0.00 (pure math, no LLM needed)
# Cadence: After every print completion + monthly report

---

## Pulse 1 — POST-PRINT P&L — Triggered by Foreman
**When:** Foreman writes print completion to /data/messages/
**Model:** Local Python script — no LLM needed
**Cost:** $0.00
**Duration:** < 10 seconds

```
TASK: Calculate per-print P&L

1. Read from Foreman: {job_id, grams_used, print_time_hours}
2. Read from Quartermaster: cost_per_gram for that filament
3. Read from active order: sale_price, platform, shipping_charged
4. Apply P&L formula from SOUL.md
5. Write job P&L JSON to /data/auditor/jobs/[job_id].json
6. Check margin threshold:
   < 15% → alert Architect via Telegram
   negative → IMMEDIATE alert + flag to Queen
7. POST net_profit to Chancellor:
   POST http://172.20.0.20:8001/revenue
   (Chancellor applies Honey Split automatically)
8. Log to MEMORY.md
```

---

## Pulse 2 — WEEKLY MARGIN REVIEW — Saturday 09:00
**Model:** Local — simple aggregation
**Cost:** $0.00

```
TASK: Weekly product margin analysis

1. Read all job JSONs from past 7 days
2. Group by product, calculate:
   - avg margin %
   - total units sold
   - total profit
   - trend vs prior week
3. Flag products with margin decline > 5% week-over-week
4. Write /data/auditor/weekly-margins-[date].json
5. Send Telegram summary to Architect:

   🧾 WEEKLY MARGIN REPORT
   Top performer: [product] — XX% margin
   Watch list: [product] — XX% (down from XX%)
   Total profit this week: $XXX.XX
   Units completed: X
```

---

## Pulse 3 — MONTHLY PRODUCT REPORT — 1st of Month 08:30
**Model:** Local — aggregation + table generation
**Cost:** $0.00

```
TASK: Monthly profitability ranking

1. Aggregate all jobs from prior month
2. Rank products by total profit contribution
3. Calculate per-product: units, avg margin, total profit, trend
4. Generate ranked markdown table
5. Save to /data/auditor/monthly-[YYYY-MM].md
6. Send to Architect via Telegram summary
7. Feed data to Queen monthly financial review
```

---

## Crontab Entries
```bash
# Weekly margin review
0 9 * * 6 openclaw run auditor "Run weekly margin review from HEARTBEAT.md" >> /var/log/hive-auditor.log 2>&1

# Monthly product report
30 8 1 * * openclaw run auditor "Run monthly product report from HEARTBEAT.md" >> /var/log/hive-auditor.log 2>&1
```

---

## Cost Guard
All calculations: local Python — $0.00
Monthly Auditor cost: $0.00

## MEMORY.md Protocol
```
[YYYY-MM-DD] Job: [id] | Product: [name] | Platform: [etsy|ebay]
Revenue: $X.XX | COGS: $X.XX | Fees: $X.XX | Net: $X.XX | Margin: X%
Filament: Xg @ $X.XX/g | Print time: Xh | Electricity: $X.XX
Status: [healthy|acceptable|thin|danger|negative]
```
