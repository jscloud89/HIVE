#!/usr/bin/env python3
"""
nurse.py — The Hive's Health Monitor & Morning Briefing Agent
workspace-nurse · Runs daily at 06:00 CT via cron
Usage: python3 nurse.py [--test]
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────
WORKSPACE   = Path(__file__).parent
HIVE_ROOT   = WORKSPACE.parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data"
LOG_DIR     = DATA_DIR / "logs"
MEMORY_FILE = WORKSPACE / "MEMORY.md"

# ── Config ───────────────────────────────────────────────────
OLLAMA_URL    = "http://localhost:11434/api/generate"
OLLAMA_MODEL  = "llama3.1:8b"
HEARTBEAT_TTL = 86400  # 24 hours in seconds

KNOWN_AGENTS = [
    "architect", "auditor", "bard", "chancellor", "concierge",
    "engineer", "forager", "foreman", "inspector", "nurse",
    "quartermaster", "queen", "scout", "supervisor", "switchboard",
    "treasurer", "warden", "worker"
]

def load_env():
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

def now_ct() -> datetime:
    """Current time in Central Time (UTC-5 standard, UTC-6 daylight — approximate)."""
    return datetime.now(timezone.utc) - timedelta(hours=5)

# ── Data Collectors ──────────────────────────────────────────

def collect_agent_status() -> dict:
    """Check which agents have recent MEMORY.md entries."""
    active   = []
    silent   = []
    now      = datetime.now(timezone.utc)
    cutoff   = now - timedelta(seconds=HEARTBEAT_TTL)

    for agent in KNOWN_AGENTS:
        memory = HIVE_ROOT / f"workspace-{agent}" / "MEMORY.md"
        if memory.exists():
            mtime = datetime.fromtimestamp(memory.stat().st_mtime, tz=timezone.utc)
            if mtime > cutoff:
                active.append(agent)
            else:
                silent.append(agent)
        else:
            silent.append(agent)

    return {"active": active, "silent": silent,
            "count": len(active), "total": len(KNOWN_AGENTS)}

def collect_storage() -> dict:
    """Get disk usage for SSD and HDD."""
    result = {}
    mounts = {
        "SSD": "/",
        "HDD": "/mnt/hive-storage"
    }
    for label, path in mounts.items():
        try:
            usage = shutil.disk_usage(path)
            pct   = round(usage.used / usage.total * 100, 1)
            result[label] = f"{pct}%"
        except Exception:
            result[label] = "N/A"
    return result

def collect_api_spend() -> dict:
    """Check OpenRouter spend from decree logs."""
    today      = now_ct().strftime("%Y-%m-%d")
    month      = now_ct().strftime("%Y-%m")
    today_spend = 0.0
    mtd_spend   = 0.0

    decree_dir = DATA_DIR / "waggle"
    if decree_dir.exists():
        for f in decree_dir.glob("decree-*.json"):
            try:
                with open(f) as fp:
                    data = json.load(fp)
                ts = data.get("timestamp", "")
                spend = data.get("decree", {}).get("spend_authorized", 0.0)
                if ts.startswith(today):
                    today_spend += spend
                if ts.startswith(month):
                    mtd_spend += spend
            except Exception:
                pass

    return {"today": today_spend, "mtd": mtd_spend}

def collect_alerts(agents: dict, storage: dict) -> list:
    """Compile alert list."""
    alerts = []

    # Silent agents
    if agents["silent"]:
        alerts.append(f"{len(agents['silent'])} agent(s) silent >24h: {', '.join(agents['silent'][:3])}")

    # Storage warnings
    for label, pct_str in storage.items():
        try:
            pct = float(pct_str.replace("%", ""))
            if pct > 85:
                alerts.append(f"{label} storage at {pct_str} — critical")
            elif pct > 70:
                alerts.append(f"{label} storage at {pct_str} — warning")
        except Exception:
            pass

    # Check switchboard log for dead letters
    sb_log = LOG_DIR / "switchboard.log"
    if sb_log.exists():
        try:
            lines = sb_log.read_text().splitlines()[-50:]
            dead = sum(1 for l in lines if "Dead-letter" in l)
            if dead > 5:
                alerts.append(f"{dead} dead-letter messages in Switchboard log")
        except Exception:
            pass

    return alerts

def collect_manufacturing() -> str:
    """Check if anything is printing (placeholder — expand when OctoPrint added)."""
    return "idle"

def collect_backup() -> str:
    """Check backup status (placeholder — expand when backup agent added)."""
    return "not configured"

def collect_birds() -> str:
    """Bird safety check — placeholder."""
    return "CLEAR"

def generate_summary(briefing_data: dict) -> str:
    """Use local Llama to generate a one-line summary of alerts."""
    if not briefing_data["alerts"]:
        return "All systems nominal."

    prompt = (
        f"You are the Hive Nurse. Write ONE short sentence summarizing these alerts "
        f"for the morning briefing: {', '.join(briefing_data['alerts'])}. "
        f"Be direct and calm."
    )

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 60, "temperature": 0.3}
    }).encode()

    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("response", "").strip()
    except Exception as e:
        return f"Summary unavailable: {e}"

def format_briefing(data: dict) -> str:
    """Format the morning briefing message."""
    date_str  = now_ct().strftime("%A, %B %d %Y")
    agents    = data["agents"]
    storage   = data["storage"]
    spend     = data["spend"]
    alerts    = data["alerts"]
    mfg       = data["manufacturing"]
    backup    = data["backup"]
    birds     = data["birds"]
    summary   = data["summary"]

    alert_str = "\n".join(f"  • {a}" for a in alerts) if alerts else "  None"

    msg = (
        f"🐝 GOOD MORNING JOSHUA — {date_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 AGENTS: {agents['count']}/{agents['total']} active\n"
        f"💰 API SPEND: ${spend['today']:.2f} today / ${spend['mtd']:.2f} MTD\n"
        f"💾 STORAGE: SSD {storage.get('SSD','N/A')} | HDD {storage.get('HDD','N/A')}\n"
        f"🖨️  MANUFACTURING: {mfg}\n"
        f"🔐 BACKUP: {backup}\n"
        f"🌿 BIRDS: {birds}\n"
        f"⚠️  ALERTS:\n{alert_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 {summary}"
    )
    return msg

def send_telegram(message: str) -> bool:
    """Send message via Telegram bot."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }).encode()

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

