#!/usr/bin/env python3
"""
market_scout.py — HIVE Market Scout Agent
Daily competitor intelligence for the card display/collector niche.
Scrapes eBay and Etsy for pricing, features, listing volume.
Feeds data to Queen and Treasurer for strategic decisions.

Schedule: Run daily at 8am CT (13:00 UTC)
  0 13 * * * cd /home/beekeeper/HIVE/workspace-scout && python3 market_scout.py

Usage:
  python3 market_scout.py              # full daily scan
  python3 market_scout.py --niche "psa card stand"
  python3 market_scout.py --report     # show last report
  python3 market_scout.py --silent     # no Telegram
"""

import argparse
import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE   = Path(__file__).parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data" / "market-scout"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
REPORT_FILE = DATA_DIR / "last_report.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL          = "google/gemini-2.5-flash-lite"

# Primary niches to track daily
NICHES = [
    {
        "id": "psa-card-stand",
        "name": "PSA Graded Card Stand",
        "ebay_keywords": "PSA card stand 3D printed graded card display",
        "etsy_keywords": "psa card stand graded card display",
        "our_price": 4.99,
        "target_category": "Card Toploaders & Holders"
    },
    {
        "id": "card-slab-holder",
        "name": "Card Slab Display Holder",
        "ebay_keywords": "graded card slab holder display stand BGS CGC",
        "etsy_keywords": "graded card holder slab display stand",
        "our_price": 12.99,
        "target_category": "Card Toploaders & Holders"
    },
    {
        "id": "pokemon-card-display",
        "name": "Pokemon Card Display Stand",
        "ebay_keywords": "pokemon card display stand 3D printed holder",
        "etsy_keywords": "pokemon card stand display holder",
        "our_price": 9.99,
        "target_category": "Pokemon Card Supplies"
    },
]

SCOUT_SOUL = """You are the HIVE Market Scout. Analyze competitor listing data and extract intelligence.
Be specific, data-driven, and actionable. Focus on:
- Price positioning opportunities
- Feature gaps we can fill
- Listing quality compared to ours
- Volume/demand signals
Keep analysis under 150 words. Output JSON only."""

# ── Helpers ──────────────────────────────────────────────
def load_env():
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def now_ct():
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M CT")

def send_telegram(text):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  ⚠️  Telegram: {e}")

def update_memory(event):
    ts = now_ct()
    line = f"## {ts} — {event}\n"
    existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    MEMORY_FILE.write_text(line + existing)

# ── eBay scraping via RSS ────────────────────────────────
def scrape_ebay(keywords, max_results=20):
    """Scrape eBay completed listings via RSS feed."""
    encoded = urllib.parse.quote(keywords)
    url = f"https://www.ebay.com/sch/i.html?_nkw={encoded}&_sop=15&rt=nc&LH_Sold=1&LH_Complete=1"

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })

    listings = []
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="ignore")

        # Extract listing data with regex
        titles  = re.findall(r'class="s-item__title[^"]*"[^>]*><span[^>]*>(.*?)</span>', html)
        prices  = re.findall(r'class="s-item__price"[^>]*>([\$£€][\d,\.]+)', html)
        sold    = re.findall(r'(\d+)\s+sold', html, re.IGNORECASE)

        for i, (title, price) in enumerate(zip(titles[:max_results], prices[:max_results])):
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            if clean_title and "Shop on eBay" not in clean_title:
                try:
                    price_val = float(price.replace('$','').replace(',',''))
                except:
                    price_val = 0
                listings.append({
                    "title": clean_title[:100],
                    "price": price_val,
                    "platform": "ebay"
                })

        print(f"  ✓ eBay: found {len(listings)} listings")

    except Exception as e:
        print(f"  ⚠️  eBay scrape error: {e}")

    return listings

