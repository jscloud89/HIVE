#!/usr/bin/env python3
"""
optimizer.py — HIVE Optimizer Agent
Monthly self-improvement system. Reviews all agents, checks for better/newer models,
benchmarks performance, drafts upgrade recommendations, and executes approved changes.

Schedule: Run on 1st of each month at 10am CT (15:00 UTC)
  0 15 1 * * cd /home/beekeeper/HIVE/workspace-optimizer && python3 optimizer.py

Usage:
  python3 optimizer.py              # full monthly review
  python3 optimizer.py --scan       # scan only, no changes
  python3 optimizer.py --apply      # apply pending approved upgrades
  python3 optimizer.py --status     # show current model inventory
  python3 optimizer.py --benchmark  # run cost/speed benchmarks
"""

import argparse
import json
import os
import re
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE     = Path(__file__).parent
PHASE1_DIR    = Path.home() / "hive-phase1"
HIVE_ROOT     = Path.home() / "HIVE"
DATA_DIR      = PHASE1_DIR / "data" / "optimizer"
MEMORY_FILE   = WORKSPACE / "MEMORY.md"
PENDING_FILE  = WORKSPACE / "pending_upgrades.json"
HISTORY_FILE  = WORKSPACE / "upgrade_history.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Agent registry ────────────────────────────────────────
# All agents, their files, and current models
AGENT_REGISTRY = {
    "queen": {
        "files": ["workspace-queen/queen.py"],
        "soul":  "workspace-queen/SOUL.md",
        "current_model": "anthropic/claude-opus-4-6",
        "role": "Strategic decisions, Royal Decrees",
        "quality_tier": "highest",   # never downgrade
        "cost_sensitivity": "low",
    },
    "scout": {
        "files": ["workspace-scout/scout.py"],
        "soul":  "workspace-scout/SOUL.md",
        "current_model": "anthropic/claude-sonnet-4-6",
        "role": "Market research, waggle dance",
        "quality_tier": "high",
        "cost_sensitivity": "medium",
    },
    "bard": {
        "files": ["workspace-bard/bard.py", "workspace-worker/worker.py"],
        "soul":  "workspace-bard/SOUL.md",
        "current_model": "anthropic/claude-sonnet-4-6",
        "role": "Creative direction, listing copy, prompts",
        "quality_tier": "high",
        "cost_sensitivity": "medium",
    },
    "foreman": {
        "files": ["workspace-foreman/foreman.py"],
        "current_model": "none",  # uses MQTT, no LLM
        "role": "A1 Mini monitoring",
        "quality_tier": "none",
        "cost_sensitivity": "none",
    },
    "treasurer": {
        "files": ["workspace-treasurer/treasurer.py"],
        "current_model": "google/gemini-2.5-flash-lite",
        "role": "Margin calculations, GO/NO-GO",
        "quality_tier": "medium",
        "cost_sensitivity": "high",
    },
    "auditor": {
        "files": ["workspace-auditor/auditor.py"],
        "current_model": "google/gemini-2.5-flash-lite",
        "role": "Financial record keeping",
        "quality_tier": "medium",
        "cost_sensitivity": "high",
    },
    "engineer": {
        "files": ["workspace-engineer/engineer.py"],
        "current_model": "anthropic/claude-sonnet-4-6",
        "role": "3D design generation, SCAD",
        "quality_tier": "high",
        "cost_sensitivity": "medium",
    },
    "architect": {
        "files": ["workspace-architect/architect.py"],
        "current_model": "anthropic/claude-sonnet-4-6",
        "role": "Notion templates, digital assets",
        "quality_tier": "high",
        "cost_sensitivity": "medium",
    },
    "worker": {
        "files": ["workspace-worker/worker.py"],
        "current_model": "anthropic/claude-sonnet-4-6",
        "role": "POD listings, Printify",
        "quality_tier": "high",
        "cost_sensitivity": "medium",
    },
    "forager": {
        "files": ["workspace-forager/forager.py"],
        "current_model": "none",  # uses CoinGecko, no LLM
        "role": "Market price monitoring",
        "quality_tier": "none",
        "cost_sensitivity": "none",
    },
    "nurse": {
        "files": ["workspace-nurse/nurse.py"],
        "current_model": "google/gemini-2.5-flash-lite",
        "role": "Morning briefings",
        "quality_tier": "low",
        "cost_sensitivity": "high",
    },
    "warroom": {
        "files": ["workspace-warroom/warroom.py"],
        "current_model": "anthropic/claude-sonnet-4-6",
        "role": "Daily agent meetings",
        "quality_tier": "high",
        "cost_sensitivity": "medium",
    },
    "listing-agent": {
        "files": ["workspace-listing/listing_agent.py"],
        "current_model": "anthropic/claude-sonnet-4-6",
        "role": "eBay/Etsy listing creation",
        "quality_tier": "high",
        "cost_sensitivity": "medium",
    },
    "market-scout": {
        "files": ["workspace-scout/market_scout.py"],
        "current_model": "google/gemini-2.5-flash-lite",
        "role": "Competitor intelligence",
        "quality_tier": "medium",
        "cost_sensitivity": "high",
    },
    "warden": {
        "files": ["workspace-warden/health_monitor.py"],
        "current_model": "none",  # no LLM, system checks only
        "role": "Agent health monitoring",
        "quality_tier": "none",
        "cost_sensitivity": "none",
    },
}