def write_memory(data: dict, sent: bool):
    """Log briefing to MEMORY.md."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n## {now_ct().strftime('%Y-%m-%d %H:%M CT')}\n"
        f"- **Agents active:** {data['agents']['count']}/{data['agents']['total']}\n"
        f"- **API spend today:** ${data['spend']['today']:.2f}\n"
        f"- **Alerts:** {len(data['alerts'])}\n"
        f"- **Telegram sent:** {'yes' if sent else 'no'}\n"
    )
    with open(MEMORY_FILE, "a") as f:
        f.write(entry)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Nurse — Hive morning briefing")
    parser.add_argument("--test", action="store_true", help="Send test briefing now without cron")
    args = parser.parse_args()

    load_env()

    print("🏥 NURSE — Morning Briefing Agent")
    print("=" * 45)

    # Collect all data
    print("Collecting agent status...")
    agents = collect_agent_status()

    print("Collecting storage...")
    storage = collect_storage()

    print("Collecting API spend...")
    spend = collect_api_spend()

    mfg    = collect_manufacturing()
    backup = collect_backup()
    birds  = collect_birds()
    alerts = collect_alerts(agents, storage)

    print("Generating summary via Llama...")
    briefing_data = {
        "agents": agents, "storage": storage, "spend": spend,
        "manufacturing": mfg, "backup": backup, "birds": birds,
        "alerts": alerts
    }
    summary = generate_summary(briefing_data)
    briefing_data["summary"] = summary

    # Format and send
    message = format_briefing(briefing_data)
    print("\n" + message)
    print("\nSending to Telegram...")

    sent = send_telegram(message)
    if sent:
        print("✅ Briefing sent successfully")
    else:
        print("❌ Telegram send failed")

    write_memory(briefing_data, sent)
    print(f"📝 Logged to {MEMORY_FILE}")

if __name__ == "__main__":
    main()
