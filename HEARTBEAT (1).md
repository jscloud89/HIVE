# HEARTBEAT.md — Scout 🔍
# Scheduled pulses for market research operations
# Model: claude-sonnet-4-6 via OpenRouter (complex tasks)
#        openrouter/auto free tier (simple lookups)
# Cadence: Daily research runs + seasonal monitoring

---

## Operating Principle
The Scout runs on a tight research loop.
Every morning a new niche from the queue is investigated.
Every finding is structured as a waggle dance JSON.
No waggle dance = no deployment. Quality over speed.

---

## Scheduled Pulses

### 🌅 MORNING NICHE RESEARCH RUN
**When:** Every day at 07:00 (after Nurse morning briefing)
**Model:** claude-sonnet-4-6 via OpenRouter
**Est. cost per run:** ~$0.08-0.15
**Duration:** 15-20 minutes

```
TASK: Daily niche research

1. Read /data/research-queue.json
2. Select highest priority niche with status: queued
3. Update niche status to: in_progress

RESEARCH PROTOCOL:
  a. Search Etsy for top 20 listings in niche
  b. Record: titles, prices, review counts, review recency
  c. Note: bestseller badges, ad placements, estimated sales
  d. Check Google Trends 90-day trajectory
  e. Identify top 3 competitor shops — analyze their full catalog
  f. Check seasonal relevance (6 weeks forward)
  g. Calculate vigor score (0.0-10.0)

OUTPUT: Write complete waggle dance JSON to:
  /data/waggle/YYYY-MM-DD-[niche-slug].json

4. Update niche status in research-queue.json to: pending_queen
5. Write /data/waggle/pending-review.flag (triggers Queen)
6. Log session to MEMORY.md
```

---

### 🎃 SEASONAL OPPORTUNITY SCAN
**When:** Every Monday at 10:00
**Model:** openrouter/auto (free tier sufficient)
**Est. cost per run:** ~$0.00-0.02
**Purpose:** Flag upcoming seasonal windows 6 weeks ahead

```
TASK: Seasonal opportunity detection

1. Calculate date 6 weeks from today
2. Identify relevant holidays/seasons in that window:
   - US holidays (major + craft-relevant minor)
   - D&D/tabletop gaming events (conventions, releases)
   - Gaming release calendar (Worldbox updates)
   - Music industry seasonal patterns

3. For each relevant season:
   - Check if hive has listings ready
   - If gap exists → add HIGH PRIORITY niche to research-queue.json

OUTPUT: Write /data/scout/seasonal-scan-YYYY-MM-DD.json
  {
    "scan_date": "YYYY-MM-DD",
    "lookahead_date": "YYYY-MM-DD",
    "opportunities": [
      {
        "event": "event name",
        "date": "YYYY-MM-DD",
        "weeks_away": X,
        "relevant_departments": ["3d_printing", "digital"],
        "hive_ready": true|false,
        "action": "none|add_to_queue|urgent"
      }
    ]
  }

4. Log findings to MEMORY.md
```

---

### 📈 COMPETITOR MONITORING PULSE
**When:** Every Wednesday at 11:00
**Model:** openrouter/auto (free tier)
**Est. cost per run:** ~$0.00-0.03
**Purpose:** Track changes in active competitor shops

```
TASK: Competitor shop monitoring

1. Read /data/scout/competitor-watchlist.json
2. For each tracked shop (max 10):
   - Check for new listings added this week
   - Check for price changes on tracked products
   - Check for review velocity changes
   - Note any promotional activity

3. Flag significant changes:
   - New product in our active niche → alert Scout for analysis
   - Major price drop → alert Worker to review our pricing
   - Review surge → note as validation signal

OUTPUT: Append to /data/scout/competitor-log-YYYY-MM.jsonl
4. If significant change detected → notify Architect via Telegram summary
5. Log to MEMORY.md
```

---

### 🏪 ACTIVE SHOP PERFORMANCE CHECK
**When:** Every Friday at 09:00
**Model:** openrouter/auto (free tier)
**Est. cost per run:** ~$0.00-0.02
**Purpose:** Monitor our own Etsy shop metrics

```
TASK: Shop performance review

1. Check Etsy API for each active shop:
   - Views this week vs last week
   - Favorites added
   - Conversion rate
   - Search rank for primary keywords

2. Flag underperforming listings (views down >30% week-over-week)
3. Flag trending listings (views up >50%) → candidate for expansion

OUTPUT: Write /data/scout/shop-performance-YYYY-MM-DD.json
4. Include in Queen's weekly strategy input
5. Log to MEMORY.md
```

---

## Research Queue Management

The research queue lives at /data/research-queue.json
Scout owns this file. Maintain it in this format:

```json
{
  "queue": [
    {
      "niche": "Dark Academia Notion Templates",
      "slug": "dark-academia-notion-templates",
      "department": "digital",
      "priority": 1,
      "status": "queued|in_progress|pending_queen|approved|denied|abandoned",
      "added": "YYYY-MM-DD",
      "source": "seasonal_scan|architect|queen|manual",
      "notes": "optional context"
    }
  ],
  "last_updated": "YYYY-MM-DD HH:MM"
}
```

Priority 1 = highest. Re-sort after every Queen weekly strategy session.

---

## Cost Guard
- Simple lookups (trends, queue checks) → always use free tier first
- Only escalate to Sonnet when research requires multi-step reasoning
- Log model used per task in waggle dance JSON scout_notes
- Daily Scout budget target: $0.10-0.20 maximum

---

## MEMORY.md Update Protocol
After every session append:
```
[YYYY-MM-DD HH:MM] Task: [research|seasonal|competitor|performance]
Niche researched: [name] | Vigor: X.X
Model used: [model name] | Cost: $X.XX
Outcome: [pending_queen|denied|queued]
Queue depth: X niches remaining
```
