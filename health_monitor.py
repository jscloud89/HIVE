#!/usr/bin/env python3
"""
health_monitor.py — HIVE Agent Health Monitor (Warden)
Heartbeat checks on all active agents. Alerts on failure.
Documents failover protocol for each agent.
Audits dormant agent states.

Schedule: Run every 15 minutes
  */15 * * * * cd /home/beekeeper/HIVE/workspace-warden && python3 health_monitor.py --silent

Usage:
  python3 health_monitor.py           # full health check + Telegram report
  python3 health_monitor.py --silent  # check only, no Telegram unless alerts
  python3 health_monitor.py --status  # show last health report
  python3 health_monitor.py --audit   # full agent audit
"""

import argparse
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE    = Path(__file__).parent
PHASE1_DIR   = Path.home() / "hive-phase1"
DATA_DIR     = PHASE1_DIR / "data" / "warden"
MEMORY_FILE  = WORKSPACE / "MEMORY.md"
HEALTH_FILE  = DATA_DIR / "last_health.json"
ALERT_FILE   = DATA_DIR / "active_alerts.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Agent definitions ─────────────────────────────────────
AGENTS = {
    # Systemd services
    "hive-chancellor": {
        "type": "systemd",
        "service": "hive-chancellor",
        "check": "docker",
        "container": "hive-chancellor",
        "critical": True,
        "failover": "cd ~/hive-phase1 && docker compose up -d chancellor",
        "description": "FastAPI — serves /hive-status, /agent/queen/chat"
    },
    "hive-mosquitto": {
        "type": "docker",
        "container": "hive-mosquitto",
        "critical": True,
        "failover": "cd ~/hive-phase1 && docker compose up -d mosquitto",
        "description": "MQTT broker — agent communication backbone"
    },
    "hive-switchboard": {
        "type": "systemd",
        "service": "hive-switchboard",
        "critical": True,
        "failover": "sudo systemctl restart hive-switchboard",
        "description": "MQTT signal router"
    },
    "hive-treasurer": {
        "type": "systemd",
        "service": "hive-treasurer",
        "critical": True,
        "failover": "sudo systemctl restart hive-treasurer",
        "description": "Margin calc agent, GO/NO-GO verdicts"
    },
    "hive-foreman": {
        "type": "systemd",
        "service": "hive-foreman",
        "critical": False,
        "failover": "sudo systemctl restart hive-foreman",
        "description": "A1 Mini MQTT monitor"
    },
    "hive-web": {
        "type": "systemd",
        "service": "hive-web",
        "critical": True,
        "failover": "sudo systemctl restart hive-web",
        "description": "Python HTTP server :8080 — serves ~/HIVE/"
    },
    "hive-listener": {
        "type": "systemd",
        "service": "hive-listener",
        "critical": True,
        "failover": "sudo systemctl restart hive-listener",
        "description": "Telegram command handler"
    },
    "nut-ups": {
        "type": "systemd",
        "service": "nut-driver@hive-ups",
        "critical": False,
        "failover": "sudo systemctl restart nut-driver@hive-ups",
        "description": "UPS monitoring"
    },
    # HTTP endpoints
    "chancellor-api": {
        "type": "http",
        "url": "http://localhost:8001/hive-status",
        "critical": True,
        "failover": "cd ~/hive-phase1 && docker compose restart chancellor",
        "description": "Chancellor API endpoint"
    },
    "web-server": {
        "type": "http",
        "url": "http://localhost:8080/",
        "critical": True,
        "failover": "sudo systemctl restart hive-web",
        "description": "Web server HTTP endpoint"
    },
    # MQTT
    "mqtt-broker": {
        "type": "port",
        "host": "localhost",
        "port": 1883,
        "critical": True,
        "failover": "cd ~/hive-phase1 && docker compose restart mosquitto",
        "description": "MQTT broker port 1883"
    },
    # Printer
    "a1-mini": {
        "type": "ping",
        "host": "192.168.50.30",
        "critical": False,
        "failover": "Check printer power and network connection",
        "description": "A1 Mini 3D printer"
    },
}

# ── Cron jobs to verify ──────────────────────────────────
CRONS = {
    "nurse-briefing":  "0 11 * * *",
    "war-room":        "0 14 * * *",
    "forager":         "0 */4 * * *",
    "market-scout":    "0 13 * * *",
}

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

