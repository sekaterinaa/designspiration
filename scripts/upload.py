#!/usr/bin/env python3
"""
One-time upload: DB setup → image upload → seed rows.
Safe to re-run (idempotent).

Requirements:
  pip install requests python-dotenv

Usage:
  1. Create a .env file in this repo root with:
       SUPABASE_SERVICE_KEY=eyJ...
  2. Run from the repo root:
       python scripts/upload.py

The script expects this layout next to the repo root (or adjust CONTENT_ROOT):
  assets/                  — 11 manually-curated images
  arena-sources/           — 9 Are.na channel folders, each with images + a CSV
  seed-cards.json
  supabase/setup.sql
"""

import json, mimetypes, os, pathlib, sys, time
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = "https://hxxcwswrwgftolfbuosf.supabase.co"
SERVICE_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")
BUCKET       = "inspirations"

if not SERVICE_KEY:
    sys.exit("ERROR: SUPABASE_SERVICE_KEY not set. Add it to .env")

# Where the unzipped content lives — adjust if different
CONTENT_ROOT = pathlib.Path(__file__).parent.parent  # repo root
# If you unzipped everything into a sibling folder, point here:
# CONTENT_ROOT = pathlib.Path("/path/to/unzipped")

ASSETS_DIR = CONTENT_ROOT / "assets"
ARENA_DIR  = CONTENT_ROOT / "arena-sources"
SEED_FILE  = CONTENT_ROOT / "seed-cards.json"
SQL_FILE   = CONTENT_ROOT / "supabase" / "setup.sql"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}

# ── channel → section label ───────────────────────────────────────────────────
CHANNEL_SECTION = {
    "acid-oae_m5d1gy8":              "Acid",
    "composition-angle-mo_lhfn8tem": "Composition / Angle",
    "data-gqcy3o-grs0":              "Data",
    "details-vrebwg2suja":           "Details",
    "forms-xwtif8gdzku":             "Forms",
    "handwritten-a99h6tgtdi4":       "Handwritten",
    "patterns-dnan2fz7stg":          "Patterns",
    "retro-tmo_hfe0y5g":             "Retro",
    "textures-peptcmhzr9k":          "Textures",
}

CHANNEL_TITLE = {
    "acid-oae_m5d1gy8":              "Acid graphic {i}",
    "composition-angle-mo_lhfn8tem": "Composition study {i}",
    "data-gqcy3o-grs0":              "Data visualization {i}",
    "details-vrebwg2suja":           "Detail study {i}",
    "forms-xwtif8gdzku":             "Form reference {i}",
    "handwritten-a99h6tgtdi4":       "Handwritten type {i}",
    "patterns-dnan2fz7stg":          "Pattern reference {i}",
    "retro-tmo_hfe0y5g":             "Retro design {i}",
    "textures-peptcmhzr9k":          "Texture reference {i}",
}

CHANNEL_DESC = {
    "acid-oae_m5d1gy8":              "Acid / psychedelic graphic from the Are.na Acid channel.",
    "composition-angle-mo_lhfn8tem": "Composition or framing reference from the Are.na Composition & Angle channel.",
    "data-gqcy3o-grs0":              "Data-driven or infographic design from the Are.na Data channel.",
    "details-vrebwg2suja":           "Close-up detail or material study from the Are.na Details channel.",
    "forms-xwtif8gdzku":             "Geometric or structural form reference from the Are.na Forms channel.",
    "handwritten-a99h6tgtdi4":       "Handwritten lettering or mark-making from the Are.na Handwritten channel.",
    "patterns-dnan2fz7stg":          "Repeating pattern or surface design from the Are.na Patterns channel.",
    "retro-tmo_hfe0y5g":             "Retro or vintage design reference from the Are.na Retro channel.",
    "textures-peptcmhzr9k":          "Tactile texture or surface reference from the Are.na Textures channel.",
}

# ── helpers ───────────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {SERVICE_KEY}",
    "apikey": SERVICE_KEY,
})

def rest(method, path, **kwargs):
    url = f"{SUPABASE_URL}/rest/v1{path}"
    r = session.request(method, url, **kwargs)
    return r

def storage_upload(bucket_path: str, local: pathlib.Path) -> str:
    """Upload file to storage. Returns public URL. Skips if already exists."""
    mime = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
    if local.suffix == ".webp":
        mime = "image/webp"
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{bucket_path}"
    with open(local, "rb") as f:
        data = f.read()
    r = session.post(url, data=data, headers={
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": mime,
        "x-upsert": "false",
    })
    if r.status_code in (200, 201):
        print(f"  ✓ uploaded  {bucket_path}")
    elif r.status_code == 409:
        print(f"  · exists    {bucket_path}")
    else:
        print(f"  ✗ FAILED    {bucket_path}: {r.status_code} {r.text[:120]}", file=sys.stderr)
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{bucket_path}"