# ── Etsy scraping ────────────────────────────────────────
def scrape_etsy(keywords, max_results=20):
    """Scrape Etsy search results."""
    encoded = urllib.parse.quote(keywords)
    url = f"https://www.etsy.com/search?q={encoded}&order=most_relevant"

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    })

    listings = []
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="ignore")

        # Extract from JSON-LD structured data
        json_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        for match in json_matches[:20]:
            try:
                data = json.loads(match)
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            title = item.get("name", "")
                            offers = item.get("offers", {})
                            price = float(offers.get("price", 0)) if offers else 0
                            if title and price > 0:
                                listings.append({
                                    "title": title[:100],
                                    "price": price,
                                    "platform": "etsy"
                                })
                elif data.get("@type") == "Product":
                    title = data.get("name", "")
                    offers = data.get("offers", {})
                    price = float(offers.get("price", 0)) if offers else 0
                    if title and price > 0:
                        listings.append({
                            "title": title[:100],
                            "price": price,
                            "platform": "etsy"
                        })
            except:
                continue

        # Fallback: regex price extraction
        if not listings:
            prices = re.findall(r'"price":"(\d+\.?\d*)"', html)
            titles = re.findall(r'"name":"([^"]{10,100})"', html)
            for title, price in zip(titles[:max_results], prices[:max_results]):
                try:
                    listings.append({
                        "title": title,
                        "price": float(price),
                        "platform": "etsy"
                    })
                except:
                    continue

        print(f"  ✓ Etsy: found {len(listings)} listings")

    except Exception as e:
        print(f"  ⚠️  Etsy scrape error: {e}")

    return listings

# ── Analyze with Claude ───────────────────────────────────
def analyze_competition(niche, ebay_listings, etsy_listings):
    """Use Claude to analyze competitor data."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return None

    # Build analysis prompt
    ebay_summary = "\n".join([
        f"  ${l['price']:.2f} — {l['title'][:60]}"
        for l in sorted(ebay_listings, key=lambda x: x['price'])[:10]
    ]) or "  No data"

    etsy_summary = "\n".join([
        f"  ${l['price']:.2f} — {l['title'][:60]}"
        for l in sorted(etsy_listings, key=lambda x: x['price'])[:10]
    ]) or "  No data"

    ebay_prices = [l['price'] for l in ebay_listings if l['price'] > 0]
    etsy_prices = [l['price'] for l in etsy_listings if l['price'] > 0]

    prompt = f"""Analyze this market data for "{niche['name']}":

OUR PRICE: ${niche['our_price']}

EBAY COMPETITORS ({len(ebay_listings)} found):
{ebay_summary}

ETSY COMPETITORS ({len(etsy_listings)} found):
{etsy_summary}

STATS:
- eBay price range: ${min(ebay_prices, default=0):.2f} - ${max(ebay_prices, default=0):.2f}
- eBay avg: ${sum(ebay_prices)/len(ebay_prices):.2f if ebay_prices else 0:.2f}
- Etsy price range: ${min(etsy_prices, default=0):.2f} - ${max(etsy_prices, default=0):.2f}
- Etsy avg: ${sum(etsy_prices)/len(etsy_prices):.2f if etsy_prices else 0:.2f}

