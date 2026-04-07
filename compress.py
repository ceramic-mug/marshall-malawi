#!/usr/bin/env python3
"""Compress a photo in posts/photos/ in place for web use.

Usage:
    python compress.py posts/photos/my-photo.jpg
    python compress.py my-photo.jpg          # assumes posts/photos/ prefix
"""

import os
import sys
import subprocess

MAX_DIM = 1600
QUALITY = 75

def compress(path):
    # Allow bare filename — assume posts/photos/
    if not os.path.dirname(path):
        path = os.path.join("posts", "photos", path)

    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    before = os.path.getsize(path)

    try:
        subprocess.run([
            "sips",
            "-s", "format", "jpeg",
            "-s", "formatOptions", str(QUALITY),
            "-Z", str(MAX_DIM),
            path,
            "--out", path,
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"sips error: {e.stderr.decode().strip()}")
        sys.exit(1)

    after = os.path.getsize(path)
    saved = (before - after) / before * 100
    print(f"{path}: {before // 1024} KB → {after // 1024} KB ({saved:.0f}% smaller)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compress.py <photo>")
        sys.exit(1)
    compress(sys.argv[1])