def load_alerts():
    if ALERT_FILE.exists():
        return json.loads(ALERT_FILE.read_text())
    return {}

def save_alerts(alerts):
    ALERT_FILE.write_text(json.dumps(alerts, indent=2))

# ── Health checks ─────────────────────────────────────────
def check_systemd(service_name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()
        return status == "active", status
    except Exception as e:
        return False, str(e)

def check_docker(container_name):
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
            capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()
        return status == "running", status
    except Exception as e:
        return False, str(e)

def check_http(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HIVE-Warden/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:50]

def check_port(host, port, timeout=3):
    import socket
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, f"port {port} open"
    except Exception as e:
        return False, str(e)[:50]

def check_ping(host, timeout=3):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            capture_output=True, text=True, timeout=timeout+2
        )
        return result.returncode == 0, "reachable" if result.returncode == 0 else "unreachable"
    except Exception as e:
        return False, str(e)[:50]

def check_agent(agent_id, config):
    agent_type = config["type"]
    start = time.time()

    if agent_type == "systemd":
        ok, status = check_systemd(config["service"])
    elif agent_type == "docker":
        ok, status = check_docker(config["container"])
    elif agent_type == "http":
        ok, status = check_http(config["url"])
    elif agent_type == "port":
        ok, status = check_port(config["host"], config["port"])
    elif agent_type == "ping":
        ok, status = check_ping(config["host"])
    else:
        ok, status = False, "unknown check type"

    latency = round((time.time() - start) * 1000)

    return {
        "agent_id": agent_id,
        "ok": ok,
        "status": status,
        "latency_ms": latency,
        "critical": config.get("critical", False),
        "description": config.get("description", ""),
        "failover": config.get("failover", ""),
        "timestamp": now_iso()
    }

# ── Cron verification ─────────────────────────────────────
def verify_crons():
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=5
        )
        crontab = result.stdout
        cron_status = {}
        for name, schedule in CRONS.items():
            cron_status[name] = schedule in crontab
        return cron_status
    except:
        return {}

