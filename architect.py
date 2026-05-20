#!/usr/bin/env python3
"""
architect.py — HIVE Architect Agent
Builds Notion templates autonomously and publishes to Gumroad.

Pipeline:
  Decree → Architect designs template → Notion API creates it
  → Shareable link → Worker creates Gumroad listing → Hermes notifies

Usage:
  python3 architect.py --brief "PSA BGS CGC graded card collection tracker"
  python3 architect.py --list    # list all created templates
  python3 architect.py --status  # show pending templates
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE   = Path(__file__).parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
TEMPLATES_FILE = WORKSPACE / "templates.json"

(DATA_DIR / "architect").mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
NOTION_URL     = "https://api.notion.com/v1"
GUMROAD_URL    = "https://api.gumroad.com/v2"
NOTION_VERSION = "2022-06-28"
MODEL          = "anthropic/claude-sonnet-4-6"

ARCHITECT_SOUL = """You are Architect, the HIVE's Notion template designer.
You create genuinely useful, well-structured Notion templates for niche audiences.

Your templates must:
- Solve a real pain point for the target audience
- Have clean, intuitive database structures
- Include useful formulas and relations
- Be visually organized with icons and descriptions
- Feel premium and worth paying for

When designing a Notion template, output a JSON structure describing:
- Pages to create
- Databases with their properties
- Sample data to pre-populate
- How pages relate to each other

