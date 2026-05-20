#!/usr/bin/env python3
"""
design_library.py — HIVE Design Library
Saves, recalls, versions, and manages approved 3D designs.

Every design has:
  - prompt.txt       exact prompt used
  - thumbnail.png    visual preview
  - model.stl/glb    approved mesh
  - notes.md         feedback history
  - meta.json        status, tags, dimensions, print stats
  - versions/        previous iterations

Usage:
  python3 design_library.py --save <slug> --prompt "..." --model /path/to.stl
  python3 design_library.py --list
  python3 design_library.py --list --tag pokemon
  python3 design_library.py --show <slug>
  python3 design_library.py --recall <slug>        # prints prompt for reuse
  python3 design_library.py --approve <slug>
  python3 design_library.py --status <slug> printed
  python3 design_library.py --note <slug> "fits PSA perfectly"
  python3 design_library.py --remix <slug>         # creates new version
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────
LIBRARY_DIR = Path.home() / "HIVE" / "design-library"
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

INDEX_FILE = LIBRARY_DIR / "index.json"

STATUSES = ["draft", "approved", "printing", "printed", "listed", "selling", "retired"]

# ── Index ────────────────────────────────────────────────
def load_index():
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text())
    return {}

def save_index(index):
    INDEX_FILE.write_text(json.dumps(index, indent=2))

def update_index(slug, meta):
    index = load_index()
    index[slug] = {
        "slug": slug,
        "name": meta.get("name", slug),
        "status": meta.get("status", "draft"),
        "tags": meta.get("tags", []),
        "created": meta.get("created", datetime.now().isoformat()),
        "updated": datetime.now().isoformat(),
        "version": meta.get("version", 1),
    }
    save_index(index)

# ── Design directory ─────────────────────────────────────
def design_dir(slug):
    d = LIBRARY_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d

def versions_dir(slug):
    v = design_dir(slug) / "versions"
    v.mkdir(exist_ok=True)
    return v

# ── Load/save meta ───────────────────────────────────────
def load_meta(slug):
    meta_file = design_dir(slug) / "meta.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {}

def save_meta(slug, meta):
    meta["updated"] = datetime.now().isoformat()
    (design_dir(slug) / "meta.json").write_text(json.dumps(meta, indent=2))
    update_index(slug, meta)

# ── Save design ──────────────────────────────────────────
def save_design(slug, prompt, model_path=None, thumbnail_path=None,
                name=None, tags=None, dimensions=None, notes=None, source="meshy"):
    d = design_dir(slug)

    # Save prompt
    (d / "prompt.txt").write_text(prompt)

    # Copy model file
    if model_path and Path(model_path).exists():
        ext = Path(model_path).suffix
        dest = d / f"model{ext}"
        shutil.copy(model_path, dest)
        print(f"  ✓ Model saved: {dest.name}")

    # Copy thumbnail
    if thumbnail_path and Path(thumbnail_path).exists():
        shutil.copy(thumbnail_path, d / "thumbnail.png")
        print(f"  ✓ Thumbnail saved")

    # Save notes
    if notes:
        notes_file = d / "notes.md"
        existing = notes_file.read_text() if notes_file.exists() else ""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        notes_file.write_text(f"## {ts}\n{notes}\n\n" + existing)

    # Save meta
    existing_meta = load_meta(slug)
    meta = {
        "slug": slug,
        "name": name or slug,
        "prompt": prompt,
        "source": source,
        "status": existing_meta.get("status", "draft"),
        "tags": tags or existing_meta.get("tags", []),
        "dimensions": dimensions or existing_meta.get("dimensions", {}),
        "version": existing_meta.get("version", 1),
        "created": existing_meta.get("created", datetime.now().isoformat()),
        "print_count": existing_meta.get("print_count", 0),
        "revenue": existing_meta.get("revenue", 0.0),
    }
    save_meta(slug, meta)

    print(f"  ✅ Design saved: {slug}")
    return d

# ── List designs ─────────────────────────────────────────
def list_designs(status_filter=None, tag_filter=None):
    index = load_index()
    if not index:
        print("No designs in library.")
        return

    filtered = index.values()
    if status_filter:
        filtered = [d for d in filtered if d["status"] == status_filter]
    if tag_filter:
        filtered = [d for d in filtered if tag_filter in d.get("tags", [])]

    filtered = sorted(filtered, key=lambda x: x.get("updated",""), reverse=True)

    print(f"\n⬡ DESIGN LIBRARY ({len(list(filtered))} designs)\n")
    print(f"{'SLUG':<45} {'NAME':<25} {'STATUS':<12} {'TAGS'}")
    print("─" * 110)

    for d in filtered:
        tags = ", ".join(d.get("tags", []))
        print(f"{d['slug']:<45} {d['name']:<25} {d['status']:<12} {tags}")

    print()

# ── Show design ──────────────────────────────────────────
def show_design(slug):
    d = design_dir(slug)
    meta = load_meta(slug)

    if not meta:
        print(f"❌ Design not found: {slug}")
        return

    print(f"\n{'='*60}")
    print(f"  📦 {meta.get('name', slug)}")
    print(f"{'='*60}")
    print(f"  Slug:      {slug}")
    print(f"  Status:    {meta.get('status','draft')}")
    print(f"  Version:   v{meta.get('version',1)}")
    print(f"  Source:    {meta.get('source','unknown')}")
    print(f"  Created:   {meta.get('created','?')[:10]}")
    print(f"  Tags:      {', '.join(meta.get('tags',[]))}")
    print(f"  Prints:    {meta.get('print_count',0)}")
    print(f"  Revenue:   ${meta.get('revenue',0):.2f}")

    dims = meta.get("dimensions", {})
    if dims:
        print(f"  Dims:      {dims}")

    print(f"\n  📝 Prompt:")
    prompt_file = d / "prompt.txt"
    if prompt_file.exists():
        print(f"  {prompt_file.read_text()[:300]}")

    notes_file = d / "notes.md"
    if notes_file.exists():
        print(f"\n  📋 Notes:")
        print(f"  {notes_file.read_text()[:300]}")

    # List files
    files = list(d.glob("*"))
    print(f"\n  📁 Files: {', '.join(f.name for f in files if f.is_file())}")
    print(f"{'='*60}\n")

# ── Recall prompt ────────────────────────────────────────
def recall_prompt(slug):
    prompt_file = design_dir(slug) / "prompt.txt"
    if not prompt_file.exists():
        print(f"❌ No prompt found for: {slug}")
        return None
    prompt = prompt_file.read_text()
    print(f"\n📋 Prompt for {slug}:\n")
    print(prompt)
    print()
    return prompt

# ── Approve design ───────────────────────────────────────
def approve_design(slug):
    meta = load_meta(slug)
    if not meta:
        print(f"❌ Design not found: {slug}")
        return
    meta["status"] = "approved"
    save_meta(slug, meta)
    print(f"  ✅ {slug} → approved")

# ── Update status ────────────────────────────────────────
def update_status(slug, status):
    if status not in STATUSES:
        print(f"❌ Invalid status. Choose from: {', '.join(STATUSES)}")
        return
    meta = load_meta(slug)
    if not meta:
        print(f"❌ Design not found: {slug}")
        return
    old = meta.get("status", "draft")
    meta["status"] = status
    save_meta(slug, meta)
    print(f"  ✅ {slug}: {old} → {status}")

# ── Add note ─────────────────────────────────────────────
def add_note(slug, note):
    d = design_dir(slug)
    notes_file = d / "notes.md"
    existing = notes_file.read_text() if notes_file.exists() else ""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    notes_file.write_text(f"## {ts}\n{note}\n\n" + existing)
    print(f"  ✅ Note added to {slug}")

# ── Remix (version a design) ─────────────────────────────
def remix_design(slug, new_prompt=None, feedback=None):
    """
    Create a new version of an existing design.
    Archives current version, prepares for regeneration.
    """
    d = design_dir(slug)
    meta = load_meta(slug)

    if not meta:
        print(f"❌ Design not found: {slug}")
        return None

    # Archive current version
    version = meta.get("version", 1)
    v_dir = versions_dir(slug) / f"v{version}"
    v_dir.mkdir(exist_ok=True)

    for f in d.glob("*"):
        if f.is_file():
            shutil.copy(f, v_dir / f.name)

    print(f"  📦 Archived v{version} → {v_dir.name}")

    # Build new prompt
    original_prompt = (d / "prompt.txt").read_text() if (d / "prompt.txt").exists() else ""
    if new_prompt:
        prompt = new_prompt
    elif feedback:
        prompt = f"{original_prompt}\n\nREMIX FEEDBACK: {feedback}"
    else:
        prompt = original_prompt

    # Update meta
    meta["version"] = version + 1
    meta["status"] = "draft"
    meta["previous_versions"] = meta.get("previous_versions", []) + [f"v{version}"]
    save_meta(slug, meta)

    # Save new prompt
    (d / "prompt.txt").write_text(prompt)

    print(f"  ✅ Ready for v{version+1} — prompt updated")
    print(f"\n📋 New prompt:\n{prompt[:200]}...\n")

    return prompt

# ── Tag design ───────────────────────────────────────────
def tag_design(slug, tags):
    meta = load_meta(slug)
    if not meta:
        print(f"❌ Design not found: {slug}")
        return
    existing_tags = meta.get("tags", [])
    new_tags = [t.strip() for t in tags.split(",")]
    meta["tags"] = list(set(existing_tags + new_tags))
    save_meta(slug, meta)
    print(f"  ✅ Tags updated: {', '.join(meta['tags'])}")

# ── Search ───────────────────────────────────────────────
def search_designs(query):
    index = load_index()
    query = query.lower()
    results = []
    for slug, d in index.items():
        if query in slug.lower() or query in d.get("name","").lower():
            results.append(d)
            continue
        # Check prompt
        prompt_file = design_dir(slug) / "prompt.txt"
        if prompt_file.exists() and query in prompt_file.read_text().lower():
            results.append(d)

    if not results:
        print(f"No designs found matching: {query}")
        return

    print(f"\n🔍 Search results for '{query}':\n")
    for d in results:
        print(f"  {d['slug']:<45} {d['name']:<25} {d['status']}")

# ── Export for Meshy/Engineer ────────────────────────────
def export_for_regeneration(slug):
    """Returns dict with everything needed to regenerate a design."""
    d = design_dir(slug)
    meta = load_meta(slug)
    prompt_file = d / "prompt.txt"
    thumb_file = d / "thumbnail.png"
    model_files = list(d.glob("model.*"))

    return {
        "slug": slug,
        "meta": meta,
        "prompt": prompt_file.read_text() if prompt_file.exists() else "",
        "thumbnail_path": str(thumb_file) if thumb_file.exists() else None,
        "model_path": str(model_files[0]) if model_files else None,
    }

# ── Entry point ───────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIVE Design Library")
    parser.add_argument("--save",      type=str, metavar="SLUG",   help="Save a design")
    parser.add_argument("--list",      action="store_true",        help="List all designs")
    parser.add_argument("--show",      type=str, metavar="SLUG",   help="Show design details")
    parser.add_argument("--recall",    type=str, metavar="SLUG",   help="Print prompt for reuse")
    parser.add_argument("--approve",   type=str, metavar="SLUG",   help="Approve a design")
    parser.add_argument("--status",    type=str, nargs=2,          help="Set status: --status SLUG STATUS")
    parser.add_argument("--note",      type=str, nargs=2,          help="Add note: --note SLUG TEXT")
    parser.add_argument("--remix",     type=str, metavar="SLUG",   help="Version a design for remixing")
    parser.add_argument("--tag",       type=str, nargs=2,          help="Tag design: --tag SLUG tags")
    parser.add_argument("--search",    type=str, metavar="QUERY",  help="Search designs")

    # Save options
    parser.add_argument("--prompt",    type=str, help="Prompt text")
    parser.add_argument("--model",     type=str, help="Model file path")
    parser.add_argument("--thumbnail", type=str, help="Thumbnail path")
    parser.add_argument("--name",      type=str, help="Human readable name")
    parser.add_argument("--tags",      type=str, help="Comma separated tags")
    parser.add_argument("--feedback",  type=str, help="Remix feedback")

    # Filters
    parser.add_argument("--filter-status", type=str, help="Filter list by status")
    parser.add_argument("--filter-tag",    type=str, help="Filter list by tag")

    args = parser.parse_args()

    if args.save:
        if not args.prompt:
            print("❌ --prompt required with --save")
            sys.exit(1)
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
        save_design(
            slug=args.save,
            prompt=args.prompt,
            model_path=args.model,
            thumbnail_path=args.thumbnail,
            name=args.name or args.save,
            tags=tags,
        )
    elif args.list:
        list_designs(
            status_filter=args.filter_status,
            tag_filter=args.filter_tag
        )
    elif args.show:
        show_design(args.show)
    elif args.recall:
        recall_prompt(args.recall)
    elif args.approve:
        approve_design(args.approve)
    elif args.status:
        update_status(args.status[0], args.status[1])
    elif args.note:
        add_note(args.note[0], args.note[1])
    elif args.remix:
        remix_design(args.remix, feedback=args.feedback)
    elif args.tag:
        tag_design(args.tag[0], args.tag[1])
    elif args.search:
        search_designs(args.search)
    else:
        parser.print_help()
