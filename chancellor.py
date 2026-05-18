from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
import json, os, glob
from pathlib import Path

app = FastAPI()

# Allow dashboard to fetch from browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DATA        = Path(os.path.expanduser("~/hive-phase1/data"))
HIVE_ROOT   = Path(os.path.expanduser("~/HIVE"))
JOBS_DIR    = DATA / "auditor" / "jobs"
WAGGLE_DIR  = DATA / "waggle"
LISTINGS_DIR = DATA / "listings"
QUEUE_FILE  = DATA / "research-queue.json"

KNOWN_AGENTS = [
    "architect", "auditor", "bard", "chancellor", "concierge",
    "engineer", "forager", "foreman", "inspector", "nurse",
    "quartermaster", "queen", "scout", "supervisor", "switchboard",
    "treasurer", "warden", "worker"
]

HONEY_SPLIT = {"tax": 0.25, "venture": 0.20, "reinvest": 0.10, "profit": 0.37, "chancellor": 0.08}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ── Data readers ──────────────────────────────────────────────

def read_auditor_jobs() -> list:
    if not JOBS_DIR.exists():
        return []
    jobs = []
    for f in sorted(JOBS_DIR.glob("*.json")):
        try:
            jobs.append(json.loads(f.read_text()))
        except Exception:
            pass
    return jobs

def read_latest_waggle() -> dict:
    if not WAGGLE_DIR.exists():
        return {}
    # Only real waggle files, not decrees
    waggles = [f for f in WAGGLE_DIR.glob("*.json")
                if not f.name.startswith("decree-") and f.name != "test-waggle.json"]
    if not waggles:
        return {}
    latest = max(waggles, key=lambda f: f.stat().st_mtime)
    try:
        return json.loads(latest.read_text())
    except Exception:
        return {}

def read_latest_decree() -> dict:
    if not WAGGLE_DIR.exists():
        return {}
    decrees = list(WAGGLE_DIR.glob("decree-*.json"))
    if not decrees:
        return {}
    latest = max(decrees, key=lambda f: f.stat().st_mtime)
    try:
        return json.loads(latest.read_text())
    except Exception:
        return {}

def read_agent_status() -> dict:
    now    = datetime.now(timezone.utc)
    online = []
    silent = []
    for agent in KNOWN_AGENTS:
        memory = HIVE_ROOT / f"workspace-{agent}" / "MEMORY.md"
        if memory.exists():
            import time
            age = now.timestamp() - memory.stat().st_mtime
            if age < 86400:  # 24 hours
                online.append(agent)
            else:
                silent.append(agent)
        else:
            silent.append(agent)
    return {"online": online, "silent": silent,
            "online_count": len(online), "total": len(KNOWN_AGENTS)}

def read_storage() -> dict:
    import shutil
    result = {}
    for label, path in [("SSD", "/"), ("HDD", "/mnt/hive-storage")]:
        try:
            u = shutil.disk_usage(path)
            result[label] = {
                "used_pct": round(u.used / u.total * 100, 1),
                "free_gb":  round(u.free / 1e9, 1),
                "total_gb": round(u.total / 1e9, 1)
            }
        except Exception:
            result[label] = {"used_pct": 0, "free_gb": 0, "total_gb": 0}
    return result

def read_queue() -> dict:
    if not QUEUE_FILE.exists():
        return {"pending": 0, "total": 0}
    try:
        q = json.loads(QUEUE_FILE.read_text())
        pending = sum(1 for t in q if t.get("status") == "pending")
        return {"pending": pending, "total": len(q)}
    except Exception:
        return {"pending": 0, "total": 0}

def read_activity_feed() -> list:
    """Build activity feed from MEMORY.md files across all agents."""
    events = []
    for agent in KNOWN_AGENTS:
        memory = HIVE_ROOT / f"workspace-{agent}" / "MEMORY.md"
        if memory.exists():
            try:
                lines = memory.read_text().splitlines()
                for line in lines:
                    if line.startswith("## "):
                        events.append({
                            "agent": agent,
                            "text": f"{agent.capitalize()}: {line[3:].strip()}",
                            "raw":  line[3:].strip()
                        })
            except Exception:
                pass
    return events[-20:]  # last 20 events

