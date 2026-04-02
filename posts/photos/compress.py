#!/usr/bin/env python3
import os
import subprocess

photos_dir = os.path.dirname(os.path.abspath(__file__))

filename = input("Photo filename: ").strip()
filepath = os.path.join(photos_dir, filename)

if not os.path.exists(filepath):
    print(f"File not found: {filepath}")
    exit(1)

subprocess.run([
    "sips",
    "-s", "format", "jpeg",
    "-s", "formatOptions", "75",
    "-Z", "1600",
    filepath,
    "--out", filepath
], check=True)

print(f"Done: {filename}")
