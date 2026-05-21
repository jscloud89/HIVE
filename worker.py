#!/usr/bin/env python3
"""
worker.py — HIVE Worker Agent
Creates Printify POD products from design briefs.

Pipeline:
  Decree → Bard generates art prompt → Gemini creates image
  → Printify uploads image → Product created → eBay listing live

Usage:
  python3 worker.py --brief "Pokemon themed coffee mug, Pokeball design"
  python3 worker.py --catalog          # show available product types
  python3 worker.py --providers <id>   # show print providers for a blueprint
  python3 worker.py --list             # list created products
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE    = Path(__file__).parent
PHASE1_DIR   = Path.home() / "hive-phase1"
DATA_DIR     = PHASE1_DIR / "data"
RENDERS_DIR  = Path.home() / "HIVE" / "renders"
PRODUCTS_FILE = WORKSPACE / "products.json"
MEMORY_FILE  = WORKSPACE / "MEMORY.md"

(DATA_DIR / "worker").mkdir(parents=True, exist_ok=True)
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PRINTIFY_BASE  = "https://api.printify.com/v1"
GEMINI_BASE    = "https://generativelanguage.googleapis.com/v1beta"
MODEL_BARD     = "anthropic/claude-sonnet-4-6"
MODEL_FAST     = "google/gemini-2.5-flash-lite"

# Popular blueprint IDs (Printify product types)
BLUEPRINTS = {
    "tshirt_bella":     5,    # Bella+Canvas 3001 Unisex T-Shirt
    "tshirt_gildan":    12,   # Gildan 64000 Unisex T-Shirt
    "hoodie":           92,   # Gildan 18500 Heavy Blend Hoodie
    "mug_11oz":         19,   # White Glossy Mug 11oz
    "mug_15oz":         507,  # White Glossy Mug 15oz
    "poster_matte":     473,  # Matte Poster
    "tote":             74,   # Natural Canvas Tote Bag
    "phone_case":       84,   # Tough Phone Case
    "sticker":          359,  # Kiss-Cut Stickers
    "pillow":           57,   # Throw Pillow
}

WORKER_SOUL = """You are Bard, the HIVE's creative director and copywriter.
Given a product concept, you create:
1. An image generation prompt for Gemini Imagen
2. A product title for eBay/Etsy
3. A product description
4. Relevant tags

Be specific, creative, and market-aware. 
Output ONLY valid JSON with keys: image_prompt, title, description, tags (array)."""

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

def printify_request(method, endpoint, data=None):
    key     = os.environ.get("PRINTIFY_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": "https://printify.com",
        "Referer": "https://printify.com/",
    }
    req = urllib.request.Request(
        f"{PRINTIFY_BASE}{endpoint}",
        data=json.dumps(data).encode() if data else None,
        headers=headers,
        method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ❌ Printify HTTP {e.code}: {err[:200]}")
        return None
    except Exception as e:
        print(f"  ❌ Printify error: {e}")
        return None

def call_claude(system, user, max_tokens=1500):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    body = json.dumps({
        "model": MODEL_BARD,
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
            "X-Title": "HIVE Worker"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read().decode())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ Claude error: {e}")
        return None

def send_telegram(text, image_path=None):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    if image_path and Path(image_path).exists():
        _send_photo(token, chat_id, image_path, text)
    else:
        body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"  ⚠️  Telegram: {e}")

def _send_photo(token, chat_id, image_path, caption):
    img = Path(image_path)
    boundary = "----HiveWorkerBoundary"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{img.name}\"\r\nContent-Type: image/png\r\n\r\n",
    ]
    body = b"".join(p.encode() for p in parts) + img.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  ⚠️  Photo send: {e}")
        send_telegram(caption)

def update_memory(event):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M CT")
    line = f"## {ts} — {event}\n"
    existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    MEMORY_FILE.write_text(line + existing)

def load_products():
    if PRODUCTS_FILE.exists():
        return json.loads(PRODUCTS_FILE.read_text())
    return {}

def save_product(slug, data):
    products = load_products()
    products[slug] = data
    PRODUCTS_FILE.write_text(json.dumps(products, indent=2))

# ── Step 1: Bard generates creative brief ────────────────
def generate_creative_brief(brief, product_type="tshirt_bella"):
    print(f"  🎨 Bard generating creative brief...")

    prompt = f"""Product brief: {brief}
