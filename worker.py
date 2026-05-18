#!/usr/bin/env python3
"""
worker.py — The Hive's Listing Creation Specialist
workspace-worker · Creates eBay listing drafts from Queen decrees
Usage: python3 worker.py --decree /path/to/decree.json [--dry-run]

A1 Mini Hardware Constraints (baked in):
- Build volume: 180x180x180mm
- Recommended filaments: PLA, PETG, TPU (no ABS/ASA — open frame)
- AMS Lite: up to 4 colors per print
- Nozzle: 0.4mm stainless (no CF/GF without hardened steel swap)
- Max speed: 500mm/s
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────
WORKSPACE    = Path(__file__).parent
HIVE_ROOT    = WORKSPACE.parent
PHASE1_DIR   = Path.home() / "hive-phase1"
DATA_DIR     = PHASE1_DIR / "data"
LISTINGS_DIR = DATA_DIR / "listings"
LOG_DIR      = DATA_DIR / "logs"
MEMORY_FILE  = WORKSPACE / "MEMORY.md"
SOUL_FILE    = WORKSPACE / "SOUL.md"

# ── Config ───────────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL          = "anthropic/claude-haiku-4-5"

# ── A1 Mini Hardware Profile ─────────────────────────────────
A1_MINI = {
    "build_volume_mm":      [180, 180, 180],
    "build_volume_inches":  [7.09, 7.09, 7.09],
    "max_colors":           4,
    "multi_color_system":   "AMS Lite",
    "recommended_filaments": ["PLA", "PETG", "TPU", "PVA"],
    "avoid_filaments":      ["ABS", "ASA", "PC", "Nylon"],
    "nozzle_diameter_mm":   0.4,
    "nozzle_type":          "stainless steel",
    "avoid_with_stainless": ["PLA-CF", "PETG-CF", "PA-CF"],
    "max_speed_mms":        500,
    "bird_safe_filaments":  ["PLA", "PETG", "TPU", "PVA"],
    "notes": (
        "Open frame — no enclosure. ABS/ASA not recommended. "
        "AMS Lite supports up to 4 color slots. "
        "Batch print to maximize plate utilization and $/hr."
    )
}

# ── Filament color catalog (update as stock changes) ─────────
FILAMENT_CATALOG = {
    "PLA": [
        "Matte Black", "Marble White", "Burnt Titanium",
        "Bambu Green", "Galaxy Gray", "Silk Gold"
    ],
    "PETG": ["Clear", "Black", "White"],
    "TPU": ["Black", "White"]
}

# ── eBay listing constraints ──────────────────────────────────
EBAY_CONSTRAINTS = {
    "title_max_chars":    80,
    "condition":          "New",
    "listing_type":       "Fixed Price",
    "duration":           "GTC",  # Good Till Cancelled
    "handling_time_days": 3,
    "return_policy":      "30 day returns accepted",
    "shipping":           "Calculated shipping or free shipping for items under $20",
    "payment":            "PayPal / eBay managed payments",
    "photos_required":    "Minimum 1 real product photo — no AI-only images",
    "disclosure":         "Add to description: '3D printed to order in our Tennessee workshop'"
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
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")

def load_decree(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"❌ Decree file not found: {path}")
        sys.exit(1)
    with open(p) as f:
        data = json.load(f)
    # Handle both direct decree and wrapped decree
    if "decree" in data and isinstance(data["decree"], dict):
        decree = data["decree"]
        waggle = data.get("waggle_input", {})
    else:
        decree = data
        waggle = {}
    return decree, waggle

def load_soul() -> str:
    if SOUL_FILE.exists():
        return SOUL_FILE.read_text()
    return "You are Worker, the Hive's listing creation specialist."

def call_haiku(system: str, user: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)

    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 3000,
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
            "X-Title": "HIVE-Worker"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        print(f"❌ Haiku error: {e.code} {e.read().decode()}")
        sys.exit(1)

def generate_listings(soul: str, decree: dict, waggle: dict) -> dict:
    """Generate multiple eBay listing variations with batch print plans."""

    niche         = waggle.get("niche") or decree.get("niche", "3D printed product")
    vigor         = waggle.get("vigor", 0)
    avg_price     = waggle.get("market_signals", {}).get("avg_price_point", "$15.00")
    filament_info = waggle.get("filament_viability", {})
    model_rec     = decree.get("model_recommendation", "haiku")
    spend_auth    = decree.get("spend_authorized", 0)

    # Build filament options based on viability flags
    color_options = ["Matte Black"]  # always available
    if filament_info.get("marble_white"):
        color_options.append("Marble White")
    if filament_info.get("burnt_titanium"):
        color_options.append("Burnt Titanium")
    color_options.extend(["Galaxy Gray", "Bambu Green"])
    color_options = color_options[:4]  # AMS Lite max 4

    user_prompt = f"""You are Worker. Queen has issued an APPROVED decree. Create eBay listing drafts.