# ── Endpoints ─────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "online", "agent": "chancellor",
            "timestamp": now_iso()}

@app.get("/summary")
def summary():
    jobs = read_auditor_jobs()
    gross  = sum(j["revenue"]["gross_revenue"] for j in jobs)
    net    = sum(j["net_profit"] for j in jobs)
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_jobs = [j for j in jobs if j["timestamp"].startswith(today)]
    today_rev  = sum(j["revenue"]["gross_revenue"] for j in today_jobs)

    return {
        "status":              "online",
        "total_gross_revenue": round(gross, 2),
        "total_net_profit":    round(net, 2),
        "revenue_today":       round(today_rev, 2),
        "tax_reserve_balance": round(net * HONEY_SPLIT["tax"], 2),
        "venture_fund":        round(net * HONEY_SPLIT["venture"], 2),
        "pending_decrees":     0,
        "jobs_completed":      len(jobs)
    }

@app.get("/hive-status")
def hive_status():
    """Master status endpoint — feeds the dashboard."""
    jobs    = read_auditor_jobs()
    waggle  = read_latest_waggle()
    decree  = read_latest_decree()
    agents  = read_agent_status()
    storage = read_storage()
    queue   = read_queue()
    feed    = read_activity_feed()

    # Financial summary
    gross      = sum(j["revenue"]["gross_revenue"] for j in jobs)
    net        = sum(j["net_profit"] for j in jobs)
    today      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month      = datetime.now(timezone.utc).strftime("%Y-%m")
    today_jobs = [j for j in jobs if j["timestamp"].startswith(today)]
    month_jobs = [j for j in jobs if j["timestamp"].startswith(month)]
    today_rev  = sum(j["revenue"]["gross_revenue"] for j in today_jobs)
    month_rev  = sum(j["revenue"]["gross_revenue"] for j in month_jobs)

    # Recovery progress
    recovery_pct = min(round(net / 2000 * 100, 1), 100)

    # Latest waggle signal
    market_signal = {
        "niche":       waggle.get("niche", "No data yet"),
        "vigor":       waggle.get("vigor", 0),
        "direction":   waggle.get("direction", "—"),
        "action":      waggle.get("recommended_action", "—"),
        "mhr_target":  6.57
    }

    # Latest decree
    decree_info = {}
    if decree:
        d = decree.get("decree", decree)
        if isinstance(d, dict):
            decree_info = {
                "decision":       d.get("decree", "—"),
                "reasoning":      d.get("reasoning", ""),
                "worker":         d.get("assigned_worker", "—"),
                "spend":          d.get("spend_authorized", 0),
                "model_rec":      d.get("model_recommendation", "—")
            }

    # Honey split
    honey = {
        "tax":        round(net * HONEY_SPLIT["tax"], 2),
        "venture":    round(net * HONEY_SPLIT["venture"], 2),
        "reinvest":   round(net * HONEY_SPLIT["reinvest"], 2),
        "profit":     round(net * HONEY_SPLIT["profit"], 2),
        "chancellor": round(net * HONEY_SPLIT["chancellor"], 2)
    }

    return {
        "timestamp":   now_iso(),
        "financial": {
            "revenue_today":   round(today_rev, 2),
            "revenue_mtd":     round(month_rev, 2),
            "gross_all_time":  round(gross, 2),
            "net_profit":      round(net, 2),
            "recovery_usd":    round(net, 2),
            "recovery_target": 2000.00,
            "recovery_pct":    recovery_pct,
            "honey_split":     honey
        },
        "agents":      agents,
        "market":      market_signal,
        "decree":      decree_info,
        "storage":     storage,
        "queue":       queue,
        "activity":    feed,
        "system": {
            "chancellor": "online",
            "mosquitto":  "online",
            "switchboard": "online",
            "netdata":    "online"
        }
    }

@app.get("/recovery")
def recovery():
    """Simple $2,000 recovery counter."""
    jobs = read_auditor_jobs()
    net  = sum(j["net_profit"] for j in jobs)
    pct  = min(round(net / 2000 * 100, 1), 100)
    return {
        "recovered":  round(net, 2),
        "target":     2000.00,
        "remaining":  round(2000 - net, 2),
        "percent":    pct,
        "jobs":       len(jobs)
    }
