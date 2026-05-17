#!/usr/bin/env python3
"""
scout.py — The Hive's Forager Scout
workspace-scout · Researches niches and produces waggle dance JSON for Queen
Usage: python3 scout.py [--category "Etsy"] [--dry-run] [--force-slug "slug"]
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Run: sudo apt install python3-bs4 && pip3 install requests --break-system-packages")
    sys.exit(1)

# ── Paths ────────────────────────────────────────────────────
WORKSPACE    = Path(__file__).parent
HIVE_ROOT    = WORKSPACE.parent
PHASE1_DIR   = Path.home() / "hive-phase1"
DATA_DIR     = PHASE1_DIR / "data"
WAGGLE_DIR   = DATA_DIR / "waggle"
SCOUT_DIR    = DATA_DIR / "scout"
LOG_DIR      = DATA_DIR / "logs"
MEMORY_FILE  = WORKSPACE / "MEMORY.md"
QUEUE_FILE   = DATA_DIR / "research-queue.json"
SOUL_FILE    = WORKSPACE / "SOUL.md"

# ── Config ───────────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_SONNET   = "anthropic/claude-sonnet-4-6"
MODEL_FLASH    = "google/gemini-2.5-flash-lite"
MODEL_AUTO     = "openrouter/auto"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def load_env():
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def load_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    with open(QUEUE_FILE) as f:
        return json.load(f)

def save_queue(queue: list):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)

def pick_task(queue: list, category_filter: str = None, force_slug: str = None) -> dict:
    """Pick next pending task from queue."""
    pending = [t for t in queue if t.get("status") == "pending"]
    if force_slug:
        pending = [t for t in pending if t.get("slug") == force_slug]
    if category_filter:
        pending = [t for t in pending if t.get("category", "").lower() == category_filter.lower()]
    if not pending:
        return None
    return sorted(pending, key=lambda x: x.get("priority", 99))[0]

# ── Scrapers ─────────────────────────────────────────────────

def scrape_etsy_search(query: str, max_listings: int = 20) -> list:
    """Scrape Etsy search results for a category query."""
    url = f"https://www.etsy.com/search?q={urllib.parse.quote(query)}&explicit=1"
    listings = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️  Etsy returned {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract listing cards
        cards = soup.find_all("div", {"data-listing-id": True})[:max_listings]
        if not cards:
            # Fallback: look for listing links
            links = soup.find_all("a", href=re.compile(r"/listing/"))[:max_listings]
            for link in links:
                title = link.get("title") or link.get_text(strip=True)
                if title and len(title) > 10:
                    listings.append({"title": title, "price": "N/A", "reviews": "N/A"})
            return listings

        for card in cards:
            title_el = card.find(["h3", "h2", "span"], class_=re.compile(r"title|name", re.I))
            price_el = card.find("span", class_=re.compile(r"price|cost", re.I))
            title = title_el.get_text(strip=True) if title_el else "Unknown"
            price = price_el.get_text(strip=True) if price_el else "N/A"
            listings.append({"title": title, "price": price, "reviews": "N/A"})

        time.sleep(random.uniform(2, 4))  # polite delay

    except Exception as e:
        print(f"  ⚠️  Etsy scrape error: {e}")

    return listings

def scrape_etsy_trending(category_hint: str) -> list:
    """Get trending searches related to category."""
    queries = [
        f"3d printed {category_hint}",
        f"handmade {category_hint}",
        category_hint
    ]
    all_listings = []
    for q in queries[:2]:
        print(f"  🔍 Searching Etsy: '{q}'")
        results = scrape_etsy_search(q, max_listings=15)
        all_listings.extend(results)
        time.sleep(1)
    return all_listings

def scrape_ebay_search(query: str) -> list:
    """Scrape eBay search for utility niche gaps."""
    url = f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote(query)}&_sop=12"
    listings = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.find_all("li", class_=re.compile(r"s-item"))[:15]

        for item in items:
            title_el = item.find("span", role="heading")
            price_el = item.find("span", class_=re.compile(r"s-item__price"))
            sold_el  = item.find("span", class_=re.compile(r"s-item__hotness|SOLD"))

            title = title_el.get_text(strip=True) if title_el else ""
            price = price_el.get_text(strip=True) if price_el else "N/A"
            sold  = sold_el.get_text(strip=True) if sold_el else ""

            if title and "Shop on eBay" not in title:
                listings.append({"title": title, "price": price, "sold": sold})

        time.sleep(random.uniform(1, 3))

    except Exception as e:
        print(f"  ⚠️  eBay scrape error: {e}")

    return listings

# ── OpenRouter Calls ─────────────────────────────────────────

def call_openrouter(system: str, user: str, model: str, max_tokens: int = 1500) -> str:
    """Call OpenRouter and return text response."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user}
        ]
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jscloud89/HIVE",
            "X-Title": "HIVE-Scout"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        print(f"❌ OpenRouter error: {e.code} {e.read().decode()}")
        sys.exit(1)