# ── Model tiers (ordered best to newest) ─────────────────
MODEL_TIERS = {
    "anthropic": {
        "highest": [
            "anthropic/claude-opus-4-6",
            "anthropic/claude-opus-4",
        ],
        "high": [
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-sonnet-4",
        ],
        "medium": [
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-haiku-4",
        ],
        "low": [
            "anthropic/claude-haiku-4-5",
        ]
    },
    "google": {
        "highest": [
            "google/gemini-2.5-pro",
        ],
        "high": [
            "google/gemini-2.5-flash",
        ],
        "medium": [
            "google/gemini-2.5-flash-lite",
        ],
        "low": [
            "google/gemini-2.5-flash-lite",
        ]
    }
}

OPTIMIZER_SOUL = """You are the HIVE Optimizer — a meta-intelligence agent responsible for 
keeping the hive's AI agents running at peak performance and minimal cost.

You review agent performance data, model availability, and costs to recommend upgrades.
You are conservative — you never recommend downgrading quality for critical agents.
You are cost-aware — you actively seek cheaper models for routine tasks.
You document every change recommendation with clear reasoning.

Output ONLY valid JSON."""

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

def load_pending():
    if PENDING_FILE.exists():
        return json.loads(PENDING_FILE.read_text())
    return {}

def save_pending(data):
    PENDING_FILE.write_text(json.dumps(data, indent=2))

def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2))

# ── Fetch available models from OpenRouter ────────────────
def fetch_available_models():
    """Get current model list from OpenRouter."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            models = {}
            for m in data.get("data", []):
                mid = m.get("id", "")
                models[mid] = {
                    "name": m.get("name", mid),
                    "context_length": m.get("context_length", 0),
                    "pricing": m.get("pricing", {}),
                }
            print(f"  ✓ Found {len(models)} models on OpenRouter")
            return models
    except Exception as e:
        print(f"  ⚠️  OpenRouter models fetch failed: {e}")
        return {}

# ── Scan agent files for model strings ───────────────────
def scan_agent_files():
    """Find actual model strings in agent files."""
    model_pattern = re.compile(
        r'(?:MODEL|model|MODEL_\w+)\s*=\s*["\']([a-z0-9\-\/\.]+)["\']'
    )
    found = {}

    for agent_id, config in AGENT_REGISTRY.items():
        if config.get("current_model") == "none":
            continue

        agent_models = []
        for file_path in config.get("files", []):
            full_path = HIVE_ROOT / file_path
            if full_path.exists():
                content = full_path.read_text()
                matches = model_pattern.findall(content)
                for m in matches:
                    if "/" in m and m not in agent_models:
                        agent_models.append(m)

        if agent_models:
            found[agent_id] = {
                "detected_models": agent_models,
                "declared_model": config.get("current_model"),
                "files_scanned": config.get("files", [])
            }

    return found

# ── Benchmark a model ─────────────────────────────────────
def benchmark_model(model_id, task="simple"):
    """Quick benchmark — measure response time and quality."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")

    prompts = {
        "simple": "Reply with only: OK",
        "math":   "What is 15% of $24.99? Reply with only the dollar amount.",
        "creative": "Write a 10-word product title for a 3D printed card stand."
    }

    prompt = prompts.get(task, prompts["simple"])
    start = time.time()

    body = json.dumps({
        "model": model_id,
        "max_tokens": 50,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
            elapsed = round((time.time() - start) * 1000)
            response = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            return {
                "ok": True,
                "latency_ms": elapsed,
                "response": response[:50],
                "tokens_used": usage.get("total_tokens", 0),
                "model": model_id
            }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:100],
            "model": model_id
        }

