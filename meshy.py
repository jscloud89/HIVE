#!/usr/bin/env python3
"""
meshy.py — HIVE Meshy Agent
Converts text prompts or concept images into 3D printable meshes via Meshy API.

Pipeline:
  Text/Image → Meshy text-to-3d or image-to-3d → STL → Engineer validation → Foreman

Usage:
  python3 meshy.py --prompt "PSA card stand with pokeball emblem"
  python3 meshy.py --image /path/to/concept.png --prompt "card stand"
  python3 meshy.py --status <task_id>
  python3 meshy.py --download <task_id>
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
WORKSPACE   = Path(__file__).parent
PHASE1_DIR  = Path.home() / "hive-phase1"
DATA_DIR    = PHASE1_DIR / "data"
MODELS_DIR  = WORKSPACE / "models"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
WEB_DIR     = Path.home() / "HIVE"
TASKS_FILE  = WORKSPACE / "meshy_tasks.json"

MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────
MESHY_BASE = "https://api.meshy.ai/openapi"

# Print-optimized style prompts
STYLE_SUFFIX = (
    "3D printable, clean geometry, suitable for FDM printing, "
    "no floating parts, solid base, manifold mesh, "
    "product design aesthetic, professional quality"
)

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

def get_key():
    key = os.environ.get("MESHY_API_KEY", "")
    if not key:
        print("❌ MESHY_API_KEY not set in .env")
        sys.exit(1)
    return key

def meshy_request(method, endpoint, data=None, headers=None):
    key = get_key()
    url = f"{MESHY_BASE}{endpoint}"
    h = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    if headers:
        h.update(headers)

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=h,
        method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ❌ HTTP {e.code}: {err[:200]}")
        return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None

def load_tasks():
    if TASKS_FILE.exists():
        return json.loads(TASKS_FILE.read_text())
    return {}

def save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))

def save_task(task_id, data):
    tasks = load_tasks()
    tasks[task_id] = data
    save_tasks(tasks)

def update_memory(event):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M CT")
    line = f"## {ts} — {event}\n"
    existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    MEMORY_FILE.write_text(line + existing)

def send_telegram(text, image_path=None):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    if image_path and Path(image_path).exists():
        _send_photo(token, chat_id, image_path, text)
    else:
        body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"  ⚠️  Telegram: {e}")

def _send_photo(token, chat_id, image_path, caption):
    img = Path(image_path)
    boundary = "----HiveMeshyBoundary"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{img.name}\"\r\nContent-Type: image/png\r\n\r\n",
    ]
    body = b"".join(p.encode() for p in parts) + img.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        print("  📸 Photo sent to Telegram")
    except Exception as e:
        print(f"  ⚠️  Photo send failed: {e}")
        # Fallback to text
        url = f"http://100.76.173.87:8080/models/{img.name}"
        send_telegram(f"{caption}\n\n🖼️ <a href='{url}'>View Model Preview</a>")

# ── Text to 3D ───────────────────────────────────────────
def text_to_3d(prompt, negative_prompt="", art_style="realistic", symmetry=False):
    """
    Create a 3D model from text prompt.
    Two-stage: preview (fast) then refine (quality).
    """
    print(f"\n{'='*55}")
    print(f"  🔮 MESHY — Text to 3D")
    print(f"  Prompt: {prompt[:80]}")
    print(f"{'='*55}\n")

    full_prompt = f"{prompt}. {STYLE_SUFFIX}"

    # Stage 1: Preview
    print("  Stage 1: Generating preview mesh...")
    preview_data = {
        "mode": "preview",
        "prompt": full_prompt,
        "negative_prompt": negative_prompt or "low quality, blurry, distorted, floating parts, disconnected geometry",
        "art_style": art_style,
        "should_remesh": True,
        "symmetry": "on" if symmetry else "off",
        "topology": "quad",
        "target_polycount": 30000
    }

    result = meshy_request("POST", "/v2/text-to-3d", preview_data)
    if not result:
        print("  ❌ Failed to start preview task")
        return None

    task_id = result["result"]
    print(f"  ✓ Preview task: {task_id}")

    # Poll until complete
    preview_task = poll_task(task_id, "text-to-3d", timeout=300)
    if not preview_task:
        return None

    # Stage 2: Refine
    print("\n  Stage 2: Refining mesh quality...")
    refine_data = {
        "mode": "refine",
        "preview_task_id": task_id
    }

    refine_result = meshy_request("POST", "/v2/text-to-3d", refine_data)
    if not refine_result:
        print("  ⚠️  Refine failed, using preview")
        final_task = preview_task
    else:
        refine_id = refine_result["result"]
        print(f"  ✓ Refine task: {refine_id}")
        final_task = poll_task(refine_id, "text-to-3d", timeout=600)
        if not final_task:
            print("  ⚠️  Refine timed out, using preview")
            final_task = preview_task
            refine_id = task_id

    return final_task

# ── Image to 3D ──────────────────────────────────────────
def image_to_3d(image_path_or_url, prompt=""):
    """
    Create a 3D model from a concept image.
    """
    print(f"\n{'='*55}")
    print(f"  🖼️  MESHY — Image to 3D")
    print(f"{'='*55}\n")

    # If local file, we need to upload it or use base64
    if image_path_or_url.startswith("http"):
        image_url = image_path_or_url
    else:
        # Convert to base64 data URL
        import base64
        img_data = Path(image_path_or_url).read_bytes()
        ext = Path(image_path_or_url).suffix.lower().replace('.', '')
        if ext == 'jpg':
            ext = 'jpeg'
        b64 = base64.b64encode(img_data).decode()
        image_url = f"data:image/{ext};base64,{b64}"
        print(f"  ✓ Image encoded ({len(img_data)//1024}KB)")

    print("  Generating 3D mesh from image...")
    data = {
        "image_url": image_url,
        "enable_pbr": False,
        "should_remesh": True,
        "topology": "quad",
        "target_polycount": 30000,
        "ai_model": "meshy-4"
    }

    if prompt:
        data["prompt"] = prompt

    result = meshy_request("POST", "/v1/image-to-3d", data)
    if not result:
        print("  ❌ Failed to start image-to-3d task")
        return None

    task_id = result["result"]
    print(f"  ✓ Task: {task_id}")

    return poll_task(task_id, "image-to-3d", timeout=600)

# ── Poll task ────────────────────────────────────────────
def poll_task(task_id, task_type, timeout=600):
    endpoint_map = {
        "text-to-3d": f"/v2/text-to-3d/{task_id}",
        "image-to-3d": f"/v1/image-to-3d/{task_id}"
    }
    endpoint = endpoint_map.get(task_type, f"/v2/text-to-3d/{task_id}")

    start = time.time()
    last_progress = -1

    while time.time() - start < timeout:
        task = meshy_request("GET", endpoint)
        if not task:
            time.sleep(5)
            continue

        status   = task.get("status", "unknown")
        progress = task.get("progress", 0)

        if progress != last_progress:
            print(f"  ⏳ {status} — {progress}%")
            last_progress = progress

        if status == "SUCCEEDED":
            print(f"  ✅ Complete!")
            return task
        elif status in ("FAILED", "EXPIRED"):
            print(f"  ❌ Task {status}: {task.get('task_error', {}).get('message', 'unknown error')}")
            return None

        time.sleep(8)

    print(f"  ⏰ Timeout after {timeout}s")
    return None

# ── Download model ───────────────────────────────────────
def download_model(task, slug=None):
    if not task:
        return None

    model_urls = task.get("model_urls", {})
    stl_url = model_urls.get("stl") or model_urls.get("glb") or model_urls.get("fbx")

    if not stl_url:
        print(f"  ❌ No model URL in task")
        print(f"  Available: {list(model_urls.keys())}")
        return None

    # Determine extension
    ext = "stl" if "stl" in stl_url.lower() or "stl" in model_urls else "glb"
    if "glb" in stl_url.lower():
        ext = "glb"

    slug = slug or task.get("id", "model")
    filename = f"{slug}.{ext}"
    out_path = MODELS_DIR / filename

    print(f"  ⬇️  Downloading {ext.upper()} model...")
    try:
        urllib.request.urlretrieve(stl_url, out_path)
        print(f"  ✅ Saved: {out_path.name} ({out_path.stat().st_size//1024}KB)")

        # Copy to web dir
        import shutil
        web_models = WEB_DIR / "models"
        web_models.mkdir(exist_ok=True)
        shutil.copy(out_path, web_models / filename)

        return out_path
    except Exception as e:
        print(f"  ❌ Download failed: {e}")
        return None

def download_thumbnail(task, slug=None):
    thumb_url = task.get("thumbnail_url", "")
    if not thumb_url:
        return None

    slug = slug or task.get("id", "model")
    out_path = MODELS_DIR / f"{slug}_thumb.png"

    try:
        urllib.request.urlretrieve(thumb_url, out_path)
        # Copy to web renders
        import shutil
        web_renders = WEB_DIR / "renders"
        web_renders.mkdir(exist_ok=True)
        shutil.copy(out_path, web_renders / f"{slug}_thumb.png")
        print(f"  📸 Thumbnail: {out_path.name}")
        return out_path
    except Exception as e:
        print(f"  ⚠️  Thumbnail download failed: {e}")
        return None

# ── Full pipeline ────────────────────────────────────────
def run_pipeline(prompt, image_path=None, negative_prompt="", art_style="realistic"):
    slug = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + prompt[:20].lower().replace(" ", "-").replace("/", "-")

    print(f"\n⬡ MESHY PIPELINE")
    print(f"  Slug: {slug}")

    # Generate
    if image_path:
        task = image_to_3d(image_path, prompt)
    else:
        task = text_to_3d(prompt, negative_prompt, art_style)

    if not task:
        send_telegram(f"❌ <b>Meshy failed</b>\nPrompt: {prompt[:100]}")
        return None

    # Download
    thumb_path = download_thumbnail(task, slug)
    model_path = download_model(task, slug)

    if not model_path:
        return None

    # Save task record
    save_task(slug, {
        "prompt": prompt,
        "image_path": image_path,
        "task_id": task.get("id"),
        "slug": slug,
        "model_path": str(model_path),
        "thumb_path": str(thumb_path) if thumb_path else None,
        "timestamp": now_iso(),
        "status": "pending_approval"
    })

    # Notify via Telegram
    model_url = f"http://100.76.173.87:8080/models/{model_path.name}"
    thumb_url = f"http://100.76.173.87:8080/renders/{slug}_thumb.png"

    caption = (
        f"🔮 <b>Meshy Model Ready</b>\n"
        f"<i>{prompt[:80]}</i>\n\n"
        f"📦 <a href='{model_url}'>Download {model_path.suffix.upper()}</a>\n\n"
        f"Reply:\n"
        f"✅ <code>print {slug}</code> — send to Foreman\n"
        f"🔧 <code>remix {slug}: [feedback]</code> — regenerate\n"
        f"❌ <code>drop {slug}</code> — discard"
    )

    if thumb_path and thumb_path.exists():
        send_telegram(caption, thumb_path)
    else:
        send_telegram(caption)

    update_memory(f"Meshy model generated: {prompt[:60]} → {model_path.name}")
    print(f"\n✅ Pipeline complete — {model_path.name}")
    return model_path

# ── Status check ─────────────────────────────────────────
def check_status(task_id):
    # Try both endpoints
    for endpoint in [f"/v2/text-to-3d/{task_id}", f"/v1/image-to-3d/{task_id}"]:
        task = meshy_request("GET", endpoint)
        if task and "status" in task:
            print(json.dumps(task, indent=2))
            return task
    print(f"  ❌ Task not found: {task_id}")
    return None

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Meshy Agent")
    parser.add_argument("--prompt",   type=str, help="Text prompt for 3D generation")
    parser.add_argument("--image",    type=str, help="Image path or URL for image-to-3d")
    parser.add_argument("--negative", type=str, default="", help="Negative prompt")
    parser.add_argument("--style",    type=str, default="realistic",
                        choices=["realistic","cartoon","low-poly","sculpture"],
                        help="Art style")
    parser.add_argument("--status",   type=str, metavar="TASK_ID", help="Check task status")
    parser.add_argument("--download", type=str, metavar="TASK_ID", help="Download completed task")
    parser.add_argument("--list",     action="store_true", help="List all tasks")
    args = parser.parse_args()

    load_env()

    if args.status:
        check_status(args.status)
    elif args.download:
        task = check_status(args.download)
        if task:
            download_model(task)
    elif args.list:
        tasks = load_tasks()
        if not tasks:
            print("No tasks found")
        for slug, data in tasks.items():
            print(f"  {slug}: {data['prompt'][:50]} — {data.get('status','?')}")
    elif args.prompt or args.image:
        run_pipeline(
            prompt=args.prompt or "",
            image_path=args.image,
            negative_prompt=args.negative,
            art_style=args.style
        )
    else:
        parser.print_help()
