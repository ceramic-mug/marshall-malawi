#!/usr/bin/env python3
"""
index_photos.py — Malawi Med photo ingestion tool

Drop photos (HEIC/JPG/PNG/etc.) into an incoming folder, then run:
    python index_photos.py                    # scans photos/incoming/
    python index_photos.py path/to/folder     # scans a custom folder

For each new photo (not already in photos/manifest.json):
  - Converts HEIC → JPG using macOS sips
  - Compresses + resizes to max 1600px, 75% quality
  - Saves to assets/compressed/
  - Extracts EXIF date, prompts you to confirm/override
  - Prompts for an optional caption
  - Prepends entry to photos/manifest.json (newest first)
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to this script's location)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
MANIFEST_PATH = SCRIPT_DIR / "photos" / "manifest.json"
OUTPUT_DIR = SCRIPT_DIR / "assets" / "compressed"
DEFAULT_INCOMING = SCRIPT_DIR / "photos" / "incoming"

IMAGE_EXTENSIONS = {".heic", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}


# ---------------------------------------------------------------------------
# EXIF date extraction
# ---------------------------------------------------------------------------

def _exif_date_pillow(path: Path) -> datetime | None:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        img = Image.open(path)
        exif_data = img._getexif()  # type: ignore[attr-defined]
        if not exif_data:
            return None
        for tag_id, value in exif_data.items():
            if TAGS.get(tag_id) == "DateTimeOriginal":
                return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def _exif_date_mdls(path: Path) -> datetime | None:
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemContentCreationDate", str(path)],
            capture_output=True, text=True, timeout=5
        )
        # Output: kMDItemContentCreationDate = 2026-04-06 12:34:56 +0000
        match = re.search(r"(\d{4}-\d{2}-\d{2})", result.stdout)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
    except Exception:
        pass
    return None


def get_photo_date(path: Path) -> datetime:
    """Try Pillow EXIF, then mdls, then today."""
    dt = _exif_date_pillow(path) or _exif_date_mdls(path)
    return dt or datetime.today()


def format_date(dt: datetime) -> str:
    """Format datetime as 'April 6'."""
    return dt.strftime("%B %-d")


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest() -> list:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return []


def save_manifest(entries: list) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def indexed_srcs(entries: list) -> set:
    return {e["src"] for e in entries}


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------

def process_image(src: Path) -> Path:
    """Convert + compress image to OUTPUT_DIR. Returns output path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    out_path = OUTPUT_DIR / f"{stem}.jpg"

    # If output already exists, don't re-compress
    if out_path.exists():
        print(f"  (compressed file already exists, reusing {out_path.name})")
        return out_path

    print(f"  Compressing {src.name} → assets/compressed/{out_path.name} ...")
    subprocess.run([
        "sips",
        "-s", "format", "jpeg",
        "-s", "formatOptions", "75",
        "-Z", "1600",
        str(src),
        "--out", str(out_path),
    ], check=True, capture_output=True)

    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    incoming_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INCOMING

    if not incoming_dir.exists():
        print(f"Incoming folder not found: {incoming_dir}")
        print("Create it and drop photos inside, then re-run.")
        sys.exit(1)

    # Collect candidate image files
    candidates = sorted(
        p for p in incoming_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not candidates:
        print(f"No image files found in {incoming_dir}")
        sys.exit(0)

    manifest = load_manifest()
    already_indexed = indexed_srcs(manifest)

    new_entries = []
    skipped = 0

    for src in candidates:
        # Derive the output src path relative to repo root
        stem = src.stem
        rel_src = f"assets/compressed/{stem}.jpg"

        if rel_src in already_indexed:
            skipped += 1
            continue

        print(f"\n── {src.name} ──────────────────────────────")

        # Compress / convert
        try:
            process_image(src)
        except subprocess.CalledProcessError as e:
            print(f"  ERROR processing {src.name}: {e}")
            continue

        # Suggest date from EXIF
        dt = get_photo_date(src)
        suggested_date = format_date(dt)

        # Prompt: date
        raw_date = input(f"  Date [{suggested_date}]: ").strip()
        date_str = raw_date if raw_date else suggested_date

        # Prompt: caption
        caption = input("  Caption (optional): ").strip()

        new_entries.append({
            "src": rel_src,
            "caption": caption,
            "date": date_str,
        })

    if not new_entries:
        print(f"\nNo new photos to index ({skipped} already in manifest).")
        return

    # Prepend new entries (newest first) then existing entries
    updated_manifest = new_entries + manifest
    save_manifest(updated_manifest)

    print(f"\nDone! Added {len(new_entries)} photo(s) to photos/manifest.json.")
    if skipped:
        print(f"Skipped {skipped} already-indexed photo(s).")


if __name__ == "__main__":
    main()
