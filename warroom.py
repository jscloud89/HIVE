#!/usr/bin/env python3
"""
warroom.py — The HIVE War Room
Daily autonomous agent meeting. Each day focuses on a different business vertical.
Agents speak in sequence, Queen synthesizes and issues a decree.
Output: JSON transcript + Telegram summary + Chancellor log.

Schedule:
  Monday    — 3D Printing / spiced_slabs
  Tuesday   — Digital Assets
  Wednesday — Printify / Print-on-Demand
  Thursday  — eBay/Etsy Strategy
  Friday    — Hive Infrastructure
  Saturday  — Content & Marketing
  Sunday    — Weekly Review

Usage:
  python3 warroom.py              # runs today's session
  python3 warroom.py --day monday # force a specific day
  python3 warroom.py --dry-run    # print output without saving/sending
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
WARROOM_DIR = DATA_DIR / "warroom"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
LOG_DIR     = DATA_DIR / "logs"

WARROOM_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────────
OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"
CHANCELLOR_URL  = "http://localhost:8001"
MODEL_QUEEN     = "anthropic/claude-opus-4-6"
MODEL_AGENT     = "anthropic/claude-sonnet-4-6"
MODEL_FAST      = "google/gemini-2.5-flash-lite"

DAYS = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]

# ── Day definitions ──────────────────────────────────────────
SESSIONS = {
    "monday": {
        "title": "3D Printing & spiced_slabs",
        "emoji": "🖨️",
        "agents": ["scout", "foreman", "treasurer", "auditor", "bard"],
        "focus": """Today's War Room focuses on the 3D printing business (spiced_slabs on eBay/Etsy).
Topics to cover:
- Current trending 3D printed products (Scout researches)
- Printer queue status and capacity (Foreman reports)
- Margin analysis on potential new products (Treasurer calculates)
- Best performing products this week (Auditor reviews)
- Listing copy and product presentation ideas (Bard suggests)
Queen synthesizes and issues a decree on what to print and list next.""",
        "data_needed": ["financial", "market", "queue", "activity"],
    },
    "tuesday": {
        "title": "Digital Assets & Passive Income",
        "emoji": "💻",
        "agents": ["bard", "architect", "scout", "treasurer"],
        "focus": """Today's War Room focuses on digital asset creation and passive income streams.
Topics to cover:
- Trending digital products on Etsy (Notion templates, prompt packs, printables, SVGs) (Scout)
- Digital product concepts the Hive could create and sell (Architect + Bard)
- Margin analysis — digital = 100% margin, infinite inventory (Treasurer)
- Content and presentation strategy for digital listings (Bard)
Queen synthesizes and decrees which digital product(s) to create and publish this week.
Priority: zero fulfillment cost, zero shipping, scalable.""",
        "data_needed": ["financial", "market"],
    },
    "wednesday": {
        "title": "Printify & Print-on-Demand",
        "emoji": "👕",
        "agents": ["scout", "bard", "treasurer", "worker"],
        "focus": """Today's War Room focuses on Printify print-on-demand products.
Topics to cover:
- Trending POD niches this week (t-shirts, mugs, hoodies, posters) (Scout)
- Design concepts that align with Hive brand and current trends (Bard)
- Margin analysis on Printify products vs 3D printing (Treasurer)
- Listing and fulfillment workflow — fully automated? (Worker)
Queen synthesizes and decrees whether to launch a Printify product this week,
and if so, exactly what design/product/niche to pursue.""",
        "data_needed": ["financial", "market"],
    },
    "thursday": {
        "title": "eBay/Etsy Strategy & Optimization",
        "emoji": "📈",
        "agents": ["auditor", "treasurer", "scout", "worker", "concierge"],
        "focus": """Today's War Room focuses on marketplace strategy and optimization.
