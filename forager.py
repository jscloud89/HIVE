#!/usr/bin/env python3
"""
forager.py — HIVE Forager Agent
Market intelligence only. Never executes trades.
Monitors crypto + equities, flags movements to Treasurer via Telegram.

Schedule: Run every 4 hours via cron
  0 */4 * * * cd /home/beekeeper/HIVE/workspace-forager && python3 forager.py

Usage:
  python3 forager.py           # run full market scan
  python3 forager.py --watch   # continuous mode, check every 15 min
  python3 forager.py --report  # print last report
"""

import argparse
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE   = Path(__file__).parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data" / "forager"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
REPORT_FILE = DATA_DIR / "last_report.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────
COINGECKO_URL = "https://api.coingecko.com/api/v3"

# Crypto to monitor
CRYPTO_IDS = {
    "bitcoin":  "BTC",
    "ethereum": "ETH",
    "solana":   "SOL",
}

# Movement thresholds that trigger alerts
ALERT_THRESHOLDS = {
    "crypto_spike":   5.0,   # % change in 24h → alert
    "crypto_crash":  -5.0,   # % change in 24h → alert
    "crypto_pump":   10.0,   # % change in 24h → strong alert
    "crypto_dump":  -10.0,   # % change in 24h → strong alert
}

# Equities to monitor (via free Yahoo Finance compatible endpoint)
EQUITIES = {
    "PRNT":  "3D Printing ETF",
    "ROBO":  "Robotics & AI ETF",
    "ARKK":  "ARK Innovation ETF",
    "NVDA":  "NVIDIA",
    "AMD":   "AMD",
}

FORAGER_SOUL = """You are Forager, the HIVE's market intelligence agent.
You analyze price movements and identify opportunities or risks.
You never trade. You only observe and report.
Be concise, specific, and actionable in your analysis.
Keep reports under 100 words."""

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

def load_last_prices():
    if REPORT_FILE.exists():
        return json.loads(REPORT_FILE.read_text()).get("prices", {})
    return {}