Output ONLY valid JSON. No markdown, no explanation."""

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def now_ct():
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M CT")

# ── Env ──────────────────────────────────────────────────
def load_env():
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

# ── OpenRouter ───────────────────────────────────────────
def call_claude(system, user, max_tokens=4000):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user}
        ]
    }).encode()
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://hive.local",
            "X-Title": "HIVE Architect"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ Claude error: {e}")
        return None

# ── Notion API ───────────────────────────────────────────
def notion_request(method, endpoint, data=None):
    key = os.environ.get("NOTION_API_KEY", "")
    req = urllib.request.Request(
        f"{NOTION_URL}{endpoint}",
        data=json.dumps(data).encode() if data else None,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION
        },
        method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ❌ Notion HTTP {e.code}: {err[:300]}")
        return None
    except Exception as e:
        print(f"  ❌ Notion error: {e}")
        return None

def get_notion_workspace():
    """Get the first available page to use as parent."""
    result = notion_request("POST", "/search", {
        "filter": {"value": "page", "property": "object"},
        "page_size": 1
    })
    if result and result.get("results"):
        return result["results"][0]["id"]
    return None

def create_notion_page(parent_id, title, icon="📋", is_database_parent=False):
    """Create a basic Notion page."""
    data = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "icon": {"type": "emoji", "emoji": icon},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": []
    }
    return notion_request("POST", "/pages", data)

def create_notion_database(parent_id, title, icon, properties):
    """Create a Notion database with given properties."""
    data = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "icon": {"type": "emoji", "emoji": icon},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties
    }
    return notion_request("POST", "/databases", data)

def add_database_row(database_id, properties):
    """Add a row to a database."""
    data = {
        "parent": {"database_id": database_id},
        "properties": properties
    }
    return notion_request("POST", "/pages", data)

def update_page_content(page_id, blocks):
    """Add content blocks to a page."""
    data = {"children": blocks}
    return notion_request("PATCH", f"/blocks/{page_id}/children", data)

# ── Template designs ─────────────────────────────────────
def design_slab_vault_tracker():
    """
    PSA/BGS/CGC Slab Vault Tracker
    Pre-designed for speed and quality.
    """
    return {
        "name": "Slab Vault Tracker",
        "emoji": "🏆",
        "description": "Premium collection tracker for PSA, BGS, CGC, SGC & TAG graded cards",
        "databases": [
            {
                "name": "🃏 Slab Inventory",
                "emoji": "🃏",
                "description": "Your complete graded card collection",
                "properties": {
                    "Card Name": {"title": {}},
                    "Set": {"rich_text": {}},
                    "Year": {"number": {"format": "number"}},
                    "Sport / Game": {
                        "select": {
                            "options": [
                                {"name": "Pokémon",    "color": "yellow"},
                                {"name": "Basketball", "color": "orange"},
                                {"name": "Baseball",   "color": "blue"},
                                {"name": "Football",   "color": "brown"},
                                {"name": "Soccer",     "color": "green"},
                                {"name": "Other",      "color": "gray"},
                            ]
                        }
                    },
                    "Grading Co.": {
                        "select": {
                            "options": [
                                {"name": "PSA",  "color": "red"},
                                {"name": "BGS",  "color": "blue"},
                                {"name": "CGC",  "color": "yellow"},
                                {"name": "SGC",  "color": "orange"},
                                {"name": "TAG",  "color": "purple"},
                                {"name": "RAW",  "color": "gray"},
                            ]
                        }
                    },
                    "Grade": {
                        "select": {
                            "options": [
                                {"name": "10",   "color": "yellow"},
                                {"name": "9.5",  "color": "green"},
                                {"name": "9",    "color": "blue"},
                                {"name": "8.5",  "color": "purple"},
                                {"name": "8",    "color": "pink"},
                                {"name": "7",    "color": "orange"},
                                {"name": "Auth", "color": "gray"},
                            ]
                        }
                    },
                    "Cert #": {"rich_text": {}},
                    "Buy Price": {"number": {"format": "dollar"}},
                    "Current Value": {"number": {"format": "dollar"}},
                    "ROI %": {
                        "formula": {
                            "expression": "if(prop(\"Buy Price\") > 0, round(((prop(\"Current Value\") - prop(\"Buy Price\")) / prop(\"Buy Price\")) * 100), 0)"
                        }
                    },
                    "Pop Report": {"number": {"format": "number"}},
                    "Status": {
                        "select": {
                            "options": [
                                {"name": "Own",       "color": "green"},
                                {"name": "Sold",      "color": "red"},
                                {"name": "Submitted", "color": "yellow"},
                                {"name": "Wishlist",  "color": "purple"},
                            ]
                        }
                    },
                    "Photo": {"files": {}},
                    "Notes": {"rich_text": {}},
                    "Date Added": {"date": {}},
                }
            },
            {
                "name": "📦 Grading Submissions",
                "emoji": "📦",
                "description": "Track cards sent for grading",
                "properties": {
                    "Card Name": {"title": {}},
                    "Grading Co.": {
                        "select": {
                            "options": [
                                {"name": "PSA", "color": "red"},
                                {"name": "BGS", "color": "blue"},
                                {"name": "CGC", "color": "yellow"},
                                {"name": "SGC", "color": "orange"},
                                {"name": "TAG", "color": "purple"},
                            ]
                        }
                    },
                    "Service Level": {
                        "select": {
                            "options": [
                                {"name": "Economy",       "color": "gray"},
                                {"name": "Regular",       "color": "blue"},
                                {"name": "Express",       "color": "orange"},
                                {"name": "Super Express", "color": "red"},
                                {"name": "Walkthrough",   "color": "purple"},
                            ]
                        }
                    },
                    "Submission #": {"rich_text": {}},
                    "Cards in Batch": {"number": {"format": "number"}},
                    "Cost": {"number": {"format": "dollar"}},
                    "Submitted Date": {"date": {}},
                    "Est. Return": {"date": {}},
                    "Actual Return": {"date": {}},
                    "Tracking #": {"rich_text": {}},
                    "Status": {
                        "select": {
                            "options": [
                                {"name": "Preparing",  "color": "gray"},
                                {"name": "Shipped",    "color": "blue"},
                                {"name": "Received",   "color": "yellow"},
                                {"name": "Grading",    "color": "orange"},
                                {"name": "QC",         "color": "purple"},
                                {"name": "Complete",   "color": "green"},
                                {"name": "Returned",   "color": "pink"},
                            ]
                        }
                    },
                    "Notes": {"rich_text": {}},
                }
            },
            {
                "name": "💰 Sales Log",
                "emoji": "💰",
                "description": "Track every card you've sold",
                "properties": {
                    "Card Name": {"title": {}},
                    "Platform": {
                        "select": {
                            "options": [
                                {"name": "eBay",      "color": "blue"},
                                {"name": "Etsy",      "color": "orange"},
                                {"name": "TCGPlayer", "color": "purple"},
                                {"name": "PWCC",      "color": "gray"},
                                {"name": "Local",     "color": "green"},
                                {"name": "Other",     "color": "pink"},
                            ]
                        }
                    },
                    "Sale Price": {"number": {"format": "dollar"}},
                    "Fees": {"number": {"format": "dollar"}},
                    "Net Proceeds": {
                        "formula": {
                            "expression": "prop(\"Sale Price\") - prop(\"Fees\")"
                        }
                    },
                    "Buy Price": {"number": {"format": "dollar"}},
                    "Profit": {
                        "formula": {
                            "expression": "prop(\"Net Proceeds\") - prop(\"Buy Price\")"
                        }
                    },
                    "Sale Date": {"date": {}},
                    "Buyer Feedback": {
                        "select": {
                            "options": [
                                {"name": "Positive", "color": "green"},
                                {"name": "Neutral",  "color": "yellow"},
                                {"name": "Negative", "color": "red"},
                            ]
                        }
                    },
                    "Notes": {"rich_text": {}},
                }
            },
            {
                "name": "🎯 Wishlist",
                "emoji": "🎯",
                "description": "Cards you want to acquire",
                "properties": {
                    "Card Name": {"title": {}},
                    "Set": {"rich_text": {}},
                    "Target Grade": {
                        "select": {
                            "options": [
                                {"name": "PSA 10", "color": "yellow"},
                                {"name": "PSA 9",  "color": "blue"},
                                {"name": "BGS 9.5","color": "green"},
                                {"name": "CGC 10", "color": "orange"},
                                {"name": "Any",    "color": "gray"},
                            ]
                        }
                    },
                    "Max Budget": {"number": {"format": "dollar"}},
                    "Current Market": {"number": {"format": "dollar"}},
                    "Priority": {
                        "select": {
                            "options": [
                                {"name": "🔥 High",   "color": "red"},
                                {"name": "📌 Medium", "color": "yellow"},
                                {"name": "💭 Low",    "color": "gray"},
                            ]
                        }
                    },
                    "Notes": {"rich_text": {}},
                }
            }
        ],
        "sample_data": {
            "🃏 Slab Inventory": [
                {
                    "Card Name": "Charizard Base Set",
                    "Set": "Base Set",
                    "Year": 1999,
                    "Sport / Game": "Pokémon",
                    "Grading Co.": "PSA",
                    "Grade": "9",
                    "Buy Price": 450.00,
                    "Current Value": 680.00,
                    "Status": "Own",
                },
                {
                    "Card Name": "LeBron James Rookie",
                    "Set": "Topps Chrome",
                    "Year": 2003,
                    "Sport / Game": "Basketball",
                    "Grading Co.": "BGS",
                    "Grade": "9.5",
                    "Buy Price": 890.00,
                    "Current Value": 1200.00,
                    "Status": "Own",
                }
            ]
        }
    }

# ── Build template in Notion ─────────────────────────────
def build_notion_template(design):
    print(f"\n  📐 Building Notion template: {design['name']}")

    # Find workspace root
    workspace_id = get_notion_workspace()
    if not workspace_id:
        print("  ❌ Could not find Notion workspace. Make sure Architect integration has access to at least one page.")
        return None

    # Create root page
    print(f"  → Creating root page...")
    root = create_notion_page(
        workspace_id,
        f"{design['emoji']} {design['name']}",
        design['emoji']
    )
    if not root:
        return None
    root_id = root["id"]
    print(f"  ✓ Root page: {root_id}")

    # Add welcome content
    welcome_blocks = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": f"Welcome to your {design['name']}! Track your entire graded card collection in one place."}}],
                "icon": {"type": "emoji", "emoji": "👑"},
                "color": "yellow_background"
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "📊 Quick Stats"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "Use the databases below to track your collection, submissions, sales, and wishlist."}}]
            }
        },
        {
            "object": "block",
            "type": "divider",
            "divider": {}
        }
    ]
    update_page_content(root_id, welcome_blocks)

    # Create each database
    db_ids = {}
    for db_design in design["databases"]:
        print(f"  → Creating database: {db_design['name']}...")
        db = create_notion_database(
            root_id,
            db_design["name"],
            db_design["emoji"],
            db_design["properties"]
        )
        if db:
            db_ids[db_design["name"]] = db["id"]
            print(f"  ✓ Database created: {db_design['name']}")
            time.sleep(0.5)  # Rate limit

            # Add sample data
            sample_key = db_design["name"]
            if sample_key in design.get("sample_data", {}):
                for row in design["sample_data"][sample_key]:
                    props = {}
                    for k, v in row.items():
                        if k == "Card Name":
                            props["Card Name"] = {"title": [{"type": "text", "text": {"content": str(v)}}]}
                        elif k in ("Set", "Cert #", "Notes", "Tracking #", "Submission #"):
                            props[k] = {"rich_text": [{"type": "text", "text": {"content": str(v)}}]}
                        elif k in ("Buy Price", "Current Value", "Year", "Pop Report",
                                   "Cards in Batch", "Cost", "Sale Price", "Fees", "Max Budget", "Current Market"):
                            props[k] = {"number": float(v) if isinstance(v, (int, float)) else 0}
                        elif k in ("Grading Co.", "Grade", "Status", "Sport / Game",
                                   "Service Level", "Platform", "Buyer Feedback",
                                   "Target Grade", "Priority"):
                            props[k] = {"select": {"name": str(v)}}
                    if props:
                        add_database_row(db["id"], props)
                        time.sleep(0.3)
        else:
            print(f"  ⚠️  Failed to create: {db_design['name']}")

    return root_id, db_ids

# ── Get shareable link ───────────────────────────────────
def get_page_url(page_id):
    clean_id = page_id.replace("-", "")
    return f"https://www.notion.so/{clean_id}"

# ── Create Gumroad listing ───────────────────────────────
def create_gumroad_listing(name, description, price_cents, notion_url):
    key = os.environ.get("GUMROAD_API_KEY", "")

    full_description = f"""{description}