Return JSON with:
{{
  "opportunity": "high|medium|low",
  "recommended_price": 0.00,
  "price_gap": "description of pricing opportunity",
  "competition_level": "low|medium|high|saturated",
  "key_insight": "one actionable insight",
  "listing_volume": "sparse|moderate|busy",
  "our_positioning": "description of how we should position"
}}"""

    body = json.dumps({
        "model": MODEL,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": SCOUT_SOUL},
            {"role": "user",   "content": prompt}
        ]
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://hive.local",
            "X-Title": "HIVE Market Scout"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
            response = data["choices"][0]["message"]["content"].strip()
            clean = re.sub(r'```json|```', '', response).strip()
            return json.loads(clean)
    except Exception as e:
        print(f"  ⚠️  Analysis error: {e}")
        return None

# ── Main scan ─────────────────────────────────────────────
def run_scan(target_niche=None, silent=False):
    print(f"\n{'='*55}")
    print(f"  🔍 MARKET SCOUT — Competitor Intelligence")
    print(f"  {now_ct()}")
    print(f"{'='*55}\n")

    niches_to_scan = NICHES
    if target_niche:
        niches_to_scan = [n for n in NICHES if target_niche.lower() in n['name'].lower()]
        if not niches_to_scan:
            # Add as custom niche
            niches_to_scan = [{
                "id": "custom",
                "name": target_niche,
                "ebay_keywords": target_niche,
                "etsy_keywords": target_niche,
                "our_price": 9.99,
                "target_category": "General"
            }]

    full_report = {
        "timestamp": now_iso(),
        "niches": {}
    }

    tg_lines = [
        f"🔍 <b>Market Scout Report</b>",
        f"<i>{now_ct()}</i>",
        ""
    ]

    for niche in niches_to_scan:
        print(f"\n  Scanning: {niche['name']}")
        print(f"  {'─'*45}")

        # Scrape both platforms
        ebay_listings = scrape_ebay(niche['ebay_keywords'])
        time.sleep(2)
        etsy_listings = scrape_etsy(niche['etsy_keywords'])
        time.sleep(1)

        # Calculate basic stats
        ebay_prices = [l['price'] for l in ebay_listings if l['price'] > 0]
        etsy_prices = [l['price'] for l in etsy_listings if l['price'] > 0]

        ebay_avg = sum(ebay_prices)/len(ebay_prices) if ebay_prices else 0
        etsy_avg = sum(etsy_prices)/len(etsy_prices) if etsy_prices else 0

        print(f"  eBay: {len(ebay_listings)} listings, avg ${ebay_avg:.2f}")
        print(f"  Etsy: {len(etsy_listings)} listings, avg ${etsy_avg:.2f}")
        print(f"  Our price: ${niche['our_price']}")

        # AI analysis
        analysis = analyze_competition(niche, ebay_listings, etsy_listings)

        if analysis:
            print(f"  Opportunity: {analysis.get('opportunity','?').upper()}")
            print(f"  Recommended price: ${analysis.get('recommended_price',0):.2f}")
            print(f"  Insight: {analysis.get('key_insight','?')}")

        # Store in report
        full_report["niches"][niche["id"]] = {
            "name": niche["name"],
            "our_price": niche["our_price"],
            "ebay_count": len(ebay_listings),
            "etsy_count": len(etsy_listings),
            "ebay_avg_price": round(ebay_avg, 2),
            "etsy_avg_price": round(etsy_avg, 2),
            "ebay_min": min(ebay_prices, default=0),
            "ebay_max": max(ebay_prices, default=0),
            "analysis": analysis,
            "top_ebay": ebay_listings[:5],
            "top_etsy": etsy_listings[:5],
        }

        # Build Telegram section
        opp_emoji = {"high": "🔥", "medium": "📊", "low": "📉"}.get(
            analysis.get("opportunity","medium") if analysis else "medium", "📊"
        )
        tg_lines.append(f"{opp_emoji} <b>{niche['name']}</b>")
        tg_lines.append(f"  eBay: {len(ebay_listings)} listings @ avg ${ebay_avg:.2f}")
        tg_lines.append(f"  Etsy: {len(etsy_listings)} listings @ avg ${etsy_avg:.2f}")
        tg_lines.append(f"  Our price: ${niche['our_price']}")
        if analysis:
            tg_lines.append(f"  💡 {analysis.get('key_insight','')}")
            rec = analysis.get('recommended_price', 0)
            if rec and rec != niche['our_price']:
                diff = rec - niche['our_price']
                tg_lines.append(f"  {'📈' if diff > 0 else '📉'} Recommended: ${rec:.2f} ({'+' if diff>0 else ''}{diff:.2f})")
        tg_lines.append("")

    # Save report
    REPORT_FILE.write_text(json.dumps(full_report, indent=2))
    print(f"\n  💾 Report saved: {REPORT_FILE}")

    # Send Telegram
    if not silent:
        send_telegram("\n".join(tg_lines))
        print(f"  📱 Report sent to Telegram")

    update_memory(f"Market scout complete — {len(niches_to_scan)} niches scanned")
    print(f"\n✅ Market Scout complete — {now_ct()}")
    return full_report

def show_report():
    if not REPORT_FILE.exists():
        print("No report yet. Run market_scout.py first.")
        return
    report = json.loads(REPORT_FILE.read_text())
    print(f"\nLast scan: {report['timestamp']}")
    for nid, niche in report.get("niches", {}).items():
        print(f"\n{niche['name']}:")
        print(f"  eBay: {niche['ebay_count']} listings @ avg ${niche['ebay_avg_price']:.2f}")
        print(f"  Etsy: {niche['etsy_count']} listings @ avg ${niche['etsy_avg_price']:.2f}")
        if niche.get("analysis"):
            print(f"  Opportunity: {niche['analysis'].get('opportunity','?')}")
            print(f"  Insight: {niche['analysis'].get('key_insight','?')}")

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Market Scout")
    parser.add_argument("--niche",  type=str, help="Specific niche to scan")
    parser.add_argument("--report", action="store_true", help="Show last report")
    parser.add_argument("--silent", action="store_true", help="No Telegram")
    args = parser.parse_args()

    load_env()

    if args.report:
        show_report()
    else:
        run_scan(target_niche=args.niche, silent=args.silent)
