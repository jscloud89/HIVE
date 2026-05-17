#!/usr/bin/env python3
"""
scout.py — The Hive's Forager Scout (v2 — API + web search)
workspace-scout · Researches niches and produces waggle dance JSON for Queen
Usage: python3 scout.py [--category "Etsy"] [--dry-run] [--force-slug "slug"] [--tip "custom niche"]
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
WORKSPACE   = Path(__file__).parent
HIVE_ROOT   = WORKSPACE.parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data"
WAGGLE_DIR  = DATA_DIR / "waggle"
SCOUT_DIR   = DATA_DIR / "scout"
LOG_DIR     = DATA_DIR / "logs"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
QUEUE_FILE  = DATA_DIR / "research-queue.json"
SOUL_FILE   = WORKSPACE / "SOUL.md"

# ── Config ───────────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_SONNET   = "anthropic/claude-sonnet-4-6"
MODEL_FLASH    = "google/gemini-2.5-flash-lite"

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
    pending = [t for t in queue if t.get("status") == "pending"]
    if force_slug:
        pending = [t for t in pending if t.get("slug") == force_slug]
    if category_filter:
        pending = [t for t in pending if t.get("category", "").lower() == category_filter.lower()]
    if not pending:
        return None
    return sorted(pending, key=lambda x: x.get("priority", 99))[0]

def load_soul() -> str:
    if SOUL_FILE.exists():
        return SOUL_FILE.read_text()
    return "You are Scout, the Hive's forager research agent."

def call_openrouter(system: str, user: str, model: str, max_tokens: int = 800,
                    web_search: bool = False) -> str:
    """Call OpenRouter and return text response."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user}
        ]
    }

    if web_search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

    payload = json.dumps(body).encode()

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
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            content = result["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            return content.strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  ⚠️  OpenRouter error {e.code}: {body[:300]}")
        return ""
    except Exception as e:
        print(f"  ⚠️  Error: {e}")
        return ""

# ── Phase 1: Discovery ────────────────────────────────────────

def discover_niches(category: str, focus: str, tip: str = None) -> str:
    tip_context = f"\nHot tip from Architect to investigate: {tip}" if tip else ""

    user = f"""You are a market research analyst scouting for a 3D printing Etsy/eBay seller.

Category: {category}
Focus: {focus}{tip_context}
Date: {now_slug()}

Search for what is currently trending and selling well in this category.
Research:
- Specific products popular right now on {category}
- Price ranges that are working ($10-$50 sweet spot for 3D prints)
- Competition level — dominant sellers or fragmented market?
- Gaps or underserved sub-niches
- Recent review velocity as demand signal

Return:
1. Top 3-5 specific niches found within this category
2. Price point observations
3. Competition density assessment  
4. Which 1-2 niches look most promising and why
5. Any seasonal or trend signals

Be specific with product names and numbers."""

    return call_openrouter(
        "You are a precise market research analyst. Be data-focused and specific.",
        user,
        MODEL_FLASH,
        max_tokens=800,
        web_search=True
    )

# ── Phase 2: Waggle Dance Synthesis ──────────────────────────

def synthesize_waggle(soul: str, task: dict, discovery: str, tip: str = None) -> dict:
    tip_context = f"\nArchitect tip: {tip}" if tip else ""

    user = f"""You are Scout. Research phase complete.

CATEGORY: {task.get('category')}
FOCUS: {task.get('focus')}{tip_context}
DATE: {now_slug()}

DISCOVERY FINDINGS:
{discovery}

Pick the single most promising specific niche and produce a complete waggle dance JSON.
Show vigor math in scout_notes. Apply filament viability bonuses where applicable.
Bird safety: CLEAR for PLA/PETG/TPU. CONDITIONAL for ABS/ASA. VETO for resin.

Respond ONLY with valid JSON — no preamble, no markdown fences:
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
  "scout_notes": "Vigor math: demand(X/3) + competition(X/3) + price(X/2) + trend(X/2) + filament bonus. Models: Flash+websearch for discovery, Sonnet for synthesis."
}}"""

    raw = call_openrouter(soul, user, MODEL_SONNET, max_tokens=1200)

    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])

    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON from Sonnet:\n{raw[:500]}")
        sys.exit(1)

# ── Output ────────────────────────────────────────────────────

def save_waggle(waggle: dict) -> Path:
    WAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    slug = waggle.get("niche_slug", "unknown")
    path = WAGGLE_DIR / f"{now_slug()}-{slug}.json"
    with open(path, "w") as f:
        json.dump(waggle, f, indent=2)
    return path

def write_memory(task: dict, waggle: dict):
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
    for t in queue:
        if t.get("slug") == task.get("slug"):
            t["status"] = "researched"
            t["last_run"] = now_slug()
    save_queue(queue)

# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scout — Hive forager research agent")
    parser.add_argument("--category", help="Filter by category (Etsy/eBay/Cults3D)")
    parser.add_argument("--force-slug", help="Force a specific queue slug")
    parser.add_argument("--tip", help="Hot tip from Architect — investigate this specifically")
    parser.add_argument("--dry-run", action="store_true", help="Validate queue and exit without API calls")
    args = parser.parse_args()

    load_env()
    SCOUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("\n🔍 SCOUT — Forager Research Agent v2")
    print("=" * 45)

    soul  = load_soul()
    queue = load_queue()
    task  = pick_task(queue, args.category, args.force_slug)

    if not task:
        print("📭 No pending tasks in research queue.")
        print(f"   Queue: {QUEUE_FILE}")
        sys.exit(0)

    print(f"📋 Task:  {task.get('category')} — {task.get('focus')}")
    print(f"🏷️  Slug:  {task.get('slug')}")
    if args.tip:
        print(f"💡 Tip:   {args.tip}")

    if args.dry_run:
        print("\n✅ Dry run — queue valid, SOUL.md loaded, no API calls made")
        sys.exit(0)

    # Phase 1
    print(f"\n🌐 Phase 1: Discovery via Flash + web search...")
    discovery = discover_niches(task.get("category"), task.get("focus"), args.tip)
    if not discovery:
        print("  ⚠️  Discovery returned empty — proceeding with Sonnet only")
        discovery = f"No discovery data. Research {task.get('focus')} on {task.get('category')} from general knowledge."
    print(f"  ✅ {len(discovery)} chars of intelligence gathered")
    print(f"  Preview: {discovery[:250]}...")

    # Phase 2
    print(f"\n💃 Phase 2: Waggle synthesis via Sonnet...")
    waggle = synthesize_waggle(soul, task, discovery, args.tip)

    print("\n" + "=" * 45)
    print(f"🔍 NICHE:      {waggle.get('niche')}")
    print(f"📊 VIGOR:      {waggle.get('vigor')}")
    print(f"🎯 CONFIDENCE: {waggle.get('confidence_score')}")
    print(f"🐦 BIRD SAFE:  {waggle.get('bird_safety')}")
    print(f"✅ ACTION:     {waggle.get('recommended_action')}")
    print(f"📋 NOTES:      {str(waggle.get('scout_notes',''))[:200]}...")
    print("=" * 45)

    waggle_path = save_waggle(waggle)
    print(f"\n💾 Waggle saved: {waggle_path}")
    write_memory(task, waggle)
    mark_complete(queue, task)
    print(f"✅ Task complete · Queue updated · Memory logged")
    print(f"\n👑 Run Queen:")
    print(f"   python3 ~/HIVE/workspace-queen/queen.py --waggle {waggle_path}\n")

if __name__ == "__main__":
    main()