def analyze_patterns(listings: list, category: str, focus: str) -> str:
    """Use cheap model to spot patterns in raw listing data."""
    if not listings:
        return "No listing data available."

    listing_text = "\n".join(
        f"- {l.get('title','?')} | Price: {l.get('price','?')} | Reviews: {l.get('reviews','?')}"
        for l in listings[:30]
    )

    system = "You are a market research analyst. Be concise and data-focused."
    user = f"""Analyze these {category} listings in the '{focus}' category.
Identify:
1. What specific niches appear most frequently?
2. What price points cluster together?
3. Which products seem to have high review counts vs new entrants?
4. What gaps or underserved sub-niches do you spot?
5. Which 1-2 specific niches look most promising to investigate further?

RAW LISTINGS:
{listing_text}

Be specific. Give me niche names, not generalities."""

    print(f"  🧠 Pattern analysis via {MODEL_FLASH}...")
    return call_openrouter(system, user, MODEL_FLASH, max_tokens=600)

def synthesize_waggle(
    soul: str,
    task: dict,
    listings: list,
    pattern_analysis: str,
    category: str
) -> dict:
    """Use Sonnet to synthesize final waggle dance JSON."""

    listing_sample = "\n".join(
        f"- {l.get('title','?')} | {l.get('price','?')}"
        for l in listings[:20]
    )

    system = soul
    user = f"""You are Scout. You have completed a research run on this category:

CATEGORY: {category}
FOCUS: {task.get('focus', '')}
DATE: {now_slug()}

RAW LISTINGS SAMPLE ({len(listings)} total collected):
{listing_sample}

PATTERN ANALYSIS (from Gemini Flash):
{pattern_analysis}

Based on this data, identify the single most promising specific niche and produce
a complete waggle dance JSON report. Calculate a real vigor score showing your math.

Respond ONLY with valid JSON matching this exact structure — no preamble:
{{
  "scout_id": "scout-01",
  "timestamp": "{now_iso()}",
  "niche": "human readable niche name",
  "niche_slug": "kebab-case-slug",
  "direction": "etsy | ebay | cults3d",
  "market_signals": {{
    "avg_monthly_searches": 0,
    "top_competitor_revenue_est": "$0/mo",
    "avg_price_point": "$0.00",
    "review_velocity": "slow | moderate | fast",
    "competition_density": "low | medium | high | saturated"
  }},
  "trend": {{
    "velocity": "declining | stable | rising | spiking",
    "seasonal": false,
    "peak_window": null
  }},
  "filament_viability": {{
    "marble_white": false,
    "burnt_titanium": false,
    "matte_black": true
  }},
  "bird_safety": "CLEAR",
  "vigor": 0.0,
  "confidence_score": 0,
  "estimated_effort": "X days",
  "estimated_cost": "$0.00",
  "recommended_action": "deploy_worker | investigate_further | abandon",
  "scout_notes": "Paragraph including vigor math and models used"
}}"""

    print(f"  🧠 Waggle dance synthesis via {MODEL_SONNET}...")
    raw = call_openrouter(system, user, MODEL_SONNET, max_tokens=1200)

    # Strip markdown fences
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"❌ Sonnet returned invalid JSON:\n{raw[:500]}")
        sys.exit(1)

