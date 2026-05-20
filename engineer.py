#!/usr/bin/env python3
"""
engineer.py — HIVE Engineer Agent
Autonomous design → render → approve → print pipeline.

Flow:
  1. Receives a design brief (from War Room decree or direct call)
  2. Researches dimensions via web search
  3. Generates parametric OpenSCAD file via Claude
  4. Renders STL + preview PNG via OpenSCAD
  5. Sends preview to Telegram with approve/tweak buttons
  6. Listens for Telegram reply
  7. On approval → hands STL to Foreman → prints
  8. On feedback → adjusts SCAD → re-renders → re-sends

Usage:
  python3 engineer.py --brief "PSA graded card display stand, pokeball emblem"
  python3 engineer.py --listen   # run Telegram webhook listener
  python3 engineer.py --status   # show pending designs
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE    = Path(__file__).parent
HIVE_ROOT    = WORKSPACE.parent
PHASE1_DIR   = Path.home() / "hive-phase1"
DATA_DIR     = PHASE1_DIR / "data"
DESIGNS_DIR  = WORKSPACE / "designs"
RENDERS_DIR  = WORKSPACE / "renders"
PENDING_FILE = WORKSPACE / "pending_approvals.json"
MEMORY_FILE  = WORKSPACE / "MEMORY.md"
WEB_DIR      = Path.home() / "HIVE"

DESIGNS_DIR.mkdir(parents=True, exist_ok=True)
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_DESIGN   = "anthropic/claude-sonnet-4-6"
MODEL_FAST     = "google/gemini-2.5-flash-lite"
CHANCELLOR_URL = "http://localhost:8001"
FOREMAN_SCRIPT = HIVE_ROOT / "workspace-foreman" / "foreman.py"

ENGINEER_SOUL = """You are Engineer, the HIVE's parametric 3D design agent.
You generate OpenSCAD code for 3D printed products.

Your designs must:
- Be fully parametric (variables at the top for easy tweaking)
- Print without supports when possible
- Follow best practices: wall thickness 3-4 shells, tolerance 0.2-0.5mm
- Include print notes as comments
- Be production-ready on the Bambu Lab A1 Mini (180x180x180mm build volume)
- Use PLA-friendly geometry (no overhangs >45° without supports)

When generating OpenSCAD:
- Start with a clear parameters section
- Use modules for reusable geometry
- Include variants if applicable (different sizes, emblems)
- Comment every major section
- End with print notes

Output ONLY valid OpenSCAD code. No markdown, no explanation outside comments."""

DIMENSION_SOUL = """You are a research assistant. Given a product brief,
return the exact physical dimensions needed for 3D printing.
Be specific with millimeters. Research the most common/standard dimensions.
Return a JSON object with all relevant dimensions."""

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def now_slug():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

# ── Environment ──────────────────────────────────────────
def load_env():
    env_file = PHASE1_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

# ── API calls ────────────────────────────────────────────
def call_openrouter(system, user, model=MODEL_DESIGN, max_tokens=3000, web_search=False):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set")
        return None

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

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://hive.local",
            "X-Title": "HIVE Engineer"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            # Handle tool use responses
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                # Extract text from content blocks
                return " ".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            return content.strip() if content else None
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code}: {e.read().decode()[:150]}")
        return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None

# ── Telegram ─────────────────────────────────────────────
def send_telegram(text, image_path=None):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  ⚠️  Telegram not configured")
        return False

    if image_path and Path(image_path).exists():
        # Send photo with caption
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        import multipart_form
        # Fall back to text if multipart not available
        _send_telegram_text(token, chat_id,
            f"🖼️ Preview ready — check http://192.168.50.10:8080/renders/{Path(image_path).name}\n\n{text}")
    else:
        _send_telegram_text(token, chat_id, text)
    return True

def _send_telegram_text(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }).encode()
    req = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True
    except Exception as e:
        print(f"  ⚠️  Telegram error: {e}")
        return False

def send_telegram_photo(image_path, caption):
    """Send photo to Telegram using multipart form."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    img = Path(image_path)
    if not img.exists():
        return _send_telegram_text(token, chat_id, caption)

    # Build multipart manually
    boundary = "----HiveBoundary"
    body_parts = []

    # chat_id field
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
    )
    # parse_mode
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n"
    )
    # caption
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n"
    )
    # photo file
    img_data = img.read_bytes()
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{img.name}\"\r\nContent-Type: image/png\r\n\r\n"
    )

    body = b"".join(p.encode() if isinstance(p, str) else p for p in body_parts)
    body += img_data
    body += f"\r\n--{boundary}--\r\n".encode()

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"  📸 Photo sent to Telegram")
            return True
    except Exception as e:
        print(f"  ⚠️  Photo send failed: {e}")
        # Fall back to text with URL
        return _send_telegram_text(token, chat_id,
            f"{caption}\n\n🖼️ <a href='http://192.168.50.10:8080/renders/{img.name}'>View Preview</a>")

