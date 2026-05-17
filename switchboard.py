#!/usr/bin/env python3
"""
switchboard.py — The Hive's Internal Signal Router
workspace-switchboard · Runs continuously as a daemon
Usage: python3 switchboard.py [--once]
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

# ── Paths ────────────────────────────────────────────────────
WORKSPACE   = Path(__file__).parent
HIVE_ROOT   = WORKSPACE.parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data"
LOG_DIR     = DATA_DIR / "logs"
MEMORY_FILE = WORKSPACE / "MEMORY.md"

# ── Config ───────────────────────────────────────────────────
MQTT_HOST        = os.environ.get("MOSQUITTO_HOST", "localhost")
MQTT_PORT        = int(os.environ.get("MOSQUITTO_PORT", 1883))
HEARTBEAT_TTL    = 300   # 5 minutes — agent considered silent after this
STATUS_INTERVAL  = 60    # publish hive/status every 60 seconds
POLL_INTERVAL    = 30    # main loop poll interval

KNOWN_AGENTS = [
    "architect", "auditor", "bard", "chancellor", "concierge",
    "engineer", "forager", "foreman", "inspector", "nurse",
    "quartermaster", "queen", "scout", "supervisor", "switchboard",
    "treasurer", "warden", "worker"
]

VALID_SUFFIXES  = {"inbox", "outbox", "heartbeat"}
PROTECTED_TOPICS = {"hive/decree"}  # read-only — never publish here

# ── Logging ──────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SWITCHBOARD] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "switchboard.log")
    ]
)
log = logging.getLogger("switchboard")

# ── State ────────────────────────────────────────────────────
heartbeats   = {}   # agent_name -> last_seen timestamp
dead_letters = 0
running      = True

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def now_iso() -> str:
    return now_utc().isoformat()

def load_env():
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

def write_anomaly(topic: str, sender: str, issue: str, action: str):
    """Log routing anomaly to MEMORY.md."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n## {now_utc().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"- **Topic:** {topic}\n"
        f"- **Sender:** {sender}\n"
        f"- **Issue:** {issue}\n"
        f"- **Action:** {action}\n"
    )
    with open(MEMORY_FILE, "a") as f:
        f.write(entry)

def parse_topic(topic: str):
    """
    Parse topic into (agent_name, suffix) or return (None, None).
    Valid: hive/agent/{name}/{inbox|outbox|heartbeat}
    """
    parts = topic.split("/")
    if len(parts) == 4 and parts[0] == "hive" and parts[1] == "agent":
        return parts[2], parts[3]
    return None, None

def validate_message(topic: str, payload: bytes) -> tuple[bool, str]:
    """Validate message — returns (valid, reason)."""
    agent, suffix = parse_topic(topic)

    # Must match namespace
    if agent is None:
        if topic not in ("hive/status", "hive/deadletter", "hive/decree"):
            return False, f"Unknown topic namespace: {topic}"
        return True, "ok"

    # Agent must be known
    if agent not in KNOWN_AGENTS:
        return False, f"Unknown agent: {agent}"

    # Suffix must be valid
    if suffix not in VALID_SUFFIXES:
        return False, f"Invalid topic suffix: {suffix}"

    # Payload must be valid JSON
    try:
        json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return False, f"Malformed payload: {e}"

    return True, "ok"

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info(f"Connected to Mosquitto at {MQTT_HOST}:{MQTT_PORT}")
        # Subscribe to all agent topics and system topics
        client.subscribe("hive/#", qos=1)
        log.info("Subscribed to hive/#")
    else:
        log.error(f"Connection failed — rc={rc}")