---

🏆 WHAT'S INCLUDED:
• Complete Notion template with 4 databases
• Slab Inventory tracker with ROI calculator
• Grading Submission tracker
• Sales Log with profit tracking
• Wishlist with budget tracking
• Pre-populated with sample data
• Lifetime access + free updates

📋 HOW TO USE:
1. Purchase and receive the Notion template link
2. Click "Duplicate" in the top right corner
3. Add to your Notion workspace
4. Start tracking your collection immediately

✅ COMPATIBLE WITH:
PSA • BGS • CGC • SGC • TAG slabs
Pokémon • Basketball • Baseball • Football • Soccer • Any sport

💬 QUESTIONS? Message us anytime.

---
By spiced_slabs | Powered by HIVE"""

    # URL encode the data
    import urllib.parse
    form_data = urllib.parse.urlencode({
        "access_token": key,
        "name": name,
        "description": full_description,
        "price": price_cents,
        "url": notion_url,
        "published": "false",  # Draft first — you approve before publishing
        "custom_fields[]": "Notion Email (for template delivery)",
        "tags[]": "notion,pokemon,psa,graded cards,collection tracker,bgs,cgc",
    }).encode()

    req = urllib.request.Request(
        f"{GUMROAD_URL}/products",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
            if data.get("success"):
                product = data["product"]
                return {
                    "id": product["id"],
                    "name": product["name"],
                    "url": product.get("short_url", ""),
                    "edit_url": f"https://app.gumroad.com/products/{product['id']}/edit",
                    "price": product["price"],
                }
            else:
                print(f"  ❌ Gumroad error: {data}")
                return None
    except Exception as e:
        print(f"  ❌ Gumroad request error: {e}")
        return None

# ── Telegram ─────────────────────────────────────────────
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

# ── Save template record ─────────────────────────────────
def save_template(slug, data):
    templates = {}
    if TEMPLATES_FILE.exists():
        templates = json.loads(TEMPLATES_FILE.read_text())
    templates[slug] = data
    TEMPLATES_FILE.write_text(json.dumps(templates, indent=2))

# ── Main pipeline ────────────────────────────────────────
def run_pipeline(brief):
    slug = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"\n{'='*55}")
    print(f"  📐 ARCHITECT — Digital Asset Pipeline")
    print(f"  Brief: {brief}")
    print(f"{'='*55}\n")

    # For now use the pre-designed slab tracker
    # Future: Claude generates custom designs from any brief
    if any(word in brief.lower() for word in ["slab", "psa", "bgs", "cgc", "graded", "card"]):
        design = design_slab_vault_tracker()
        print(f"  ✓ Using pre-designed: {design['name']}")
    else:
        print(f"  ⚠️  No matching pre-design. Using Slab Vault Tracker as default.")
        design = design_slab_vault_tracker()

    # Step 1: Build in Notion
    print(f"\n  Step 1: Building Notion template...")
    result = build_notion_template(design)
    if not result:
        send_telegram("❌ <b>Architect failed</b>\nCould not build Notion template.\nCheck that Architect integration has page access in Notion.")
        return None

    root_id, db_ids = result
    notion_url = get_page_url(root_id)
    print(f"\n  ✓ Template URL: {notion_url}")

    # Step 2: Create Gumroad listing (draft)
    print(f"\n  Step 2: Creating Gumroad listing (draft)...")
    listing = create_gumroad_listing(
        name=f"🏆 {design['name']} — Notion Template for Graded Card Collectors",
        description=design["description"],
        price_cents=999,  # $9.99
        notion_url=notion_url
    )

    if listing:
        print(f"  ✓ Gumroad listing created (DRAFT): {listing['edit_url']}")
    else:
        print(f"  ⚠️  Gumroad listing failed — template still created in Notion")

    # Step 3: Save record
    record = {
        "slug": slug,
        "brief": brief,
        "name": design["name"],
        "notion_url": notion_url,
        "notion_page_id": root_id,
        "gumroad": listing,
        "timestamp": now_iso(),
        "status": "draft"
    }
    save_template(slug, record)

    # Step 4: Notify via Telegram
    gumroad_info = ""
    if listing:
        gumroad_info = (
            f"\n\n💰 <b>Gumroad Listing (DRAFT):</b>\n"
            f"<a href='{listing['edit_url']}'>Edit & Publish → ${listing['price']/100:.2f}</a>"
        )

    send_telegram(
        f"📐 <b>Architect Complete!</b>\n"
        f"<i>{design['name']}</i>\n\n"
        f"📋 <b>Notion Template:</b>\n"
        f"<a href='{notion_url}'>View Template</a>\n"
        f"{gumroad_info}\n\n"
        f"⚠️ <b>Action needed:</b>\n"
        f"1. Open Notion template and enable sharing\n"
        f"2. Set 'Allow duplicate as template'\n"
        f"3. Copy share link → add to Gumroad product\n"
        f"4. Publish Gumroad listing\n\n"
        f"Reply <code>publish {slug}</code> when ready"
    )

    print(f"\n✅ Architect pipeline complete!")
    print(f"   Notion: {notion_url}")
    if listing:
        print(f"   Gumroad: {listing['edit_url']}")
    print(f"\n📱 Check Telegram for next steps.")

    return record

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Architect Agent")
    parser.add_argument("--brief", type=str, help="Design brief")
    parser.add_argument("--list",  action="store_true", help="List templates")
    args = parser.parse_args()

    load_env()

    if args.list:
        if TEMPLATES_FILE.exists():
            templates = json.loads(TEMPLATES_FILE.read_text())
            for slug, t in templates.items():
                print(f"  {slug}: {t['name']} — {t['status']}")
        else:
            print("No templates yet.")
    elif args.brief:
        run_pipeline(args.brief)
    else:
        parser.print_help()