def get_telegram_updates(offset=0):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=30"
    try:
        with urllib.request.urlopen(url, timeout=35) as resp:
            return json.loads(resp.read().decode())
    except:
        return {"result": []}

# ── Pending approvals ────────────────────────────────────
def load_pending():
    if PENDING_FILE.exists():
        return json.loads(PENDING_FILE.read_text())
    return {}

def save_pending(pending):
    PENDING_FILE.write_text(json.dumps(pending, indent=2))

def add_pending(design_id, data):
    pending = load_pending()
    pending[design_id] = data
    save_pending(pending)

def remove_pending(design_id):
    pending = load_pending()
    pending.pop(design_id, None)
    save_pending(pending)

# ── Research dimensions ──────────────────────────────────
def research_dimensions(brief):
    print(f"  🔍 Researching dimensions for: {brief}")

    prompt = f"""Research the exact physical dimensions for: {brief}

Return a JSON object with dimensions in millimeters. Example format:
{{
  "item": "PSA graded card slab",
  "width_mm": 81,
  "height_mm": 136,
  "depth_mm": 6.5,
  "tolerance_recommended_mm": 1.0,
  "notes": "Standard PSA slab dimensions",
  "variants": {{
    "BGS": {{"width_mm": 84, "depth_mm": 8}},
    "CGC": {{"width_mm": 82, "depth_mm": 7}}
  }}
}}

Return ONLY valid JSON. No markdown."""

    response = call_openrouter(
        system=DIMENSION_SOUL,
        user=prompt,
        model=MODEL_FAST,
        max_tokens=500,
        web_search=True
    )

    if not response:
        return None

    # Extract JSON
    try:
        # Strip any markdown
        clean = re.sub(r'```json|```', '', response).strip()
        return json.loads(clean)
    except:
        print(f"  ⚠️  Could not parse dimensions JSON: {response[:200]}")
        return None

# ── Generate OpenSCAD ────────────────────────────────────
def generate_scad(brief, dimensions, feedback=None):
    print(f"  ⚙️  Generating OpenSCAD...")

    dim_str = json.dumps(dimensions, indent=2) if dimensions else "Use standard dimensions"
    feedback_str = f"\n\nUSER FEEDBACK TO INCORPORATE:\n{feedback}" if feedback else ""

    prompt = f"""Design brief: {brief}

Researched dimensions:
{dim_str}

Design requirements:
- Two-prong style stand (like a card holder with two vertical posts)
- Wide stable base with slight front bevel
- Slot between prongs sized for the card/slab
- Chamfered top entry for easy insertion
- Pokéball emblem embossed on front face of base (variant=0)
- Star/GRADED emblem option (variant=1)
- Plain option (variant=2)
- Brand text "spiced_slabs" recessed into bottom
- Rubber foot recesses (4 corners)
- Print flat, no supports needed
- Bambu Lab A1 Mini compatible (max 180x180x180mm){feedback_str}

Generate complete, valid OpenSCAD code."""

    response = call_openrouter(
        system=ENGINEER_SOUL,
        user=prompt,
        model=MODEL_DESIGN,
        max_tokens=4000
    )

    if not response:
        return None

    # Strip markdown if present
    response = re.sub(r'```openscad|```scad|```', '', response).strip()
    return response

# ── Render STL + PNG ─────────────────────────────────────
def render_design(scad_path, slug):
    stl_path = DESIGNS_DIR / f"{slug}.stl"
    png_path  = RENDERS_DIR / f"{slug}.png"

    print(f"  🖨️  Rendering STL...")
    result = subprocess.run(
        ["openscad", "-o", str(stl_path), str(scad_path)],
        capture_output=True, text=True, timeout=120
    )

    if result.returncode != 0:
        print(f"  ❌ STL render failed:\n{result.stderr[:300]}")
        return None, None

    print(f"  📸 Rendering preview PNG...")
    png_result = subprocess.run([
        "openscad",
        "--render",
        "--imgsize=800,600",
        "--colorscheme=Tomorrow Night",
        "-o", str(png_path),
        str(scad_path)
    ], capture_output=True, text=True, timeout=60)

    if png_result.returncode != 0:
        print(f"  ⚠️  PNG render failed (STL still valid)")
        png_path = None
    else:
        # Copy to web dir for easy access
        import shutil
        web_renders = WEB_DIR / "renders"
        web_renders.mkdir(exist_ok=True)
        shutil.copy(png_path, web_renders / f"{slug}.png")

    print(f"  ✅ STL: {stl_path.name} ({stl_path.stat().st_size // 1024}KB)")
    return stl_path, png_path