QUEEN'S DECREE:
{json.dumps(decree, indent=2)}

NICHE INTELLIGENCE FROM SCOUT:
- Niche: {niche}
- Vigor score: {vigor}
- Market avg price: {avg_price}
- Spend authorized: ${spend_auth}

PRINTER CONSTRAINTS (Bambu Lab A1 Mini):
- Build volume: 180x180x180mm (7"x7"x7" max per item)
- AMS Lite: up to 4 colors available: {color_options}
- Recommended filaments: PLA, PETG, TPU only
- Bird safe: all recommended filaments are CLEAR
- Location: Tennessee workshop

EBAY RULES:
- Title: 80 characters MAX
- Condition: New
- Listing type: Fixed Price, Good Till Cancelled
- Handling time: 3 business days
- Must include: "3D printed to order in our Tennessee workshop"
- NO AI-only images — real product photos required before posting

BATCH OPTIMIZATION REQUIREMENT:
Calculate how many units fit on the 180x180mm build plate at once.
More units per plate = lower cost per unit = better margin.
Include batch_plan in every variation.

Create exactly 5 listing variations for this niche:
1. Standard single color (Matte Black) — entry price point
2. Premium color (Marble White if viable, else Galaxy Gray) — +15-20% price
3. Multi-color accent version (2 colors via AMS Lite) — mid-premium
4. Bundle/value pack (2-3 units) — volume play
5. Custom/personalized version — highest price point

For each variation produce:
{{
  "variation_id": "v1",
  "variation_name": "short name",
  "ebay_title": "max 80 chars — keyword rich",
  "price_usd": 0.00,
  "filament": "material and color",
  "colors_used": 1,
  "estimated_print_time_hours": 0.0,
  "estimated_filament_grams": 0,
  "estimated_filament_cost_usd": 0.00,
  "units_per_plate": 0,
  "batch_plan": "X units per plate, Y plates for Z total units",
  "machine_hours_per_unit": 0.0,
  "revenue_per_machine_hour": 0.00,
  "description_html": "<p>Full eBay description HTML here</p>",
  "item_specifics": {{
    "Material": "PLA",
    "Color": "Matte Black",
    "Brand": "Handcrafted",
    "Country of Manufacture": "United States",
    "Type": "specific product type"
  }},
  "search_keywords": ["keyword1", "keyword2"],
  "notes_for_joshua": "What to print, photograph, and check before posting"
}}

Return a JSON object with this structure — no preamble, no markdown fences:
{{
  "niche": "{niche}",
  "generated_at": "{now_iso()}",
  "printer": "Bambu Lab A1 Mini",
  "ams_lite": true,
  "color_options": {json.dumps(color_options)},
  "variations": [5 variation objects],
  "recommended_first_listing": "v1 or v2 etc — which to post first and why",
  "total_revenue_potential": 0.00,
  "notes": "Any important Worker notes"
}}"""

    raw = call_haiku(soul, user_prompt)

    # Strip markdown fences
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])

    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        print(f"❌ Haiku returned invalid JSON:\n{raw[:500]}")
        sys.exit(1)

def save_listings(listings: dict, niche: str) -> Path:
    LISTINGS_DIR.mkdir(parents=True, exist_ok=True)
    slug     = niche.lower().replace(" ", "-")[:40]
    filename = f"listings-{slug}-{now_slug()}.json"
    path     = LISTINGS_DIR / filename
    with open(path, "w") as f:
        json.dump(listings, f, indent=2)
    return path

def print_summary(listings: dict):
    """Print a readable summary of all listing variations."""
    print(f"\n📦 NICHE: {listings.get('niche')}")
    print(f"🖨️  PRINTER: {listings.get('printer')} + AMS Lite")
    print(f"🎨 COLORS: {', '.join(listings.get('color_options', []))}")
    print()

    variations = listings.get("variations", [])
    for v in variations:
        print(f"  [{v.get('variation_id')}] {v.get('variation_name')}")
        print(f"       Title:    {v.get('ebay_title')}")
        print(f"       Price:    ${v.get('price_usd', 0):.2f}")
        print(f"       Filament: {v.get('filament')}")
        print(f"       Batch:    {v.get('batch_plan')}")
        print(f"       $/hr:     ${v.get('revenue_per_machine_hour', 0):.2f}")
        print(f"       📋 Note:  {v.get('notes_for_joshua', '')[:80]}")
        print()

    print(f"⭐ RECOMMENDED FIRST: {listings.get('recommended_first_listing')}")
    print(f"💰 TOTAL REVENUE POTENTIAL: ${listings.get('total_revenue_potential', 0):.2f}")

def write_memory(decree: dict, listings: dict, path: Path):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    variations = listings.get("variations", [])
    entry = (
        f"\n## {now_slug()}\n"
        f"- **Niche:** {listings.get('niche')}\n"
        f"- **Decree:** {decree.get('decree', '?').upper()}\n"
        f"- **Variations created:** {len(variations)}\n"
        f"- **Revenue potential:** ${listings.get('total_revenue_potential', 0):.2f}\n"
        f"- **File:** {path.name}\n"
        f"- **Status:** DRAFT — awaiting Joshua review and product photos\n"
    )
    with open(MEMORY_FILE, "a") as f:
        f.write(entry)

def main():
    parser = argparse.ArgumentParser(description="Worker — Hive listing creation specialist")
    parser.add_argument("--decree", required=True, help="Path to Queen's decree JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Load decree and validate, no API call")
    args = parser.parse_args()

    load_env()
    LISTINGS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("\n🏭 WORKER — Listing Creation Specialist")
    print("=" * 45)
    print(f"🖨️  Printer: Bambu Lab A1 Mini")
    print(f"📐 Build volume: 180×180×180mm")
    print(f"🎨 AMS Lite: up to 4 colors")

    soul           = load_soul()
    decree, waggle = load_decree(args.decree)

    niche = waggle.get("niche") or decree.get("niche", "unknown")
    print(f"\n📋 Decree: {decree.get('decree', '?').upper()}")
    print(f"🔍 Niche:  {niche}")
    print(f"💰 Spend authorized: ${decree.get('spend_authorized', 0):.2f}")
    print(f"🤖 Model rec: {decree.get('model_recommendation', '?')}")

    if decree.get("decree", "").lower() != "approved":
        print(f"\n⛔ Decree is not APPROVED — Worker stands down")
        sys.exit(0)

    if args.dry_run:
        print("\n✅ Dry run — decree validated, no API call made")
        sys.exit(0)

    print(f"\n⚙️  Generating 5 listing variations via Haiku...")
    listings = generate_listings(soul, decree, waggle)

    print_summary(listings)

    path = save_listings(listings, niche)
    print(f"\n💾 Listings saved: {path}")

    write_memory(decree, listings, path)
    print(f"📝 Logged to {MEMORY_FILE}")

    print(f"\n⚠️  NEXT STEPS FOR JOSHUA:")
    rec = listings.get("recommended_first_listing", "v1")
    variations = {v["variation_id"]: v for v in listings.get("variations", [])}
    first = variations.get(rec, listings.get("variations", [{}])[0])
    print(f"   1. Print: {first.get('notes_for_joshua', '')}")
    print(f"   2. Photograph the real printed product")
    print(f"   3. Review listing draft at: {path}")
    print(f"   4. Approve and post to eBay spiced_slabs")
    print()

if __name__ == "__main__":
    main()