# ── Crypto data ───────────────────────────────────────────
def fetch_crypto():
    ids = ",".join(CRYPTO_IDS.keys())
    url = f"{COINGECKO_URL}/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_7d_change=true"
    req = urllib.request.Request(url, headers={"User-Agent": "HIVE-Forager/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  ❌ CoinGecko error: {e}")
        return {}

def fetch_crypto_trending():
    """Get trending coins on CoinGecko."""
    req = urllib.request.Request(
        f"{COINGECKO_URL}/search/trending",
        headers={"User-Agent": "HIVE-Forager/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            coins = data.get("coins", [])[:5]
            return [c["item"]["name"] for c in coins]
    except:
        return []

def fetch_crypto_fear_greed():
    """Get Fear & Greed index."""
    try:
        req = urllib.request.Request(
            "https://api.alternative.me/fng/?limit=1",
            headers={"User-Agent": "HIVE-Forager/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            fg = data["data"][0]
            return int(fg["value"]), fg["value_classification"]
    except:
        return None, None

# ── Equities data ─────────────────────────────────────────
def fetch_equity(ticker):
    """Fetch equity data via Yahoo Finance API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev  = meta.get("chartPreviousClose", price)
            change_pct = ((price - prev) / prev * 100) if prev else 0
            return {
                "ticker": ticker,
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "prev_close": round(prev, 2)
            }
    except Exception as e:
        print(f"  ⚠️  {ticker}: {e}")
        return None

# ── Analysis ──────────────────────────────────────────────
def analyze_crypto(prices, last_prices):
    alerts = []
    summary = []

    for coin_id, symbol in CRYPTO_IDS.items():
        if coin_id not in prices:
            continue
        data = prices[coin_id]
        price = data.get("usd", 0)
        change_24h = data.get("usd_24h_change", 0)
        change_7d  = data.get("usd_7d_change", 0)

        emoji = "🟢" if change_24h > 0 else "🔴"
        summary.append(
            f"{emoji} <b>{symbol}</b>: ${price:,.2f} "
            f"({change_24h:+.1f}% 24h | {change_7d:+.1f}% 7d)"
        )

        # Check alert thresholds
        if change_24h >= ALERT_THRESHOLDS["crypto_pump"]:
            alerts.append(f"🚀 {symbol} PUMP: +{change_24h:.1f}% in 24h — ${price:,.2f}")
        elif change_24h >= ALERT_THRESHOLDS["crypto_spike"]:
            alerts.append(f"📈 {symbol} spike: +{change_24h:.1f}% in 24h")
        elif change_24h <= ALERT_THRESHOLDS["crypto_dump"]:
            alerts.append(f"💥 {symbol} DUMP: {change_24h:.1f}% in 24h — ${price:,.2f}")
        elif change_24h <= ALERT_THRESHOLDS["crypto_crash"]:
            alerts.append(f"📉 {symbol} drop: {change_24h:.1f}% in 24h")

    return summary, alerts

def analyze_equities(equity_data):
    summary = []
    alerts  = []

    for ticker, data in equity_data.items():
        if not data:
            continue
        name   = EQUITIES.get(ticker, ticker)
        price  = data["price"]
        change = data["change_pct"]
        emoji  = "🟢" if change > 0 else "🔴"
        summary.append(f"{emoji} <b>{ticker}</b> ({name}): ${price} ({change:+.1f}%)")

        if abs(change) >= 5:
            direction = "📈" if change > 0 else "📉"
            alerts.append(f"{direction} {ticker} moved {change:+.1f}% — ${price}")

    return summary, alerts

# ── Main scan ─────────────────────────────────────────────
def run_scan(silent=False):
    print(f"\n{'='*50}")
    print(f"  🔍 FORAGER — Market Intelligence Scan")
    print(f"  {now_ct()}")
    print(f"{'='*50}\n")

    last_prices = load_last_prices()

    # Fetch data
    print("  Fetching crypto prices...")
    crypto_prices = fetch_crypto()

    print("  Fetching Fear & Greed index...")
    fg_value, fg_label = fetch_crypto_fear_greed()

    print("  Fetching trending coins...")
    trending = fetch_crypto_trending()

    print("  Fetching equities...")
    equity_data = {}
    for ticker in EQUITIES:
        equity_data[ticker] = fetch_equity(ticker)
        time.sleep(0.5)

    # Analyze
    crypto_summary, crypto_alerts = analyze_crypto(crypto_prices, last_prices)
    equity_summary, equity_alerts = analyze_equities(equity_data)
    all_alerts = crypto_alerts + equity_alerts

    # Build report
    report = {
        "timestamp": now_iso(),
        "prices": {
            coin: {
                "usd": crypto_prices.get(coin, {}).get("usd", 0),
                "change_24h": crypto_prices.get(coin, {}).get("usd_24h_change", 0)
            }
            for coin in CRYPTO_IDS
        },
        "equities": equity_data,
        "fear_greed": {"value": fg_value, "label": fg_label},
        "trending": trending,
        "alerts": all_alerts,
    }

    # Save report
    REPORT_FILE.write_text(json.dumps(report, indent=2))

    # Print to console
    print("\n  📊 CRYPTO:")
    for line in crypto_summary:
        print(f"  {line}")

    if fg_value:
        fg_emoji = "😱" if fg_value < 25 else "😰" if fg_value < 45 else "😐" if fg_value < 55 else "😊" if fg_value < 75 else "🤑"
        print(f"\n  {fg_emoji} Fear & Greed: {fg_value} — {fg_label}")

    if trending:
        print(f"\n  🔥 Trending: {', '.join(trending[:3])}")

    print("\n  📈 EQUITIES:")
    for line in equity_summary:
        print(f"  {line}")

    if all_alerts:
        print(f"\n  ⚠️  ALERTS ({len(all_alerts)}):")
        for alert in all_alerts:
            print(f"  {alert}")

    # Send Telegram report
    if not silent:
        tg_lines = [
            f"🔍 <b>Forager Market Report</b>",
            f"<i>{now_ct()}</i>",
            "",
            "📊 <b>Crypto:</b>",
        ] + crypto_summary

        if fg_value:
            fg_emoji = "😱" if fg_value < 25 else "😰" if fg_value < 45 else "😐" if fg_value < 55 else "😊" if fg_value < 75 else "🤑"
            tg_lines.append(f"\n{fg_emoji} Fear & Greed: {fg_value} — {fg_label}")

        if trending:
            tg_lines.append(f"🔥 Trending: {', '.join(trending[:3])}")

        tg_lines += ["", "📈 <b>Equities:</b>"] + equity_summary

        if all_alerts:
            tg_lines += ["", "⚠️ <b>ALERTS:</b>"] + all_alerts
            tg_lines.append("\n📣 <i>Flagged to Treasurer for review</i>")

        send_telegram("\n".join(tg_lines))
        print(f"\n  📱 Report sent to Telegram")

    update_memory(f"Market scan complete. Alerts: {len(all_alerts)}")
    print(f"\n✅ Forager scan complete")
    return report

def show_last_report():
    if not REPORT_FILE.exists():
        print("No report yet. Run forager.py first.")
        return
    report = json.loads(REPORT_FILE.read_text())
    print(json.dumps(report, indent=2))

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Forager — Market Intelligence")
    parser.add_argument("--watch",  action="store_true", help="Continuous mode every 15 min")
    parser.add_argument("--report", action="store_true", help="Show last report")
    parser.add_argument("--silent", action="store_true", help="Don't send Telegram")
    args = parser.parse_args()

    load_env()

    if args.report:
        show_last_report()
    elif args.watch:
        print("⬡ Forager watching markets (every 15 min)...")
        while True:
            run_scan(silent=args.silent)
            print(f"\n  💤 Next scan in 15 minutes...")
            time.sleep(900)
    else:
        run_scan(silent=args.silent)
