#!/usr/bin/env python3
"""
listing_agent.py — HIVE Listing Agent
Autonomously creates optimized eBay and Etsy listings from product briefs.

Pipeline:
  Brief + Photos → Bard generates listing copy → Platform API creates listing
  → Telegram notification with listing URL

Usage:
  python3 listing_agent.py --brief "PSA graded card display stand, marble white PLA"
  python3 listing_agent.py --brief "..." --platform ebay
  python3 listing_agent.py --brief "..." --platform etsy
  python3 listing_agent.py --brief "..." --platform both
  python3 listing_agent.py --list    # show all listings
  python3 listing_agent.py --status  # show pending
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE     = Path(__file__).parent
PHASE1_DIR    = Path.home() / "hive-phase1"
DATA_DIR      = PHASE1_DIR / "data" / "listings"
MEMORY_FILE   = WORKSPACE / "MEMORY.md"
LISTINGS_FILE = WORKSPACE / "listings.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_BARD     = "anthropic/claude-sonnet-4-6"

# eBay condition IDs
EBAY_CONDITIONS = {
    "new":         1000,
    "like_new":    1500,
    "very_good":   2000,
    "good":        2500,
    "acceptable":  3000,
}

LISTING_SOUL = """You are Bard, the HIVE's expert listing copywriter.
You specialize in writing high-converting eBay and Etsy listings for 3D printed products.

Your listings must:
- Lead with the buyer's benefit, not the product feature
- Use natural keyword-rich language (not keyword stuffing)
- Include specific dimensions and compatibility info
- Have a clear call to action
- Feel premium and trustworthy
- Be optimized for search visibility

For 3D printed products always mention:
- Material (PLA, PETG, etc.)
- Color options available
- Print quality (layer height, wall count)
- Shipping speed
- Custom order availability

Output ONLY valid JSON. No markdown."""

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

def load_listings():
    if LISTINGS_FILE.exists():
        return json.loads(LISTINGS_FILE.read_text())
    return {}

def save_listing(slug, data):
    listings = load_listings()
    listings[slug] = data
    LISTINGS_FILE.write_text(json.dumps(listings, indent=2))

# ── Generate listing copy ────────────────────────────────
def generate_listing_copy(brief, platform="ebay"):
    print(f"  ✍️  Bard generating {platform} listing copy...")

    # Load catalog for context
    catalog_file = Path.home() / "HIVE/workspace-scout/catalog.json"
    catalog = {}
    if catalog_file.exists():
        catalog = json.loads(catalog_file.read_text())

    prompt = f"""Create a complete {platform.upper()} listing for this product:

PRODUCT BRIEF: {brief}

HIVE CATALOG CONTEXT:
- Printer: {catalog.get('printer', 'Bambu Lab A1 Mini')}
- Materials: {', '.join(catalog.get('filaments', ['Marble White PLA', 'Matte Black PLA']))}
- Shop: {catalog.get('shop', 'spiced_slabs')}
- Target margin: {catalog.get('target_margin', 0.30)*100:.0f}%

Platform: {platform.upper()}

Return a JSON object with these exact keys:
{{
  "title": "SEO-optimized title, max 80 chars for eBay / 140 for Etsy",
  "description": "Full listing description, 200-400 words, HTML formatted for eBay or plain text for Etsy",
  "price": 24.99,
  "category": "most relevant category name",
  "tags": ["tag1", "tag2", ...],
  "condition": "new",
  "shipping_note": "Ships within 1-2 business days",
  "variants": ["Marble White", "Matte Black", "Burnt Titanium"],
  "key_features": ["feature1", "feature2", "feature3", "feature4", "feature5"]
}}