Topics to cover:
- Current listing performance review (Auditor)
- Pricing optimization — are we leaving money on the table? (Treasurer)
- Competitor analysis — what are top sellers doing differently? (Scout)
- Listing SEO and title optimization opportunities (Worker)
- Customer experience and review strategy (Concierge)
Queen synthesizes and issues strategic directives for the week:
price changes, new listings, retired listings, SEO updates.""",
        "data_needed": ["financial", "activity", "queue"],
    },
    "friday": {
        "title": "Hive Infrastructure & Agent Upgrades",
        "emoji": "⚙️",
        "agents": ["engineer", "warden", "supervisor", "architect"],
        "focus": """Today's War Room focuses on Hive infrastructure, reliability, and agent improvements.
Topics to cover:
- System health review — any failures, bottlenecks, or risks this week? (Warden)
- Agent performance — which agents are underperforming or missing capabilities? (Supervisor)
- Proposed improvements or new agent capabilities (Engineer + Architect)
- Security review — any exposure or vulnerabilities? (Warden)
Queen synthesizes and issues infrastructure directives:
what to build, fix, or upgrade before next week.""",
        "data_needed": ["financial", "activity"],
    },
    "saturday": {
        "title": "Content, Marketing & Social",
        "emoji": "📸",
        "agents": ["bard", "concierge", "scout", "worker"],
        "focus": """Today's War Room focuses on content creation, marketing, and social media strategy.
Topics to cover:
- Content ideas for TikTok/Instagram/YouTube Shorts this week (Bard)
- Product photography briefs — what shots do we need? (Bard + Concierge)
- Trending hashtags and communities for our products (Scout)
- Listing image optimization and A/B test ideas (Worker)
- Brand voice and storytelling opportunities (Bard)
Queen synthesizes and issues a content decree:
exactly what content to create, what platform to post on, and what angle to take.""",
        "data_needed": ["financial", "market", "activity"],
    },
    "sunday": {
        "title": "Weekly Review & Next Week Planning",
        "emoji": "👑",
        "agents": ["auditor", "treasurer", "foreman", "scout", "bard"],
        "focus": """Today is the Sunday Weekly Review. The entire Hive reflects on the past week
and plans the week ahead.
Topics to cover:
- Revenue and profit summary for the week (Auditor)
- Recovery progress toward $2,000 goal (Treasurer)
- Production output and efficiency (Foreman)
- Market signals — what opportunities emerged this week? (Scout)
- What worked, what didn't, what to change (All agents)
Queen synthesizes the full week, issues a strategic decree for next week,
and sets priorities for Monday's session.""",
        "data_needed": ["financial", "market", "queue", "activity"],
    },
}

# ── Agent personas ───────────────────────────────────────────
AGENT_SOULS = {
    "scout": "You are Scout, the Hive's market research agent. You find trending products, niches, and opportunities. You are data-driven, specific, and cite real market signals. Keep responses under 150 words.",
    "foreman": "You are Foreman, the Hive's 3D printing operations manager. You know the A1 Mini's capacity, current print queue, filament status, and production efficiency. Keep responses under 150 words.",
    "treasurer": "You are Treasurer, the Hive's margin and financial analyst. You calculate costs, fees, margins, and ROI. You are precise with numbers. Keep responses under 150 words.",
    "auditor": "You are Auditor, the Hive's financial record keeper. You track revenue, profit, job performance, and financial history. Keep responses under 150 words.",
    "bard": "You are Bard, the Hive's creative and content strategist. You write listing copy, suggest product names, create marketing angles, and develop brand voice. Keep responses under 150 words.",
    "architect": "You are Architect, the Hive's systems and product designer. You design new products, digital assets, and structural improvements. Keep responses under 150 words.",
    "engineer": "You are Engineer, the Hive's technical builder. You identify technical improvements, automation opportunities, and system optimizations. Keep responses under 150 words.",
    "warden": "You are Warden, the Hive's security and reliability monitor. You identify risks, vulnerabilities, and system health issues. Keep responses under 150 words.",
    "supervisor": "You are Supervisor, the Hive's operations overseer. You monitor agent performance, identify bottlenecks, and ensure smooth operations. Keep responses under 150 words.",
    "worker": "You are Worker, the Hive's listing and fulfillment specialist. You create eBay/Etsy listings, optimize titles, and manage the fulfillment pipeline. Keep responses under 150 words.",
    "concierge": "You are Concierge, the Hive's customer experience agent. You handle buyer communication strategy, review management, and customer satisfaction. Keep responses under 150 words.",
}

