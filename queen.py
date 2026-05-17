#!/usr/bin/env python3
"""
queen.py — The Queen's Decision Engine
Hive Phase 1 · workspace-queen
Usage: python3 queen.py --waggle /path/to/waggle.json [--dry-run]
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────
WORKSPACE   = Path(__file__).parent
HIVE_ROOT   = WORKSPACE.parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
SOUL_FILE   = WORKSPACE / "SOUL.md"
LOG_DIR     = DATA_DIR / "logs"
DECREE_DIR  = DATA_DIR / "waggle"

# ── Config ───────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL              = "anthropic/claude-opus-4-6"
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
VIGOR_THRESHOLD    = 7.0
CONFIDENCE_MIN     = 60

def load_env():
    """Load .env file from hive-phase1."""
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

def load_soul():
    """Load Queen's SOUL.md as system prompt."""
    if not SOUL_FILE.exists():
        print("❌ SOUL.md not found — Queen has no identity.")
        sys.exit(1)
    return SOUL_FILE.read_text()

def load_waggle(path: str) -> dict:
    """Load and validate waggle dance JSON from Scout."""
    p = Path(path)
    if not p.exists():
        print(f"❌ Waggle dance file not found: {path}")
        sys.exit(1)
    with open(p) as f:
        data = json.load(f)
    required = ["niche", "vigor_score", "confidence_score", "evidence"]
    missing = [k for k in required if k not in data]
    if missing:
        print(f"❌ Waggle dance missing required fields: {missing}")
        sys.exit(1)
    return data

def call_queen(soul: str, waggle: dict) -> dict:
    """Call OpenRouter with Queen's SOUL and waggle dance data."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set in environment")
        sys.exit(1)

    user_prompt = f"""Scout has returned with a waggle dance report. Evaluate it and issue your decree.

WAGGLE DANCE REPORT:
{json.dumps(waggle, indent=2)}

Respond ONLY with a valid JSON decree object. No preamble, no explanation outside the JSON.
"""

    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 1000,
        "messages": [
            {"role": "system", "content": soul},
            {"role": "user",   "content": user_prompt}
        ]
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jscloud89/HIVE",
            "X-Title": "HIVE-Queen"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"❌ OpenRouter HTTP error: {e.code} {e.reason}")
        print(e.read().decode())
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"❌ Network error: {e.reason}")
        sys.exit(1)

    raw_text = result["choices"][0]["message"]["content"].strip()

    # Strip markdown fences if present
    if raw_text.startswith("```"):
        raw_text = "\n".join(raw_text.split("\n")[1:])
    if raw_text.endswith("```"):
        raw_text = "\n".join(raw_text.split("\n")[:-1])

    try:
        decree = json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"❌ Queen returned non-JSON response:\n{raw_text}")
        sys.exit(1)

    return decree

def enforce_hard_rules(waggle: dict, decree: dict) -> dict:
    """Apply Queen's hard rules as a safety layer."""
    vigor        = waggle.get("vigor_score", 0)
    confidence   = waggle.get("confidence_score", 0)
    override_msg = None

    if confidence < CONFIDENCE_MIN and decree.get("decree") == "approved":
        override_msg = f"Confidence {confidence} < {CONFIDENCE_MIN} minimum — auto-denied"
        decree["decree"] = "denied"
        decree["reasoning"] = override_msg

    if vigor < VIGOR_THRESHOLD and decree.get("decree") == "approved":
        override_msg = f"Vigor score {vigor} < {VIGOR_THRESHOLD} threshold — auto-denied"
        decree["decree"] = "denied"
        decree["reasoning"] = override_msg

    if override_msg:
        print(f"⚠️  Hard rule override: {override_msg}")

    return decree

def write_memory(waggle: dict, decree: dict):
    """Append decree to MEMORY.md."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n## {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"- **Niche:** {waggle.get('niche', 'unknown')}\n"
        f"- **Vigor:** {waggle.get('vigor_score', '?')}\n"
        f"- **Confidence:** {waggle.get('confidence_score', '?')}\n"
        f"- **Decree:** {decree.get('decree', '?').upper()}\n"
        f"- **Reasoning:** {decree.get('reasoning', '')}\n"
        f"- **Worker:** {decree.get('assigned_worker', 'unassigned')}\n"
        f"- **Spend authorized:** ${decree.get('spend_authorized', 0):.2f}\n"
        f"- **Model rec:** {decree.get('model_recommendation', '')}\n"
    )
    with open(MEMORY_FILE, "a") as f:
        f.write(entry)
    print(f"📝 Decree logged to {MEMORY_FILE}")

def save_decree(waggle: dict, decree: dict):
    """Save decree JSON alongside waggle data."""
    DECREE_DIR.mkdir(parents=True, exist_ok=True)
    niche_slug = waggle.get("niche", "unknown").lower().replace(" ", "-")[:30]
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    decree_file = DECREE_DIR / f"decree-{niche_slug}-{ts}.json"
    with open(decree_file, "w") as f:
        json.dump({
            "timestamp": datetime.utcnow().isoformat(),
            "waggle_input": waggle,
            "decree": decree
        }, f, indent=2)
    print(f"💾 Decree saved to {decree_file}")
    return decree_file

def main():
    parser = argparse.ArgumentParser(description="Queen — Hive strategic decision engine")
    parser.add_argument("--waggle", required=True, help="Path to waggle dance JSON from Scout")
    parser.add_argument("--dry-run", action="store_true", help="Load and validate but don't call API")
    args = parser.parse_args()

    load_env()

    print("\n👑 QUEEN — Strategic Decision Engine")
    print("=" * 45)

    soul   = load_soul()
    waggle = load_waggle(args.waggle)

    print(f"📊 Niche:      {waggle.get('niche')}")
    print(f"📊 Vigor:      {waggle.get('vigor_score')}")
    print(f"📊 Confidence: {waggle.get('confidence_score')}")

    if args.dry_run:
        print("\n🔍 Dry run — skipping API call")
        print("✅ Waggle dance validated successfully")
        return

    print(f"\n🧠 Consulting Opus 4.6 via OpenRouter...")
    decree = call_queen(soul, waggle)
    decree = enforce_hard_rules(waggle, decree)

    print("\n" + "=" * 45)
    print(f"👑 DECREE: {decree.get('decree', '?').upper()}")
    print(f"📋 Reasoning: {decree.get('reasoning', '')}")
    print(f"👷 Worker: {decree.get('assigned_worker', 'unassigned')}")
    print(f"💰 Spend authorized: ${decree.get('spend_authorized', 0):.2f}")
    print(f"🤖 Model recommendation: {decree.get('model_recommendation', '')}")
    print("=" * 45)

    write_memory(waggle, decree)
    decree_file = save_decree(waggle, decree)

    print(f"\n✅ Queen's session complete\n")

if __name__ == "__main__":
    main()