def db_upsert(row: dict):
    """Insert row, skip on duplicate image_path."""
    r = rest("POST", "/inspirations", json=row, headers={
        "Prefer": "resolution=ignore-duplicates,return=minimal",
        "Content-Type": "application/json",
    })
    if r.status_code in (200, 201):
        print(f"  ✓ row  {row['title']}")
    elif r.status_code == 409:
        print(f"  · dup  {row['title']}")
    else:
        print(f"  ✗ ROW FAILED  {row['title']}: {r.status_code} {r.text[:120]}", file=sys.stderr)


# ── Step 1: run setup.sql ─────────────────────────────────────────────────────
print("\n=== Step 1: database + storage setup ===")

# Check if table already exists
r = rest("GET", "/inspirations?limit=1")
if r.status_code == 200:
    print("  Table already exists — skipping DDL.")
else:
    print(f"  Running setup.sql…")
    sql = SQL_FILE.read_text()
    # Supabase doesn't expose a generic SQL endpoint publicly;
    # use the management API if available, otherwise run via psycopg2.
    # For most users: paste setup.sql into the Supabase SQL editor once.
    print("  ⚠  Cannot run DDL automatically via REST API.")
    print("  → Please run supabase/setup.sql in the Supabase SQL editor first,")
    print("     then re-run this script.")
    print(f"  (Got {r.status_code} from table check: {r.text[:80]})")
    sys.exit(1)

# ── Step 2: ensure bucket is public ──────────────────────────────────────────
print("\n=== Step 2: storage bucket ===")
r = session.get(f"{SUPABASE_URL}/storage/v1/bucket/{BUCKET}",
                headers={"Authorization": f"Bearer {SERVICE_KEY}"})
if r.status_code == 200:
    print(f"  Bucket '{BUCKET}' exists.")
else:
    r2 = session.post(f"{SUPABASE_URL}/storage/v1/bucket",
                      json={"id": BUCKET, "name": BUCKET, "public": True},
                      headers={"Authorization": f"Bearer {SERVICE_KEY}",
                               "Content-Type": "application/json"})
    print(f"  Bucket create: {r2.status_code}")

# ── Step 3: curated seed cards ────────────────────────────────────────────────
print("\n=== Step 3: curated cards (seed-cards.json) ===")
seed_cards = json.loads(SEED_FILE.read_text())

for card in seed_cards:
    img_file = card["image_file"]
    local = CONTENT_ROOT / img_file
    if not local.exists():
        local = ASSETS_DIR / pathlib.Path(img_file).name
    if not local.exists():
        print(f"  ✗ missing  {img_file}", file=sys.stderr)
        continue

    if img_file.startswith("arena-sources/"):
        parts = pathlib.Path(img_file).parts
        bucket_path = f"arena/{parts[1]}/{parts[2]}"
    else:
        bucket_path = f"assets/{pathlib.Path(img_file).name}"

    storage_upload(bucket_path, local)
    db_upsert({
        "title":       card["title"],
        "description": card.get("description") or None,
        "source_url":  card.get("source_url") or None,
        "image_path":  bucket_path,
        "section":     card.get("section", "Other References"),
    })

# ── Step 4: arena channel images (auto-titled) ────────────────────────────────
print("\n=== Step 4: arena channel images ===")

# Named files already handled via seed-cards — skip them
seeded_names = set()
for card in seed_cards:
    f = card["image_file"]
    if "arena-sources" in f:
        seeded_names.add(pathlib.Path(f).name)

for channel_dir in sorted(ARENA_DIR.iterdir()):
    if channel_dir.name == "__MACOSX" or not channel_dir.is_dir():
        continue
    channel = channel_dir.name
    section = CHANNEL_SECTION.get(channel, channel)
    title_t = CHANNEL_TITLE.get(channel, f"{channel} {{i}}")
    desc    = CHANNEL_DESC.get(channel, f"Image from the {channel} channel.")

    images = sorted(
        [f for f in channel_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS],
        key=lambda p: p.name,
    )
    idx = 1
    for img in images:
        if img.name in seeded_names:
            print(f"  · skip (seeded)    {img.name}")
            continue
        # Skip numbered files from patterns — they're all already seeded
        # as named files (distorted-text-texture.png, etc.) or are the
        # fragmented-type-collage duplicate.
        if channel == "patterns-dnan2fz7stg":
            print(f"  · skip (patterns)  {img.name}")
            continue

        bucket_path = f"arena/{channel}/{img.name}"
        storage_upload(bucket_path, img)
        db_upsert({
            "title":       title_t.format(i=idx),
            "description": desc,
            "source_url":  None,
            "image_path":  bucket_path,
            "section":     section,
        })
        idx += 1

print("\n=== All done! ===")
print(f"\nGallery URL (after upload): file://…/gallery/index.html")
print(f"Or host gallery/index.html anywhere — it fetches from Supabase.")