# ── Disk + memory check ───────────────────────────────────
def check_system_resources():
    resources = {}
    try:
        # Disk usage
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            resources["disk_used"] = parts[2]
            resources["disk_avail"] = parts[3]
            resources["disk_pct"] = parts[4]
    except:
        pass

    try:
        # Memory
        result = subprocess.run(
            ["free", "-h"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            resources["mem_total"] = parts[1]
            resources["mem_used"] = parts[2]
            resources["mem_free"] = parts[3]
    except:
        pass

    try:
        # Load average
        with open('/proc/loadavg') as f:
            load = f.read().split()[:3]
            resources["load_avg"] = f"{load[0]} {load[1]} {load[2]}"
    except:
        pass

    return resources

# ── Main health check ─────────────────────────────────────
def run_health_check(silent=False, alert_only=False):
    print(f"\n{'='*55}")
    print(f"  🛡️  WARDEN — Agent Health Monitor")
    print(f"  {now_ct()}")
    print(f"{'='*55}\n")

    results = {}
    failed = []
    warnings = []
    previous_alerts = load_alerts()

    # Check all agents
    for agent_id, config in AGENTS.items():
        result = check_agent(agent_id, config)
        results[agent_id] = result

        status_icon = "✅" if result["ok"] else ("❌" if result["critical"] else "⚠️")
        print(f"  {status_icon} {agent_id:<25} {result['status']:<15} {result['latency_ms']}ms")

        if not result["ok"]:
            if result["critical"]:
                failed.append(result)
            else:
                warnings.append(result)

    # Check crons
    print(f"\n  📅 Cron Jobs:")
    cron_status = verify_crons()
    for name, active in cron_status.items():
        icon = "✅" if active else "❌"
        print(f"  {icon} {name}")

    # System resources
    print(f"\n  💻 System Resources:")
    resources = check_system_resources()
    for k, v in resources.items():
        print(f"  {k}: {v}")

    # Build health report
    health_report = {
        "timestamp": now_iso(),
        "agents": results,
        "failed_count": len(failed),
        "warning_count": len(warnings),
        "crons": cron_status,
        "resources": resources,
        "overall": "healthy" if not failed else "degraded" if len(failed) < 3 else "critical"
    }

    HEALTH_FILE.write_text(json.dumps(health_report, indent=2))

    # Determine new alerts (not in previous)
    new_alerts = []
    for f in failed:
        if f["agent_id"] not in previous_alerts:
            new_alerts.append(f)

    # Recovered alerts
    recovered = []
    for agent_id in previous_alerts:
        if agent_id in results and results[agent_id]["ok"]:
            recovered.append(agent_id)

    # Update alert state
    current_alerts = {f["agent_id"]: f for f in failed}
    save_alerts(current_alerts)

    # Send Telegram
    send_now = not silent or new_alerts or recovered

    if send_now:
        overall_emoji = "✅" if not failed else "⚠️" if warnings and not failed else "❌"
        lines = [
            f"🛡️ <b>Warden Health Report</b>",
            f"<i>{now_ct()}</i>",
            f"{overall_emoji} Status: {health_report['overall'].upper()}",
            ""
        ]

        if failed:
            lines.append("❌ <b>FAILED (Critical):</b>")
            for f in failed:
                lines.append(f"  • {f['agent_id']}: {f['status']}")
                lines.append(f"    Fix: <code>{f['failover']}</code>")

        if warnings:
            lines.append("⚠️ <b>Warnings:</b>")
            for w in warnings:
                lines.append(f"  • {w['agent_id']}: {w['status']}")

        if new_alerts:
            lines.append(f"\n🚨 <b>{len(new_alerts)} NEW FAILURE(S)</b>")

        if recovered:
            lines.append(f"\n💚 Recovered: {', '.join(recovered)}")

        # Summary stats
        total = len(results)
        ok_count = sum(1 for r in results.values() if r["ok"])
        lines += [
            "",
            f"📊 {ok_count}/{total} agents healthy",
        ]
        if resources:
            lines.append(f"💾 Disk: {resources.get('disk_pct','?')} used | Mem: {resources.get('mem_used','?')}/{resources.get('mem_total','?')}")
            lines.append(f"⚡ Load: {resources.get('load_avg','?')}")

        send_telegram("\n".join(lines))

    if new_alerts:
        update_memory(f"ALERT: {len(new_alerts)} agents failed — {[a['agent_id'] for a in new_alerts]}")
        print(f"\n  🚨 {len(new_alerts)} new alert(s) — Telegram sent")
    elif recovered:
        update_memory(f"RECOVERED: {recovered}")
        print(f"\n  💚 {len(recovered)} agent(s) recovered")

    print(f"\n  Overall: {health_report['overall'].upper()}")
    print(f"  {ok_count}/{total} healthy | {len(failed)} failed | {len(warnings)} warnings")
    print(f"\n✅ Warden check complete — {now_ct()}")

    return health_report

def show_status():
    if not HEALTH_FILE.exists():
        print("No health report yet. Run health_monitor.py first.")
        return
    report = json.loads(HEALTH_FILE.read_text())
    print(f"\nLast check: {report['timestamp']}")
    print(f"Overall: {report['overall'].upper()}")
    print(f"Failed: {report['failed_count']} | Warnings: {report['warning_count']}")
    print()
    for agent_id, r in report["agents"].items():
        icon = "✅" if r["ok"] else "❌"
        print(f"  {icon} {agent_id:<25} {r['status']}")

def full_audit():
    print(f"\n⬡ WARDEN FULL AGENT AUDIT — {now_ct()}\n")
    print(f"{'Agent':<25} {'Type':<10} {'Critical':<10} {'Description'}")
    print("─" * 80)
    for agent_id, config in AGENTS.items():
        critical = "YES" if config.get("critical") else "no"
        print(f"{agent_id:<25} {config['type']:<10} {critical:<10} {config.get('description','')[:40]}")

    print(f"\n{'─'*80}")
    print(f"Total agents monitored: {len(AGENTS)}")
    print(f"Critical agents: {sum(1 for a in AGENTS.values() if a.get('critical'))}")
    print(f"\nCron jobs:")
    for name, schedule in CRONS.items():
        print(f"  {name}: {schedule}")

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Warden — Agent Health Monitor")
    parser.add_argument("--silent",     action="store_true", help="Only Telegram on alerts")
    parser.add_argument("--status",     action="store_true", help="Show last report")
    parser.add_argument("--audit",      action="store_true", help="Full agent audit")
    parser.add_argument("--alert-only", action="store_true", help="Only send Telegram if failures")
    args = parser.parse_args()

    load_env()

    if args.status:
        show_status()
    elif args.audit:
        full_audit()
    else:
        run_health_check(
            silent=args.silent,
            alert_only=args.alert_only
        )