Product type: {product_type}

Create a complete creative package for this POD product.

The image_prompt should be optimized for Gemini Imagen:
- Specific art style (vector, watercolor, pixel art, bold graphic, etc.)
- Color palette
- Key visual elements
- Background treatment (transparent or solid)
- Print-ready quality

The title should be SEO-optimized for eBay/Etsy (max 80 chars).
The description should be 150-200 words, benefit-focused.
Tags should be 13 relevant keywords.

Return ONLY valid JSON:
{{
  "image_prompt": "...",
  "title": "...",
  "description": "...",
  "tags": ["tag1", "tag2", ...]
}}"""

    response = call_claude(WORKER_SOUL, prompt)
    if not response:
        return None

    import re
    clean = re.sub(r'```json|```', '', response).strip()
    try:
        return json.loads(clean)
    except:
        print(f"  ⚠️  Could not parse brief JSON")
        return None

# ── Step 2: Gemini generates artwork ─────────────────────
def generate_artwork(image_prompt, slug):
    print(f"  🖼️  Gemini generating artwork...")
    key = os.environ.get("GOOGLE_API_KEY", "")
    endpoint = f"{GEMINI_BASE}/models/gemini-2.5-flash-image:generateContent?key={key}"

    # Enhance prompt for print-ready output
    full_prompt = f"{image_prompt}. Print-ready design, high resolution, clean edges, suitable for apparel and merchandise printing."

    body = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}
    }).encode()

    req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
            for part in data["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    img_data = base64.b64decode(part["inlineData"]["data"])
                    out_path = RENDERS_DIR / f"{slug}-design.png"
                    out_path.write_bytes(img_data)
                    print(f"  ✅ Artwork saved: {out_path.name} ({len(img_data)//1024}KB)")
                    return out_path
    except Exception as e:
        print(f"  ❌ Gemini error: {e}")
    return None

# ── Step 3: Upload image to Printify ─────────────────────
def upload_to_printify(image_path, file_name):
    print(f"  ⬆️  Uploading to Printify...")
    img_data = Path(image_path).read_bytes()
    b64 = base64.b64encode(img_data).decode()

    data = {
        "file_name": file_name,
        "contents": b64
    }

    shop_id = os.environ.get("PRINTIFY_SHOP_ID", "27624981")
    result = printify_request("POST", f"/uploads/images.json", data)

    if result and result.get("id"):
        print(f"  ✅ Image uploaded: {result['id']}")
        return result["id"]
    return None

# ── Step 4: Get print provider ───────────────────────────
def get_print_provider(blueprint_id):
    """Get the best available print provider for a blueprint."""
    result = printify_request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")
    if result and len(result) > 0:
        # Prefer US providers
        us = [p for p in result if "US" in p.get("location", {}).get("country", "")]
        provider = us[0] if us else result[0]
        print(f"  ✓ Provider: {provider['title']} (ID: {provider['id']})")
        return provider["id"]
    return None

# ── Step 5: Get variants ──────────────────────────────────
def get_variants(blueprint_id, provider_id):
    """Get available variants for a product."""
    result = printify_request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")
    if not result:
        return []

    variants = result.get("variants", [])
    # For t-shirts: get common sizes in a few colors
    # Return all enabled variants, limited to first 20
    enabled = [v for v in variants if v.get("is_available", True)]
    return enabled[:20]

# ── Step 6: Create product ───────────────────────────────
def create_printify_product(brief_data, image_id, blueprint_id, provider_id, variants):
    print(f"  📦 Creating Printify product...")
    shop_id = os.environ.get("PRINTIFY_SHOP_ID", "27624981")

    # Build print areas
    print_areas = [{
        "variant_ids": [v["id"] for v in variants],
        "placeholders": [{
            "position": "front",
            "images": [{
                "id": image_id,
                "x": 0.5,
                "y": 0.5,
                "scale": 1,
                "angle": 0
            }]
        }]
    }]

    # Build variants with pricing
    product_variants = []
    for v in variants:
        product_variants.append({
            "id": v["id"],
            "price": 2499,  # $24.99 default — Treasurer will optimize
            "is_enabled": True
        })

    data = {
        "title": brief_data["title"],
        "description": brief_data["description"],
        "blueprint_id": blueprint_id,
        "print_provider_id": provider_id,
        "variants": product_variants,
        "print_areas": print_areas,
        "tags": brief_data.get("tags", [])[:13],
    }

    result = printify_request("POST", f"/shops/{shop_id}/products.json", data)
    if result and result.get("id"):
        print(f"  ✅ Product created: {result['id']}")
        return result
    return None

# ── Step 7: Publish to eBay ──────────────────────────────
def publish_product(product_id):
    print(f"  🚀 Publishing to eBay...")
    shop_id = os.environ.get("PRINTIFY_SHOP_ID", "27624981")
    result = printify_request(
        "POST",
        f"/shops/{shop_id}/products/{product_id}/publish.json",
        {
            "title": True,
            "description": True,
            "images": True,
            "variants": True,
            "tags": True,
            "keyFeatures": True,
            "shipping_template": True
        }
    )
    if result:
        print(f"  ✅ Published!")
        return True
    return False

# ── Catalog browser ──────────────────────────────────────
def show_catalog():
    print("\n⬡ Popular Printify Products:\n")
    for name, bid in BLUEPRINTS.items():
        print(f"  {name:<20} blueprint_id={bid}")
    print("\nFor full catalog: https://printify.com/app/store/products/new")

def show_providers(blueprint_id):
    result = printify_request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")
    if result:
        print(f"\n⬡ Print Providers for blueprint {blueprint_id}:\n")
        for p in result:
            loc = p.get("location", {})
            print(f"  ID: {p['id']:<6} {p['title']:<40} {loc.get('country','?')}")

# ── Main pipeline ────────────────────────────────────────
def run_pipeline(brief, product_type="tshirt_bella", publish=False):
    slug = datetime.now().strftime("%Y%m%d-%H%M%S")
    blueprint_id = BLUEPRINTS.get(product_type, 5)

    print(f"\n{'='*55}")
    print(f"  👕 WORKER — POD Pipeline")
    print(f"  Brief: {brief}")
    print(f"  Product: {product_type} (blueprint {blueprint_id})")
    print(f"{'='*55}\n")

    # Step 1: Creative brief
    brief_data = generate_creative_brief(brief, product_type)
    if not brief_data:
        print("  ❌ Failed to generate creative brief")
        return None

    print(f"  ✓ Title: {brief_data['title']}")
    print(f"  ✓ Prompt: {brief_data['image_prompt'][:80]}...")

    # Step 2: Generate artwork
    artwork_path = generate_artwork(brief_data["image_prompt"], slug)
    if not artwork_path:
        print("  ❌ Failed to generate artwork")
        return None

    # Send preview to Telegram for approval
    caption = (
        f"👕 <b>Worker Design Ready</b>\n"
        f"<i>{brief_data['title']}</i>\n\n"
        f"Product: {product_type}\n"
        f"Price: $24.99\n\n"
        f"Reply:\n"
        f"✅ <code>pod-approve {slug}</code> — create & publish\n"
        f"🔧 <code>pod-remix {slug}: feedback</code> — regenerate\n"
        f"❌ <code>pod-drop {slug}</code> — discard"
    )
    send_telegram(caption, artwork_path)

    # Save pending record
    save_product(slug, {
        "slug": slug,
        "brief": brief,
        "product_type": product_type,
        "blueprint_id": blueprint_id,
        "brief_data": brief_data,
        "artwork_path": str(artwork_path),
        "status": "pending_approval",
        "timestamp": now_iso()
    })

    print(f"\n📱 Preview sent to Telegram — awaiting approval")
    print(f"   Slug: {slug}")

    if publish:
        return _complete_pipeline(slug, blueprint_id, brief_data, artwork_path)

    return slug

def _complete_pipeline(slug, blueprint_id, brief_data, artwork_path):
    """Complete the pipeline after approval."""
    # Upload image
    image_id = upload_to_printify(artwork_path, f"{slug}-design.png")
    if not image_id:
        send_telegram(f"❌ <b>Worker failed</b>\nCould not upload image to Printify.")
        return None

    # Get provider
    provider_id = get_print_provider(blueprint_id)
    if not provider_id:
        send_telegram(f"❌ <b>Worker failed</b>\nNo print provider available.")
        return None

    # Get variants
    variants = get_variants(blueprint_id, provider_id)
    if not variants:
        send_telegram(f"❌ <b>Worker failed</b>\nNo variants available.")
        return None

    print(f"  ✓ {len(variants)} variants available")

    # Create product
    product = create_printify_product(brief_data, image_id, blueprint_id, provider_id, variants)
    if not product:
        send_telegram(f"❌ <b>Worker failed</b>\nCould not create Printify product.")
        return None

    product_id = product["id"]

    # Publish
    published = publish_product(product_id)

    # Update record
    products = load_products()
    if slug in products:
        products[slug]["status"] = "published" if published else "created"
        products[slug]["printify_id"] = product_id
        PRODUCTS_FILE.write_text(json.dumps(products, indent=2))

    update_memory(f"POD product created: {brief_data['title']} → {product_id}")

    # Final Telegram notification
    status = "published to eBay" if published else "created (not yet published)"
    send_telegram(
        f"✅ <b>Worker Complete!</b>\n"
        f"<i>{brief_data['title']}</i>\n\n"
        f"Status: {status}\n"
        f"Printify ID: <code>{product_id}</code>\n\n"
        f"<a href='https://printify.com/app/store/products/{product_id}/edit'>View on Printify</a>"
    )

    print(f"\n✅ Pipeline complete — {product_id}")
    return product_id

def approve_product(slug):
    """Called when user approves via Telegram."""
    products = load_products()
    if slug not in products:
        send_telegram(f"❓ Product not found: <code>{slug}</code>")
        return

    data = products[slug]
    send_telegram(f"✅ <b>Approved!</b> Creating product...\n<i>{data['brief_data']['title']}</i>")

    _complete_pipeline(
        slug,
        data["blueprint_id"],
        data["brief_data"],
        data["artwork_path"]
    )

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Worker — POD Pipeline")
    parser.add_argument("--brief",     type=str, help="Product brief")
    parser.add_argument("--product",   type=str, default="tshirt_bella", help="Product type")
    parser.add_argument("--publish",   action="store_true", help="Auto-publish without approval")
    parser.add_argument("--catalog",   action="store_true", help="Show product catalog")
    parser.add_argument("--providers", type=int, metavar="BLUEPRINT_ID", help="Show providers")
    parser.add_argument("--approve",   type=str, metavar="SLUG", help="Approve pending product")
    parser.add_argument("--list",      action="store_true", help="List products")
    args = parser.parse_args()

    load_env()

    if args.catalog:
        show_catalog()
    elif args.providers:
        show_providers(args.providers)
    elif args.approve:
        approve_product(args.approve)
    elif args.list:
        products = load_products()
        if not products:
            print("No products yet.")
        for slug, p in products.items():
            print(f"  {slug}: {p.get('brief_data',{}).get('title','?')[:50]} — {p.get('status','?')}")
    elif args.brief:
        run_pipeline(args.brief, args.product, args.publish)
    else:
        parser.print_help()