For pricing: use Treasurer's GO price of $24.99 for standard items, adjust for size/complexity.
For eBay: use HTML in description. For Etsy: use plain text with line breaks.
Tags must be under 20 chars each for Etsy."""

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    body = json.dumps({
        "model": MODEL_BARD,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": LISTING_SOUL},
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
            "X-Title": "HIVE Listing Agent"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
            response = data["choices"][0]["message"]["content"].strip()
            clean = re.sub(r'```json|```', '', response).strip()
            return json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse error: {e}")
        print(f"  Response: {response[:200]}")
        return None
    except Exception as e:
        print(f"  ❌ Bard error: {e}")
        return None

# ── eBay listing ──────────────────────────────────────────
def create_ebay_draft(listing_data, brief):
    """
    Creates an eBay listing draft.
    Uses eBay Trading API if token available, otherwise saves as draft file.
    """
    ebay_token = os.environ.get("EBAY_USER_TOKEN", "")

    if not ebay_token:
        # Save as draft for manual posting
        slug = datetime.now().strftime("%Y%m%d-%H%M%S")
        draft_path = DATA_DIR / f"ebay-draft-{slug}.json"
        draft = {
            "platform": "ebay",
            "slug": slug,
            "brief": brief,
            "listing": listing_data,
            "status": "draft",
            "timestamp": now_iso(),
            "instructions": [
                "1. Go to ebay.com/sell",
                "2. Click 'Create listing'",
                "3. Use title: " + listing_data.get('title',''),
                "4. Set price: $" + str(listing_data.get('price', 24.99)),
                "5. Category: " + listing_data.get('category',''),
            ]
        }
        draft_path.write_text(json.dumps(draft, indent=2))
        print(f"  📄 eBay draft saved: {draft_path.name}")
        return {"status": "draft", "path": str(draft_path), "slug": slug}

    # TODO: Full eBay API integration when token is available
    print("  ⚠️  eBay API token not configured — saved as draft")
    return None

# ── Etsy listing ──────────────────────────────────────────
def create_etsy_draft(listing_data, brief):
    """
    Creates an Etsy listing draft.
    Uses Etsy API v3 if token available, otherwise saves as draft.
    """
    etsy_token = os.environ.get("ETSY_API_KEY", "")

    if not etsy_token:
        slug = datetime.now().strftime("%Y%m%d-%H%M%S")
        draft_path = DATA_DIR / f"etsy-draft-{slug}.json"
        draft = {
            "platform": "etsy",
            "slug": slug,
            "brief": brief,
            "listing": listing_data,
            "status": "draft",
            "timestamp": now_iso(),
        }
        draft_path.write_text(json.dumps(draft, indent=2))
        print(f"  📄 Etsy draft saved: {draft_path.name}")
        return {"status": "draft", "path": str(draft_path), "slug": slug}

    return None

# ── Format listing for display ───────────────────────────
def display_listing(listing_data, platform):
    print(f"\n  {'─'*50}")
    print(f"  📋 {platform.upper()} LISTING READY")
    print(f"  {'─'*50}")
    print(f"  Title:    {listing_data.get('title','')}")
    print(f"  Price:    ${listing_data.get('price', 0):.2f}")
    print(f"  Category: {listing_data.get('category','')}")
    print(f"  Tags:     {', '.join(listing_data.get('tags',[])[:5])}")
    print(f"\n  Key Features:")
    for f in listing_data.get('key_features', []):
        print(f"    • {f}")
    print(f"\n  Description preview:")
    desc = listing_data.get('description','')
    # Strip HTML for preview
    clean_desc = re.sub(r'<[^>]+>', '', desc)
    print(f"  {clean_desc[:300]}...")
    print(f"  {'─'*50}")

# ── Main pipeline ─────────────────────────────────────────
def run_pipeline(brief, platform="both"):
    slug = datetime.now().strftime("%Y%m%d-%H%M%S")

    print(f"\n{'='*55}")
    print(f"  📋 LISTING AGENT — {platform.upper()}")
    print(f"  Brief: {brief[:60]}")
    print(f"{'='*55}\n")

    results = {}

    platforms = ["ebay", "etsy"] if platform == "both" else [platform]

    for p in platforms:
        print(f"\n  Generating {p.upper()} listing...")
        listing_data = generate_listing_copy(brief, p)

        if not listing_data:
            print(f"  ❌ Failed to generate {p} listing")
            continue

        display_listing(listing_data, p)

        # Create listing/draft
        if p == "ebay":
            result = create_ebay_draft(listing_data, brief)
        else:
            result = create_etsy_draft(listing_data, brief)

        if result:
            results[p] = result

        # Save to listings record
        save_listing(f"{slug}-{p}", {
            "slug": f"{slug}-{p}",
            "brief": brief,
            "platform": p,
            "listing": listing_data,
            "result": result,
            "timestamp": now_iso(),
            "status": "draft"
        })

    # Telegram notification
    if results:
        lines = [f"📋 <b>Listing Agent Complete</b>", f"<i>{brief[:60]}</i>", ""]
        for p, r in results.items():
            lines.append(f"✅ <b>{p.upper()}</b> draft ready")
            if r.get("path"):
                lines.append(f"   File: <code>{Path(r['path']).name}</code>")

        lines += [
            "",
            "📝 To publish:",
            "• eBay: go to ebay.com/sell and use the draft",
            "• Etsy: go to etsy.com/sell and use the draft",
            "",
            f"Reply <code>listing-approve {slug}</code> to confirm published"
        ]
        send_telegram("\n".join(lines))

    update_memory(f"Listing generated: {brief[:50]} → {list(results.keys())}")
    print(f"\n✅ Listing Agent complete — {now_ct()}")
    return results

# ── List all listings ─────────────────────────────────────
def show_listings():
    listings = load_listings()
    if not listings:
        print("No listings yet.")
        return
    print(f"\n⬡ LISTINGS ({len(listings)} total)\n")
    for slug, l in sorted(listings.items(), reverse=True)[:20]:
        print(f"  {slug[:20]:<22} {l['platform']:<6} {l['status']:<10} {l.get('listing',{}).get('title','?')[:45]}")

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Listing Agent")
    parser.add_argument("--brief",    type=str, help="Product brief")
    parser.add_argument("--platform", type=str, default="both",
                        choices=["ebay","etsy","both"], help="Target platform")
    parser.add_argument("--list",     action="store_true", help="Show all listings")
    parser.add_argument("--status",   action="store_true", help="Show pending listings")
    args = parser.parse_args()

    load_env()

    if args.list or args.status:
        show_listings()
    elif args.brief:
        run_pipeline(args.brief, args.platform)
    else:
        parser.print_help()
