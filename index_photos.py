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


def get_photo_date(path: Path) -> tuple[datetime, bool]:
    """Try Pillow EXIF, then mdls. Returns (datetime, from_exif)."""
    dt = _exif_date_pillow(path) or _exif_date_mdls(path)
    if dt:
        return dt, True
    return datetime.today(), False


def format_date(dt: datetime) -> str:
    """Format datetime as 'April 6'."""
    return dt.strftime("%B %-d")


# ---------------------------------------------------------------------------
# Perceptual hashing (duplicate detection)
# ---------------------------------------------------------------------------

HASH_THRESHOLD = 10  # max Hamming distance (out of 64 bits) to call two photos identical


def _dhash(path: Path, hash_size: int = 8) -> int | None:
    """Difference hash: robust to compression and minor edits. Requires Pillow."""
    try:
        from PIL import Image
        img = Image.open(path).convert("L").resize(
            (hash_size + 1, hash_size), Image.LANCZOS
        )
        pixels = list(img.getdata())
        bits = 0
        for row in range(hash_size):
            for col in range(hash_size):
                left = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        return bits
    except Exception:
        return None


def _hamming(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")


def build_hash_index(manifest: list) -> dict[int, str]:
    """Hash every already-compressed image. Returns {hash: src} map."""
    index: dict[int, str] = {}
    for entry in manifest:
        compressed = SCRIPT_DIR / entry["src"]
        if not compressed.exists():
            continue
        h = _dhash(compressed)
        if h is not None:
            index[h] = entry["src"]
    return index


def find_duplicate(h: int, index: dict[int, str]) -> str | None:
    """Return existing src if a perceptually identical photo is already indexed."""
    for existing_hash, src in index.items():
        if _hamming(h, existing_hash) <= HASH_THRESHOLD:
            return src
    return None


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

    print("Building duplicate index from existing photos...")
    hash_index = build_hash_index(manifest)
    if not hash_index:
        print("  (no existing compressed photos found — skipping duplicate check)")

    new_entries = []
    skipped = 0

    for src in candidates:
        # Derive the output src path relative to repo root
        stem = src.stem
        rel_src = f"assets/compressed/{stem}.jpg"

        # Skip if already indexed by filename
        if rel_src in already_indexed:
            skipped += 1
            continue

        print(f"\n── {src.name} ──────────────────────────────")

        # Check for perceptual duplicate before processing
        incoming_hash = _dhash(src)
        if incoming_hash is not None:
            dup = find_duplicate(incoming_hash, hash_index)
            if dup:
                print(f"  SKIP — duplicate of {dup}")
                skipped += 1
                continue
        elif hash_index:
            print("  (Pillow unavailable — duplicate check skipped)")

        # Compress / convert
        try:
            process_image(src)
        except subprocess.CalledProcessError as e:
            print(f"  ERROR processing {src.name}: {e}")
            continue

        # Date from EXIF — auto-use if found, fall back to today
        dt, from_exif = get_photo_date(src)
        date_str = format_date(dt)
        source = "EXIF" if from_exif else "today (no EXIF)"
        print(f"  Date: {date_str} ({source})")

        new_entries.append({
            "src": rel_src,
            "caption": "",
            "date": date_str,
        })

        # Add to in-memory index so duplicates within this batch are also caught
        if incoming_hash is not None:
            hash_index[incoming_hash] = rel_src

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