# ── Send for approval ────────────────────────────────────
def send_for_approval(design_id, brief, stl_path, png_path, dimensions, iteration=1):
    dim_summary = ""
    if dimensions:
        dim_summary = f"\n📐 Dimensions: {dimensions.get('width_mm')}mm W × {dimensions.get('height_mm', '?')}mm H × {dimensions.get('depth_mm')}mm D"

    caption = (
        f"🔧 <b>Engineer Design Ready</b> — Iteration {iteration}\n"
        f"<i>{brief}</i>"
        f"{dim_summary}\n"
        f"📦 STL: {stl_path.name}\n\n"
        f"Reply with:\n"
        f"✅ <code>approve {design_id}</code> — send to printer\n"
        f"🔧 <code>tweak {design_id}: [your feedback]</code> — redesign\n"
        f"❌ <code>cancel {design_id}</code> — cancel"
    )

    if png_path and Path(png_path).exists():
        send_telegram_photo(png_path, caption)
    else:
        _send_telegram_text(
            os.environ.get("TELEGRAM_BOT_TOKEN",""),
            os.environ.get("TELEGRAM_CHAT_ID",""),
            caption + f"\n\n🖼️ <a href='http://192.168.50.10:8080/renders/{design_id}.png'>View Preview</a>"
        )

    # Store pending
    add_pending(design_id, {
        "brief": brief,
        "stl_path": str(stl_path),
        "png_path": str(png_path) if png_path else None,
        "dimensions": dimensions,
        "iteration": iteration,
        "timestamp": now_iso()
    })

    print(f"  📱 Sent to Telegram for approval (ID: {design_id})")