# ── Generate upgrade recommendations ─────────────────────
def generate_recommendations(agent_scan, available_models):
    """Use Claude to analyze and recommend upgrades."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")

    # Build context
    agent_summary = []
    for agent_id, config in AGENT_REGISTRY.items():
        if config.get("quality_tier") == "none":
            continue
        agent_summary.append({
            "agent": agent_id,
            "role": config["role"],
            "current_model": config["current_model"],
            "quality_tier": config["quality_tier"],
            "cost_sensitivity": config["cost_sensitivity"],
            "detected_in_files": agent_scan.get(agent_id, {}).get("detected_models", [])
        })

    # Check for newer Claude models
    claude_models = [m for m in available_models if "anthropic/claude" in m]
    gemini_models = [m for m in available_models if "google/gemini" in m]

    prompt = f"""Review these HIVE agents and their current AI models.
Recommend upgrades where beneficial. Be conservative for critical agents.

CURRENT AGENTS:
{json.dumps(agent_summary, indent=2)}

AVAILABLE CLAUDE MODELS ON OPENROUTER:
{json.dumps(sorted(claude_models)[:15], indent=2)}

AVAILABLE GEMINI MODELS:
{json.dumps(sorted(gemini_models)[:10], indent=2)}

RULES:
- Queen always uses highest quality Claude (Opus) — never downgrade
- Cost-sensitive agents (treasurer, nurse, market-scout) should use cheapest capable model
- High quality agents (bard, engineer, scout) need Sonnet or better
- If a newer model version exists in same tier, recommend upgrade
- If a cheaper model can do the job equally well, recommend it
- Never recommend a model not in the available list

Return JSON:
{{
  "recommendations": [
    {{
      "agent": "agent_id",
      "current_model": "current",
      "recommended_model": "new_model",
      "reason": "why this upgrade/change",
      "impact": "performance|cost|both",
      "priority": "high|medium|low",
      "risk": "low|medium|high"
    }}
  ],
  "summary": "one paragraph summary of findings",
  "estimated_monthly_savings": "$X.XX"
}}