QUEEN_SOUL = """You are the Queen — the Hive's strategic intelligence and final decision-maker.
You have just presided over a War Room session where your agents have spoken.
Your job is to synthesize their input and issue a clear, actionable Royal Decree.

Your decree must:
1. Acknowledge the strongest insights from the session
2. Make ONE clear primary decision (what to do this week)
3. List 2-3 specific action items with assigned agents
4. Note any risks or conditions to watch
5. Be decisive — the Hive executes on your word

Format your response as:
DECREE: [one sentence decision]
REASONING: [2-3 sentences]
ACTIONS:
- [Agent]: [specific task]
- [Agent]: [specific task]
- [Agent]: [specific task]
WATCH: [one risk or condition to monitor]

Keep it under 250 words. Be the Queen."""

# ── Helpers ──────────────────────────────────────────────────
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
    utc = datetime.now(timezone.utc)
    ct = utc - timedelta(hours=5)  # CDT
    return ct.strftime("%Y-%m-%d %H:%M CT")

def get_day_name():
    return DAYS[datetime.now().weekday()]

def call_openrouter(system, user, model=MODEL_AGENT, max_tokens=400):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set")
        return None

    body = json.dumps({
        "model": model,
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
            "X-Title": "HIVE War Room"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code}: {e.read().decode()[:100]}")
        return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None

def get_hive_status():
    try:
        req = urllib.request.Request(
            f"{CHANCELLOR_URL}/hive-status",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠️  Chancellor offline: {e}")
        return {}

def send_telegram(message):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  ⚠️  Telegram not configured")
        return False

    body = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }).encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True
    except Exception as e:
        print(f"  ⚠️  Telegram error: {e}")
        return False

def post_to_chancellor(session_data):
    """Store war room session in Chancellor data directory."""
    try:
        outdir = DATA_DIR / "warroom"
        outdir.mkdir(parents=True, exist_ok=True)
        fname = outdir / f"{session_data['date']}-{session_data['day']}.json"
        fname.write_text(json.dumps(session_data, indent=2))
        print(f"  💾 Session saved: {fname.name}")
    except Exception as e:
        print(f"  ⚠️  Save error: {e}")

def update_memory(day, title, decree_text):
    ts = now_ct()
    line = f"## {ts} — {title}\n{decree_text[:200]}\n\n"
    existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    MEMORY_FILE.write_text(line + existing)