def on_message(client, userdata, msg):
    global dead_letters
    topic   = msg.topic
    payload = msg.payload

    # Skip our own status publishes
    if topic in ("hive/status",):
        return

    agent, suffix = parse_topic(topic)

    # Track heartbeats
    if suffix == "heartbeat" and agent in KNOWN_AGENTS:
        heartbeats[agent] = now_utc()
        log.debug(f"Heartbeat from {agent}")
        return

    # Validate
    valid, reason = validate_message(topic, payload)
    if not valid:
        dead_letters += 1
        log.warning(f"Dead-letter [{topic}]: {reason}")
        dead_payload = json.dumps({
            "timestamp": now_iso(),
            "original_topic": topic,
            "reason": reason,
            "payload_preview": payload.decode("utf-8", errors="replace")[:200]
        })
        client.publish("hive/deadletter", dead_payload, qos=1)
        write_anomaly(topic, agent or "unknown", reason, "dead-lettered")
        return

    # Route outbox → inbox
    if suffix == "outbox" and agent:
        try:
            data = json.loads(payload.decode())
            destination = data.get("to")
            if destination and destination in KNOWN_AGENTS:
                inbox_topic = f"hive/agent/{destination}/inbox"
                client.publish(inbox_topic, payload, qos=1)
                log.info(f"Routed {agent} → {destination}")
            else:
                dead_letters += 1
                reason = f"Missing or unknown 'to' field: {destination}"
                log.warning(f"Dead-letter [{topic}]: {reason}")
                dead_payload = json.dumps({
                    "timestamp": now_iso(),
                    "original_topic": topic,
                    "reason": reason
                })
                client.publish("hive/deadletter", dead_payload, qos=1)
                write_anomaly(topic, agent, reason, "dead-lettered")
        except Exception as e:
            log.error(f"Routing error on {topic}: {e}")

def publish_status(client):
    """Publish aggregated hive status to hive/status."""
    now = now_utc()
    agents_online  = []
    agents_silent  = []

    for agent in KNOWN_AGENTS:
        if agent == "switchboard":
            agents_online.append(agent)
            continue
        last = heartbeats.get(agent)
        if last and (now - last).total_seconds() < HEARTBEAT_TTL:
            agents_online.append(agent)
        else:
            agents_silent.append(agent)

    status = {
        "timestamp":     now_iso(),
        "agents_online": agents_online,
        "agents_silent": agents_silent,
        "dead_letters":  dead_letters,
        "uptime_check":  now.strftime("%Y-%m-%d %H:%M UTC")
    }

    client.publish("hive/status", json.dumps(status), qos=1, retain=True)
    log.info(f"Status published — online: {len(agents_online)}, silent: {len(agents_silent)}, dead_letters: {dead_letters}")

    # Alert if any agent silent > TTL (excluding those never seen)
    for agent in agents_silent:
        if agent in heartbeats:
            log.warning(f"Agent {agent} has been silent > {HEARTBEAT_TTL//60} minutes")

def handle_signal(sig, frame):
    global running
    log.info(f"Signal {sig} received — shutting down")
    running = False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Switchboard — Hive MQTT router")
    parser.add_argument("--once", action="store_true", help="Publish one status update and exit")
    args = parser.parse_args()

    load_env()

    log.info("🔌 SWITCHBOARD starting")
    log.info(f"   MQTT: {MQTT_HOST}:{MQTT_PORT}")
    log.info(f"   Known agents: {len(KNOWN_AGENTS)}")

    signal.signal(signal.SIGINT,  handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="switchboard")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except Exception as e:
        log.error(f"Cannot connect to Mosquitto: {e}")
        sys.exit(1)

    client.loop_start()
    time.sleep(2)  # Allow connection to establish

    if args.once:
        publish_status(client)
        time.sleep(1)
        client.loop_stop()
        client.disconnect()
        log.info("One-shot complete")
        return

    last_status = time.time()

    log.info("Switchboard running — press Ctrl+C to stop")
    while running:
        now = time.time()
        if now - last_status >= STATUS_INTERVAL:
            publish_status(client)
            last_status = now
        time.sleep(POLL_INTERVAL)

    client.loop_stop()
    client.disconnect()
    log.info("Switchboard stopped cleanly")

if __name__ == "__main__":
    main()