Only include agents where a change is genuinely recommended."""

    body = json.dumps({
        "model": "anthropic/claude-sonnet-4-6",
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": OPTIMIZER_SOUL},
            {"role": "user", "content": prompt}
        ]
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://hive.local",
            "X-Title": "HIVE Optimizer"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read().decode())
            response = data["choices"][0]["message"]["content"].strip()
            clean = re.sub(r'```json|```', '', response).strip()
            match = re.search(r'\{.*\}', clean, re.DOTALL)
            if match:
                return json.loads(match.group())
    except Exception as e:
        print(f"  ⚠️  Recommendation error: {e}")
    return None

# ── Apply an upgrade ──────────────────────────────────────
def apply_upgrade(agent_id, old_model, new_model):
    """Patch agent files to use the new model string."""
    config = AGENT_REGISTRY.get(agent_id, {})
    files_updated = []

    for file_path in config.get("files", []):
        full_path = HIVE_ROOT / file_path
        if not full_path.exists():
            continue

        content = full_path.read_text()
        # Replace model string
        updated = content.replace(f'"{old_model}"', f'"{new_model}"')
        updated = updated.replace(f"'{old_model}'", f"'{new_model}'")

        if updated != content:
            # Backup first
            backup = full_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d')}")
            backup.write_text(content)
            full_path.write_text(updated)
            files_updated.append(str(file_path))
            print(f"  ✅ Updated {file_path}: {old_model} → {new_model}")
        else:
            print(f"  ⚠️  No match found in {file_path}")

    return files_updated

# ── Main scan ─────────────────────────────────────────────
def run_scan(apply_pending=False):
    print(f"\n{'='*55}")
    print(f"  🔧 OPTIMIZER — Monthly Agent Review")
    print(f"  {now_ct()}")
    print(f"{'='*55}\n")

    # Step 1: Scan current agent files
    print("  📂 Scanning agent files...")
    agent_scan = scan_agent_files()
    print(f"  ✓ Scanned {len(agent_scan)} agents with models")

    # Step 2: Fetch available models
    print("\n  🌐 Fetching available models from OpenRouter...")
    available_models = fetch_available_models()

    # Step 3: Generate recommendations
    print("\n  🧠 Generating upgrade recommendations...")
    recommendations = generate_recommendations(agent_scan, available_models)

    if not recommendations:
        print("  ⚠️  Could not generate recommendations")
        send_telegram("⚙️ <b>Optimizer ran</b> but could not generate recommendations. Check logs.")
        return

    recs = recommendations.get("recommendations", [])
    summary = recommendations.get("summary", "")
    savings = recommendations.get("estimated_monthly_savings", "$0")

    print(f"\n  Found {len(recs)} recommendations:")
    for r in recs:
        print(f"  • {r['agent']}: {r['current_model']} → {r['recommended_model']}")
        print(f"    Reason: {r['reason'][:80]}")
        print(f"    Priority: {r['priority']} | Risk: {r['risk']}")

    # Step 4: Save pending upgrades for approval
    pending = {
        "generated": now_iso(),
        "recommendations": recs,
        "summary": summary,
        "estimated_savings": savings,
        "status": "pending_approval"
    }
    save_pending(pending)

    # Step 5: Send Telegram for Queen approval
    if recs:
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        lines = [
            "⚙️ <b>Optimizer Monthly Report</b>",
            f"<i>{now_ct()}</i>",
            "",
            f"📊 <b>{len(recs)} upgrade(s) recommended</b>",
            f"💰 Est. monthly savings: {savings}",
            "",
            "<b>Recommendations:</b>"
        ]

        for r in recs:
            emoji = priority_emoji.get(r['priority'], '📌')
            lines.append(
                f"{emoji} <b>{r['agent']}</b>\n"
                f"  {r['current_model']}\n"
                f"  → {r['recommended_model']}\n"
                f"  {r['reason'][:80]}"
            )

        lines += [
            "",
            f"📝 Summary: {summary[:200]}",
            "",
            "Reply to approve:",
            "<code>optimizer-approve</code> — apply all recommendations",
            "<code>optimizer-skip</code> — skip this month",
            "<code>optimizer-apply [agent]</code> — apply specific agent only"
        ]

        send_telegram("\n".join(lines))
        print(f"\n  📱 Recommendations sent to Telegram for Queen approval")
    else:
        send_telegram(
            "⚙️ <b>Optimizer Monthly Report</b>\n"
            f"<i>{now_ct()}</i>\n\n"
            "✅ All agents running optimal models. No changes needed."
        )

    update_memory(f"Optimizer scan: {len(recs)} recommendations generated")
    print(f"\n✅ Optimizer scan complete — {now_ct()}")
    return recommendations

def apply_approved_upgrades(agent_filter=None):
    """Apply pending approved upgrades."""
    pending = load_pending()
    if not pending or not pending.get("recommendations"):
        print("No pending upgrades.")
        return

    recs = pending["recommendations"]
    if agent_filter:
        recs = [r for r in recs if r["agent"] == agent_filter]

    history = load_history()
    applied = []

    for rec in recs:
        if rec.get("risk") == "high":
            print(f"  ⚠️  Skipping high-risk upgrade: {rec['agent']} — manual review required")
            continue

        print(f"\n  Applying: {rec['agent']} → {rec['recommended_model']}")
        files = apply_upgrade(rec["agent"], rec["current_model"], rec["recommended_model"])

        if files:
            applied.append(rec)
            history.append({
                "timestamp": now_iso(),
                "agent": rec["agent"],
                "old_model": rec["current_model"],
                "new_model": rec["recommended_model"],
                "files": files,
                "reason": rec["reason"]
            })

    save_history(history)

    # Run health check after upgrades
    print("\n  🛡️  Running health check post-upgrade...")
    result = subprocess.run(
        ["python3", str(HIVE_ROOT/"workspace-warden/health_monitor.py"), "--silent"],
        capture_output=True, text=True, timeout=60
    )
    print(result.stdout[-500:] if result.stdout else "No output")

    update_memory(f"Optimizer applied {len(applied)} upgrades: {[a['agent'] for a in applied]}")

    msg = (
        f"⚙️ <b>Optimizer: Upgrades Applied</b>\n"
        f"<i>{now_ct()}</i>\n\n"
        f"✅ {len(applied)} agent(s) upgraded:\n"
    )
    for a in applied:
        msg += f"• {a['agent']}: {a['old_model']} → {a['recommended_model']}\n"
    msg += "\n🛡️ Health check run — check Warden for status."
    send_telegram(msg)

    print(f"\n✅ Applied {len(applied)} upgrades")

def show_status():
    """Show current model inventory."""
    print(f"\n⬡ HIVE MODEL INVENTORY — {now_ct()}\n")
    print(f"{'Agent':<20} {'Model':<45} {'Tier':<10} {'Cost'}")
    print("─" * 90)

    for agent_id, config in AGENT_REGISTRY.items():
        model = config.get("current_model", "none")
        tier  = config.get("quality_tier", "none")
        cost  = config.get("cost_sensitivity", "none")
        print(f"{agent_id:<20} {model:<45} {tier:<10} {cost}")

    pending = load_pending()
    if pending.get("recommendations"):
        print(f"\n⚠️  {len(pending['recommendations'])} pending upgrade(s) — run with --apply to execute")

    history = load_history()
    if history:
        print(f"\n📋 Last upgrade: {history[-1]['timestamp'][:10]} — {history[-1]['agent']}")

def run_benchmark():
    """Benchmark key models for speed and quality."""
    print(f"\n⬡ MODEL BENCHMARK — {now_ct()}\n")

    models_to_test = [
        "anthropic/claude-sonnet-4-6",
        "google/gemini-2.5-flash-lite",
        "anthropic/claude-haiku-4-5",
    ]

    results = []
    for model in models_to_test:
        print(f"  Testing {model}...")
        for task in ["simple", "math"]:
            result = benchmark_model(model, task)
            result["task"] = task
            results.append(result)
            if result["ok"]:
                print(f"    {task}: {result['latency_ms']}ms — {result['response'][:40]}")
            else:
                print(f"    {task}: FAILED — {result.get('error','?')}")
        time.sleep(1)

    print(f"\n✅ Benchmark complete")
    return results

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Optimizer — Self-Improvement Agent")
    parser.add_argument("--scan",      action="store_true", help="Scan and recommend only")
    parser.add_argument("--apply",     action="store_true", help="Apply pending upgrades")
    parser.add_argument("--agent",     type=str,            help="Apply upgrade for specific agent")
    parser.add_argument("--status",    action="store_true", help="Show model inventory")
    parser.add_argument("--benchmark", action="store_true", help="Run model benchmarks")
    args = parser.parse_args()

    load_env()

    if args.status:
        show_status()
    elif args.benchmark:
        run_benchmark()
    elif args.apply:
        apply_approved_upgrades(agent_filter=args.agent)
    else:
        run_scan()