# ── Send to printer ──────────────────────────────────────
def send_to_printer(stl_path):
    print(f"  🖨️  Sending to Foreman for printing: {stl_path}")
    result = subprocess.run(
        ["python3", str(FOREMAN_SCRIPT), "--print", str(stl_path)],
        capture_output=True, text=True, timeout=60
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  ❌ Foreman error: {result.stderr}")
        return False
    return True

# ── Update memory ────────────────────────────────────────
def update_memory(event):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M CT")
    line = f"## {ts} — {event}\n"
    existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    MEMORY_FILE.write_text(line + existing)

# ── Main design pipeline ─────────────────────────────────
def design_pipeline(brief, feedback=None, iteration=1):
    slug = f"{now_slug()}-{re.sub(r'[^a-z0-9]', '-', brief.lower())[:30]}"
    design_id = slug

    print(f"\n{'='*55}")
    print(f"  🔧 ENGINEER — Design Pipeline")
    print(f"  Brief: {brief}")
    if feedback:
        print(f"  Feedback: {feedback}")
    print(f"{'='*55}\n")

    # Step 1: Research dimensions
    dimensions = research_dimensions(brief)
    if dimensions:
        print(f"  ✓ Dimensions: {json.dumps(dimensions, indent=4)}")
    else:
        print(f"  ⚠️  Using estimated dimensions")

    # Step 2: Generate SCAD
    scad_code = generate_scad(brief, dimensions, feedback)
    if not scad_code:
        print("  ❌ Failed to generate SCAD")
        return None

    scad_path = DESIGNS_DIR / f"{slug}.scad"
    scad_path.write_text(scad_code)
    print(f"  ✓ SCAD saved: {scad_path.name}")

    # Step 3: Render
    stl_path, png_path = render_design(scad_path, slug)
    if not stl_path:
        print("  ❌ Render failed")

        # Send error to Telegram
        _send_telegram_text(
            os.environ.get("TELEGRAM_BOT_TOKEN",""),
            os.environ.get("TELEGRAM_CHAT_ID",""),
            f"⚠️ <b>Engineer render failed</b>\nBrief: {brief}\nCheck SCAD syntax."
        )
        return None

    # Copy STL to web dir
    import shutil
    shutil.copy(stl_path, WEB_DIR / stl_path.name)

    # Step 4: Send for approval
    send_for_approval(design_id, brief, stl_path, png_path, dimensions, iteration)

    # Log
    update_memory(f"Design generated: {brief} → {stl_path.name}")

    return design_id

# ── Telegram listener ────────────────────────────────────
def listen_for_approvals():
    print(f"\n⬡ Engineer listening for Telegram approvals...")
    offset = 0

    while True:
        try:
            updates = get_telegram_updates(offset)
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip()

                if not text:
                    continue

                print(f"  📨 Received: {text}")

                # Parse commands
                if text.lower().startswith("approve "):
                    design_id = text.split(" ", 1)[1].strip()
                    handle_approval(design_id)

                elif text.lower().startswith("tweak "):
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        design_id = parts[0].replace("tweak ", "").strip()
                        feedback = parts[1].strip()
                        handle_tweak(design_id, feedback)
                    else:
                        _send_telegram_text(
                            os.environ.get("TELEGRAM_BOT_TOKEN",""),
                            os.environ.get("TELEGRAM_CHAT_ID",""),
                            "Format: tweak [design_id]: [your feedback]"
                        )

                elif text.lower().startswith("cancel "):
                    design_id = text.split(" ", 1)[1].strip()
                    handle_cancel(design_id)

                elif text.lower() == "status":
                    handle_status()

        except KeyboardInterrupt:
            print("\n⬡ Engineer listener stopped")
            break
        except Exception as e:
            print(f"  ⚠️  Listener error: {e}")
            time.sleep(5)

def handle_approval(design_id):
    pending = load_pending()
    if design_id not in pending:
        _send_telegram_text(
            os.environ.get("TELEGRAM_BOT_TOKEN",""),
            os.environ.get("TELEGRAM_CHAT_ID",""),
            f"❓ Design ID not found: {design_id}\nCheck /status for pending designs."
        )
        return

    data = pending[design_id]
    stl_path = data["stl_path"]

    _send_telegram_text(
        os.environ.get("TELEGRAM_BOT_TOKEN",""),
        os.environ.get("TELEGRAM_CHAT_ID",""),
        f"✅ <b>Approved!</b> Sending to printer...\n<code>{Path(stl_path).name}</code>"
    )

    success = send_to_printer(stl_path)

    if success:
        remove_pending(design_id)
        update_memory(f"Design approved and printed: {data['brief']}")
        _send_telegram_text(
            os.environ.get("TELEGRAM_BOT_TOKEN",""),
            os.environ.get("TELEGRAM_CHAT_ID",""),
            f"🖨️ <b>Print job sent!</b>\n{Path(stl_path).name}\nForeman will notify you when complete."
        )
    else:
        _send_telegram_text(
            os.environ.get("TELEGRAM_BOT_TOKEN",""),
            os.environ.get("TELEGRAM_CHAT_ID",""),
            f"❌ Failed to send to printer. Check Foreman status."
        )

def handle_tweak(design_id, feedback):
    pending = load_pending()
    if design_id not in pending:
        _send_telegram_text(
            os.environ.get("TELEGRAM_BOT_TOKEN",""),
            os.environ.get("TELEGRAM_CHAT_ID",""),
            f"❓ Design ID not found: {design_id}"
        )
        return

    data = pending[design_id]
    remove_pending(design_id)

    _send_telegram_text(
        os.environ.get("TELEGRAM_BOT_TOKEN",""),
        os.environ.get("TELEGRAM_CHAT_ID",""),
        f"🔧 <b>Redesigning...</b>\nFeedback: {feedback}\nThis takes ~2 minutes."
    )

    # Re-run pipeline with feedback
    new_id = design_pipeline(
        data["brief"],
        feedback=feedback,
        iteration=data.get("iteration", 1) + 1
    )

def handle_cancel(design_id):
    remove_pending(design_id)
    _send_telegram_text(
        os.environ.get("TELEGRAM_BOT_TOKEN",""),
        os.environ.get("TELEGRAM_CHAT_ID",""),
        f"❌ Design {design_id} cancelled."
    )

def handle_status():
    pending = load_pending()
    if not pending:
        _send_telegram_text(
            os.environ.get("TELEGRAM_BOT_TOKEN",""),
            os.environ.get("TELEGRAM_CHAT_ID",""),
            "✅ No pending design approvals."
        )
        return

    lines = ["📋 <b>Pending Design Approvals:</b>\n"]
    for did, data in pending.items():
        lines.append(f"• <code>{did}</code>\n  {data['brief']}\n  Iteration {data.get('iteration',1)}")

    _send_telegram_text(
        os.environ.get("TELEGRAM_BOT_TOKEN",""),
        os.environ.get("TELEGRAM_CHAT_ID",""),
        "\n".join(lines)
    )

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Engineer Agent")
    parser.add_argument("--brief", type=str, help="Design brief to execute")
    parser.add_argument("--listen", action="store_true", help="Listen for Telegram approvals")
    parser.add_argument("--status", action="store_true", help="Show pending designs")
    parser.add_argument("--approve", type=str, help="Manually approve a design ID")
    args = parser.parse_args()

    load_env()

    if args.listen:
        listen_for_approvals()
    elif args.status:
        handle_status()
    elif args.approve:
        handle_approval(args.approve)
    elif args.brief:
        design_pipeline(args.brief)
    else:
        parser.print_help()
