#!/usr/bin/env python3
"""
auditor.py — The Hive's Per-Print Profit Calculator
workspace-auditor · Runs locally on Ollama — $0 cost
Usage:
  python3 auditor.py --job /path/to/job.json        # Calculate P&L for a job
  python3 auditor.py --quick                         # Quick P&L from prompts
  python3 auditor.py --weekly                        # Weekly machine-hour report
  python3 auditor.py --monthly                       # Monthly product report
  python3 auditor.py --list                          # List all logged jobs
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────
WORKSPACE    = Path(__file__).parent
HIVE_ROOT    = WORKSPACE.parent
PHASE1_DIR   = Path.home() / "hive-phase1"
DATA_DIR     = PHASE1_DIR / "data"
AUDITOR_DIR  = DATA_DIR / "auditor"
JOBS_DIR     = AUDITOR_DIR / "jobs"
MEMORY_FILE  = WORKSPACE / "MEMORY.md"

# ── A1 Mini Constants ────────────────────────────────────────
A1_MINI_WATTS        = 35       # average draw during printing
ELECTRICITY_RATE     = 0.12     # $/kWh — Tennessee average
PACKAGING_COST       = 0.45     # per unit — bubble mailer
FILAMENT_DEFAULT_CPG = 0.025    # $/gram default if Quartermaster unavailable
MACHINE_HOUR_FLOOR   = 2.07     # $/hr break-even
MACHINE_HOUR_TARGET  = 4.00     # $/hr primary target
MACHINE_HOUR_STAR    = 6.00     # $/hr star product threshold

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def load_env():
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

# ── Fee Calculators ──────────────────────────────────────────

def ebay_fees(sale_price: float) -> dict:
    fee = sale_price * 0.1325
    return {
        "transaction_fee":    round(fee, 4),
        "listing_fee":        0.00,
        "payment_processing": 0.00,
        "total_fees":         round(fee, 4)
    }

def etsy_fees(sale_price: float, shipping_charged: float = 0.0) -> dict:
    total        = sale_price + shipping_charged
    transaction  = total * 0.065
    listing      = 0.20
    payment_proc = total * 0.03 + 0.25
    return {
        "transaction_fee":    round(transaction, 4),
        "listing_fee":        listing,
        "payment_processing": round(payment_proc, 4),
        "total_fees":         round(transaction + listing + payment_proc, 4)
    }

def shopify_fees(sale_price: float) -> dict:
    fee = sale_price * 0.029 + 0.30
    return {
        "transaction_fee":    round(fee, 4),
        "listing_fee":        0.00,
        "payment_processing": 0.00,
        "total_fees":         round(fee, 4)
    }

def calculate_fees(platform: str, sale_price: float, shipping: float = 0.0) -> dict:
    p = platform.lower()
    if p == "ebay":
        return ebay_fees(sale_price)
    elif p == "etsy":
        return etsy_fees(sale_price, shipping)
    elif p == "shopify":
        return shopify_fees(sale_price)
    else:
        return ebay_fees(sale_price)  # default conservative

# ── Core P&L Calculator ──────────────────────────────────────

def calculate_pl(
    job_id: str,
    product: str,
    platform: str,
    sale_price: float,
    shipping_charged: float,
    filament_grams: float,
    print_time_hours: float,
    shipping_label_cost: float,
    cost_per_gram: float = None,
    order_id: str = "manual"
) -> dict:
    """Calculate full P&L for a completed print job."""

    cpg = cost_per_gram if cost_per_gram else FILAMENT_DEFAULT_CPG

    # Revenue
    gross_revenue = sale_price + shipping_charged

    # COGS
    filament_cost    = round(filament_grams * cpg, 4)
    electricity_cost = round(print_time_hours * A1_MINI_WATTS / 1000 * ELECTRICITY_RATE, 4)
    packaging_cost   = PACKAGING_COST
    total_cogs       = round(filament_cost + electricity_cost + packaging_cost + shipping_label_cost, 4)

    # Platform fees
    fees = calculate_fees(platform, sale_price, shipping_charged)

    # Net profit
    net_profit = round(gross_revenue - total_cogs - fees["total_fees"], 4)
    margin_pct = round((net_profit / gross_revenue) * 100, 2) if gross_revenue > 0 else 0
    machine_hr = round(net_profit / print_time_hours, 4) if print_time_hours > 0 else 0

    # Margin status
    if margin_pct > 40:
        margin_status = "🟢 Healthy"
    elif margin_pct > 25:
        margin_status = "🟡 Acceptable"
    elif margin_pct > 15:
        margin_status = "🟠 Thin — reprice candidate"
    elif margin_pct > 0:
        margin_status = "🔴 Danger — pause listings"
    else:
        margin_status = "☢️ Losing money — STOP"

    if machine_hr >= MACHINE_HOUR_STAR:
        mhr_status = "🌟 Star product"
    elif machine_hr >= MACHINE_HOUR_TARGET:
        mhr_status = "🟢 Healthy"
    elif machine_hr >= MACHINE_HOUR_FLOOR:
        mhr_status = "🟡 Viable"
    elif machine_hr >= 0:
        mhr_status = "🔴 Below floor"
    else:
        mhr_status = "☢️ Losing money"

    return {
        "job_id":    job_id,
        "order_id":  order_id,
        "timestamp": now_iso(),
        "product":   product,
        "platform":  platform,
        "revenue": {
            "sale_price":       sale_price,
            "shipping_charged": shipping_charged,
            "gross_revenue":    gross_revenue
        },
        "cogs": {
            "filament_grams":      filament_grams,
            "cost_per_gram":       cpg,
            "filament_cost":       filament_cost,
            "print_time_hours":    print_time_hours,
            "electricity_cost":    electricity_cost,
            "packaging_cost":      packaging_cost,
            "shipping_label_cost": shipping_label_cost,
            "total_cogs":          total_cogs
        },
        "platform_fees":         fees,
        "net_profit":            net_profit,
        "margin_pct":            margin_pct,
        "margin_status":         margin_status,
        "machine_hour_profit":   machine_hr,
        "machine_hour_status":   mhr_status,
        "honey_split_ready":     net_profit > 0,
        "alert_required":        margin_pct < 15 or net_profit < 0
    }

def save_job(result: dict) -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    path = JOBS_DIR / f"{result['job_id']}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    return path

def print_pl(result: dict):
    """Print a formatted P&L summary."""
    r   = result["revenue"]
    c   = result["cogs"]
    f   = result["platform_fees"]
    print(f"\n{'='*50}")
    print(f"🧾 P&L REPORT — {result['product']}")
    print(f"{'='*50}")
    print(f"Platform:     {result['platform'].upper()}")
    print(f"Order ID:     {result['order_id']}")
    print()
    print(f"REVENUE:")
    print(f"  Sale price:       ${r['sale_price']:.2f}")
    print(f"  Shipping charged: ${r['shipping_charged']:.2f}")
    print(f"  Gross revenue:    ${r['gross_revenue']:.2f}")
    print()
    print(f"COGS:")
    print(f"  Filament:  {c['filament_grams']}g × ${c['cost_per_gram']:.4f}/g = ${c['filament_cost']:.4f}")
    print(f"  Electric:  {c['print_time_hours']}hr × ${A1_MINI_WATTS}W = ${c['electricity_cost']:.4f}")
    print(f"  Packaging: ${c['packaging_cost']:.2f}")
    print(f"  Shipping:  ${c['shipping_label_cost']:.2f}")
    print(f"  Total COGS: ${c['total_cogs']:.4f}")
    print()
    print(f"PLATFORM FEES ({result['platform'].upper()}):")
    print(f"  Transaction: ${f['transaction_fee']:.4f}")
    print(f"  Listing:     ${f['listing_fee']:.2f}")
    print(f"  Processing:  ${f['payment_processing']:.4f}")
    print(f"  Total fees:  ${f['total_fees']:.4f}")
    print()
    print(f"{'─'*50}")
    print(f"NET PROFIT:   ${result['net_profit']:.2f}")
    print(f"MARGIN:       {result['margin_pct']:.1f}% — {result['margin_status']}")
    print(f"$/MACHINE-HR: ${result['machine_hour_profit']:.2f} — {result['machine_hour_status']}")
    print(f"{'='*50}")
    if result["alert_required"]:
        print(f"⚠️  ALERT: Margin below threshold — review pricing")
    if result["honey_split_ready"]:
        print(f"🍯 Honey split ready — notify Chancellor")

def write_memory(result: dict):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    status = "✅" if result["net_profit"] > 0 else "🔴"
    entry = (
        f"\n## {now_slug()} — {result['product']}\n"
        f"- **Platform:** {result['platform'].upper()}\n"
        f"- **Revenue:** ${result['revenue']['gross_revenue']:.2f}\n"
        f"- **Net profit:** ${result['net_profit']:.2f} {status}\n"
        f"- **Margin:** {result['margin_pct']:.1f}% — {result['margin_status']}\n"
        f"- **$/hr:** ${result['machine_hour_profit']:.2f} — {result['machine_hour_status']}\n"
    )
    with open(MEMORY_FILE, "a") as f:
        f.write(entry)

def load_all_jobs() -> list:
    if not JOBS_DIR.exists():
        return []
    jobs = []
    for f in sorted(JOBS_DIR.glob("*.json")):
        try:
            with open(f) as fp:
                jobs.append(json.load(fp))
        except Exception:
            pass
    return jobs

# ── Weekly Report ────────────────────────────────────────────

def weekly_report():
    jobs = load_all_jobs()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    week_jobs = [
        j for j in jobs
        if datetime.fromisoformat(j["timestamp"]) > cutoff
    ]

    if not week_jobs:
        print("📭 No jobs completed this week yet.")
        return

    total_hours   = sum(j["cogs"]["print_time_hours"] for j in week_jobs)
    total_revenue = sum(j["revenue"]["gross_revenue"] for j in week_jobs)
    total_profit  = sum(j["net_profit"] for j in week_jobs)
    gross_mhr     = round(total_revenue / total_hours, 2) if total_hours else 0
    net_mhr       = round(total_profit / total_hours, 2) if total_hours else 0

    stars  = [j for j in week_jobs if j["machine_hour_profit"] >= MACHINE_HOUR_STAR]
    below  = [j for j in week_jobs if j["machine_hour_profit"] < MACHINE_HOUR_FLOOR]

    print(f"\n{'='*50}")
    print(f"🧾 MACHINE HOUR EFFICIENCY REPORT")
    print(f"Week of {now_slug()}")
    print(f"{'='*50}")
    print(f"Total print hours:  {total_hours:.1f}hr")
    print(f"Revenue generated:  ${total_revenue:.2f}")
    print(f"Gross $/hr:         ${gross_mhr:.2f}")
    print(f"Net $/hr:           ${net_mhr:.2f} (target: ${MACHINE_HOUR_TARGET:.2f}+)")
    print()

    if stars:
        print("STAR PRODUCTS this week:")
        for j in stars:
            print(f"  🌟 {j['product']} — ${j['machine_hour_profit']:.2f}/hr")

    if below:
        print("\nBELOW FLOOR this week:")
        for j in below:
            print(f"  🔴 {j['product']} — ${j['machine_hour_profit']:.2f}/hr → reprice or discontinue")

    print(f"\n$2,000 RECOVERY PROGRESS:")
    total_all_profit = sum(j["net_profit"] for j in load_all_jobs())
    pct = min(round(total_all_profit / 2000 * 100, 1), 100)
    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    print(f"  [{bar}] ${total_all_profit:.2f} / $2,000.00 ({pct}%)")
    print(f"{'='*50}")

# ── Monthly Report ───────────────────────────────────────────

def monthly_report():
    jobs    = load_all_jobs()
    month   = datetime.now(timezone.utc).strftime("%Y-%m")
    cutoff  = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0)
    mo_jobs = [j for j in jobs if datetime.fromisoformat(j["timestamp"]) >= cutoff]

    if not mo_jobs:
        print(f"📭 No jobs completed in {month} yet.")
        return

    # Group by product
    products = {}
    for j in mo_jobs:
        p = j["product"]
        if p not in products:
            products[p] = []
        products[p].append(j)

    AUDITOR_DIR.mkdir(parents=True, exist_ok=True)
    report_path = AUDITOR_DIR / f"monthly-{month}.md"

    lines = [
        f"# Monthly P&L Report — {month}",
        f"Generated: {now_iso()}", "",
        "| Product | Units | Avg Margin | Total Profit | Avg $/hr | Status |",
        "|---|---|---|---|---|---|"
    ]

    for product, pjobs in sorted(products.items(), key=lambda x: -sum(j["net_profit"] for j in x[1])):
        units       = len(pjobs)
        avg_margin  = round(sum(j["margin_pct"] for j in pjobs) / units, 1)
        total_profit= round(sum(j["net_profit"] for j in pjobs), 2)
        avg_mhr     = round(sum(j["machine_hour_profit"] for j in pjobs) / units, 2)
        status      = "✅ Keep" if avg_margin > 25 else "⚠️ Reprice"
        lines.append(f"| {product} | {units} | {avg_margin}% | ${total_profit:.2f} | ${avg_mhr:.2f} | {status} |")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\n📊 Monthly report saved: {report_path}")
    print("\n".join(lines))

# ── Quick Interactive Mode ───────────────────────────────────

def quick_mode():
    """Interactive P&L calculation from command line inputs."""
    print("\n🧾 AUDITOR — Quick P&L Calculator")
    print("=" * 40)

    product          = input("Product name: ").strip()
    platform         = input("Platform (ebay/etsy/shopify): ").strip().lower()
    sale_price       = float(input("Sale price ($): ").strip())
    shipping_charged = float(input("Shipping charged to buyer ($, 0 if free): ").strip() or "0")
    filament_grams   = float(input("Filament used (grams): ").strip())
    print_time_hours = float(input("Print time (hours): ").strip())
    shipping_label   = float(input("Shipping label cost ($): ").strip())
    cpg_input        = input(f"Filament cost/gram (Enter for default ${FILAMENT_DEFAULT_CPG}): ").strip()
    cpg              = float(cpg_input) if cpg_input else None

    job_id = f"quick-{now_slug()}-{product.lower().replace(' ', '-')[:20]}"

    result = calculate_pl(
        job_id=job_id,
        product=product,
        platform=platform,
        sale_price=sale_price,
        shipping_charged=shipping_charged,
        filament_grams=filament_grams,
        print_time_hours=print_time_hours,
        shipping_label_cost=shipping_label,
        cost_per_gram=cpg
    )

    print_pl(result)
    save_job(result)
    write_memory(result)
    print(f"\n💾 Job saved: {JOBS_DIR / job_id}.json")

# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auditor — Hive P&L calculator")
    parser.add_argument("--job",     help="Path to job JSON file")
    parser.add_argument("--quick",   action="store_true", help="Interactive quick P&L")
    parser.add_argument("--weekly",  action="store_true", help="Weekly machine-hour report")
    parser.add_argument("--monthly", action="store_true", help="Monthly product report")
    parser.add_argument("--list",    action="store_true", help="List all logged jobs")
    args = parser.parse_args()

    load_env()
    AUDITOR_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    if args.weekly:
        weekly_report()
        return

    if args.monthly:
        monthly_report()
        return

    if args.list:
        jobs = load_all_jobs()
        if not jobs:
            print("📭 No jobs logged yet.")
            return
        print(f"\n📋 {len(jobs)} jobs logged:\n")
        total = 0
        for j in jobs:
            total += j["net_profit"]
            print(f"  {j['job_id']} | {j['product']} | ${j['net_profit']:.2f} | {j['margin_pct']:.1f}% | ${j['machine_hour_profit']:.2f}/hr")
        print(f"\n  TOTAL NET PROFIT: ${total:.2f} / $2,000.00 target")
        return

    if args.quick:
        quick_mode()
        return

    if args.job:
        with open(args.job) as f:
            job = json.load(f)
        result = calculate_pl(**{k: job[k] for k in job if k in calculate_pl.__code__.co_varnames})
        print_pl(result)
        save_job(result)
        write_memory(result)
        return

    # Default: quick mode
    quick_mode()

if __name__ == "__main__":
    main()