# ── Main War Room ─────────────────────────────────────────────
def run_warroom(day_name, dry_run=False):
    session = SESSIONS[day_name]
    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*56}")
    print(f"  {session['emoji']} WAR ROOM — {session['title'].upper()}")
    print(f"  {date_str} · {day_name.capitalize()}")
    print(f"{'='*56}\n")

    # Get live hive data
    print("📡 Fetching hive status from Chancellor...")
    hive_data = get_hive_status()
    f = hive_data.get("financial", {})
    m = hive_data.get("market", {})
    q = hive_data.get("queue", {})
    agents = hive_data.get("agents", {})

    # Build context for agents
    context = f"""HIVE STATUS ({now_ct()}):
- Recovery: ${f.get('recovery_usd', 0):.2f} / $2,000 ({f.get('recovery_pct', 0):.1f}%)
- Revenue Today: ${f.get('revenue_today', 0):.2f} | MTD: ${f.get('revenue_mtd', 0):.2f}
- Net Profit: ${f.get('net_profit', 0):.2f}
- Active Agents: {agents.get('online_count', 0)} / {agents.get('total', 18)}
- Queue: {q.get('pending', 0)} pending jobs
- Current Niche: {m.get('niche', 'None')}
- Market Vigor: {m.get('vigor', 0)} / 10
- Last Decree: {hive_data.get('decree', {}).get('decision', 'None')}

TODAY'S FOCUS: {session['focus']}

Speak as your agent persona. Be specific, actionable, and brief."""

    # ── Agent round table ──
    transcript = []
    print(f"🎙️  Agents speaking:\n")

    for agent_id in session["agents"]:
        soul = AGENT_SOULS.get(agent_id, f"You are {agent_id}, a Hive agent.")
        print(f"  → {agent_id.capitalize()}...", end=" ", flush=True)

        response = call_openrouter(
            system=soul,
            user=context + f"\n\nSpeak as {agent_id.capitalize()} for today's {session['title']} War Room session.",
            model=MODEL_AGENT,
            max_tokens=200
        )

        if response:
            print(f"✓")
            transcript.append({
                "agent": agent_id,
                "timestamp": now_iso(),
                "content": response
            })
            print(f"     {response[:120]}{'...' if len(response)>120 else ''}\n")
        else:
            print(f"✗ (skipped)")
            transcript.append({
                "agent": agent_id,
                "timestamp": now_iso(),
                "content": f"[{agent_id} did not respond]"
            })

    # ── Queen synthesizes ──
    print(f"\n👑 Queen deliberating...\n")

    agent_statements = "\n\n".join([
        f"{t['agent'].upper()}: {t['content']}"
        for t in transcript
        if "[did not respond]" not in t["content"]
    ])

    queen_prompt = f"""WAR ROOM SESSION: {session['title']}
Date: {date_str}

{context}

AGENT STATEMENTS:
{agent_statements}

Issue your Royal Decree."""

    queen_response = call_openrouter(
        system=QUEEN_SOUL,
        user=queen_prompt,
        model=MODEL_QUEEN,
        max_tokens=400
    )

    if not queen_response:
        queen_response = "DECREE: Insufficient data to issue decree today. Monitor and reconvene."

    print(f"{'─'*50}")
    print(f"👑 ROYAL DECREE:\n")
    print(f"{queen_response}")
    print(f"{'─'*50}\n")

    # ── Build session record ──
    session_data = {
        "date": date_str,
        "day": day_name,
        "title": session["title"],
        "emoji": session["emoji"],
        "timestamp": now_iso(),
        "hive_snapshot": {
            "recovery_usd": f.get("recovery_usd", 0),
            "recovery_pct": f.get("recovery_pct", 0),
            "revenue_today": f.get("revenue_today", 0),
            "net_profit": f.get("net_profit", 0),
        },
        "agents": session["agents"],
        "transcript": transcript,
        "decree": queen_response
    }

    # ── Telegram summary ──
    tg_lines = [
        f"{session['emoji']} <b>WAR ROOM — {session['title'].upper()}</b>",
        f"<i>{date_str}</i>",
        "",
        f"<b>Agents:</b> {', '.join(a.capitalize() for a in session['agents'])}",
        "",
        f"<b>👑 ROYAL DECREE:</b>",
        f"<code>{queen_response[:600]}</code>",
        "",
        f"💰 Recovery: ${f.get('recovery_usd',0):.2f} / $2,000 ({f.get('recovery_pct',0):.1f}%)",
        f"📦 Queue: {q.get('pending',0)} pending",
    ]
    tg_message = "\n".join(tg_lines)

    if not dry_run:
        print("📱 Sending to Telegram...", end=" ")
        ok = send_telegram(tg_message)
        print("✓" if ok else "✗")

        post_to_chancellor(session_data)
        update_memory(day_name, session["title"], queen_response)
        print(f"\n✅ War Room complete — {now_ct()}")
    else:
        print("🔍 DRY RUN — not saving or sending")

    return session_data

# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE War Room")
    parser.add_argument("--day", type=str, choices=DAYS, help="Force specific day")
    parser.add_argument("--dry-run", action="store_true", help="Don't save or send")
    args = parser.parse_args()

    load_env()

    day = args.day or get_day_name()
    print(f"⬡ HIVE War Room — {day.capitalize()}")

    run_warroom(day, dry_run=args.dry_run)