def save_waggle(waggle: dict) -> Path:
    """Save waggle dance JSON to data/waggle/."""
    WAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    slug = waggle.get("niche_slug", "unknown")
    filename = f"{now_slug()}-{slug}.json"
    path = WAGGLE_DIR / filename
    with open(path, "w") as f:
        json.dump(waggle, f, indent=2)
    return path

def write_memory(task: dict, waggle: dict):
    """Log research run to MEMORY.md."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n## {now_slug()}\n"
        f"- **Category:** {task.get('category')} — {task.get('focus')}\n"
        f"- **Niche discovered:** {waggle.get('niche', 'unknown')}\n"
        f"- **Vigor:** {waggle.get('vigor', '?')}\n"
        f"- **Confidence:** {waggle.get('confidence_score', '?')}\n"
        f"- **Action:** {waggle.get('recommended_action', '?')}\n"
    )
    with open(MEMORY_FILE, "a") as f:
        f.write(entry)

def mark_complete(queue: list, task: dict):
    """Mark task as researched in queue."""
    for t in queue:
        if t.get("slug") == task.get("slug"):
            t["status"] = "researched"
            t["last_run"] = now_slug()
    save_queue(queue)

def main():
    parser = argparse.ArgumentParser(description="Scout — Hive forager research agent")
    parser.add_argument("--category", help="Filter by category (Etsy/eBay/Cults3D)")
    parser.add_argument("--force-slug", help="Force a specific queue slug")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip API calls")
    args = parser.parse_args()

    load_env()

    SCOUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("\n🔍 SCOUT — Forager Research Agent")
    print("=" * 45)

    # Load soul
    soul = SOUL_FILE.read_text() if SOUL_FILE.exists() else ""

    # Pick task
    queue = load_queue()
    task  = pick_task(queue, args.category, args.force_slug)

    if not task:
        print("📭 No pending tasks in research queue.")
        print("Add tasks to ~/hive-phase1/data/research-queue.json")
        sys.exit(0)

    category = task.get("category", "Etsy")
    focus    = task.get("focus", "")

    print(f"📋 Task:     {category} — {focus}")
    print(f"🏷️  Slug:     {task.get('slug')}")
    print()

    # Scrape
    listings = []
    if category.lower() == "etsy":
        print("🌐 Scraping Etsy...")
        listings = scrape_etsy_trending(focus)
    elif category.lower() == "ebay":
        print("🌐 Scraping eBay...")
        listings = scrape_ebay_search(focus)
    else:
        print(f"⚠️  No scraper for category '{category}' — using API only")

    print(f"  📦 {len(listings)} listings collected")

    if args.dry_run:
        print("\n🔍 Dry run — skipping API synthesis")
        print("Sample listings:")
        for l in listings[:5]:
            print(f"  - {l.get('title','?')} | {l.get('price','?')}")
        sys.exit(0)

    # Analyze patterns with cheap model
    print("\n📊 Analyzing patterns...")
    pattern_analysis = analyze_patterns(listings, category, focus)
    print(f"  Pattern summary: {pattern_analysis[:200]}...")

    # Synthesize waggle dance with Sonnet
    print("\n💃 Synthesizing waggle dance...")
    waggle = synthesize_waggle(soul, task, listings, pattern_analysis, category)

    # Display result
    print("\n" + "=" * 45)
    print(f"🔍 NICHE:      {waggle.get('niche')}")
    print(f"📊 VIGOR:      {waggle.get('vigor')}")
    print(f"🎯 CONFIDENCE: {waggle.get('confidence_score')}")
    print(f"🐦 BIRD SAFE:  {waggle.get('bird_safety')}")
    print(f"✅ ACTION:     {waggle.get('recommended_action')}")
    print(f"📋 NOTES:      {waggle.get('scout_notes','')[:200]}...")
    print("=" * 45)

    # Save
    waggle_path = save_waggle(waggle)
    print(f"\n💾 Waggle saved to {waggle_path}")

    write_memory(task, waggle)
    print(f"📝 Logged to {MEMORY_FILE}")

    mark_complete(queue, task)
    print(f"✅ Task marked complete in queue")

    print(f"\n👑 Ready for Queen evaluation:")
    print(f"   python3 ~/HIVE/workspace-queen/queen.py --waggle {waggle_path}")
    print()

if __name__ == "__main__":
    main()
