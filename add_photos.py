#!/usr/bin/env python3
"""
add_photos.py — Malawi Med gallery photo ingestor
Run from the repo root: python3 add_photos.py

Requires:
    pip install tkinterdnd2 Pillow
"""
import json
import os
import re
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ── Optional deps ─────────────────────────────────────────────────────────────

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).parent
OUTPUT_DIR  = REPO_ROOT / "assets" / "compressed"
MANIFEST    = REPO_ROOT / "photos" / "manifest.json"
IMAGE_EXTS  = {".heic", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
HEIC_EXTS   = {".heic", ".heif"}
HASH_THRESHOLD = 10


# ── Image helpers ─────────────────────────────────────────────────────────────

def _open_pil_image(path: Path):
    """Open any image as a PIL Image.
    HEIC files are converted to a temp JPEG via sips first (Pillow can't open HEIC)."""
    if not _PIL_AVAILABLE:
        return None
    try:
        if path.suffix.lower() in HEIC_EXTS:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                tmp = Path(f.name)
            try:
                subprocess.run(
                    ["sips", "-s", "format", "jpeg", "-Z", "320",
                     str(path), "--out", str(tmp)],
                    check=True, capture_output=True, timeout=15,
                )
                img = Image.open(tmp)
                img.load()  # read into memory before temp file is deleted
            finally:
                tmp.unlink(missing_ok=True)
            return img
        return Image.open(path)
    except Exception:
        return None


def _dhash(pil_img, hash_size: int = 8) -> int | None:
    """Difference hash of an already-opened PIL Image."""
    if pil_img is None or not _PIL_AVAILABLE:
        return None
    try:
        img = pil_img.convert("L").resize(
            (hash_size + 1, hash_size), Image.LANCZOS
        )
        pixels = list(img.getdata())
        bits = 0
        for row in range(hash_size):
            for col in range(hash_size):
                left  = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                bits  = (bits << 1) | (1 if left > right else 0)
        return bits
    except Exception:
        return None


def _dhash_path(path: Path) -> int | None:
    return _dhash(_open_pil_image(path))


def _hamming(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")


def _find_duplicate(h: int, index: dict[int, str]) -> str | None:
    for eh, src in index.items():
        if _hamming(h, eh) <= HASH_THRESHOLD:
            return src
    return None


# ── EXIF / date helpers ───────────────────────────────────────────────────────

def _exif_date_pillow(pil_img) -> datetime | None:
    if pil_img is None or not _PIL_AVAILABLE:
        return None
    try:
        from PIL.ExifTags import TAGS
        exif_data = pil_img._getexif()  # type: ignore[attr-defined]
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
            capture_output=True, text=True, timeout=5,
        )
        match = re.search(r"(\d{4}-\d{2}-\d{2})", result.stdout)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
    except Exception:
        pass
    return None


def get_photo_date(path: Path, pil_img=None) -> tuple[datetime, bool]:
    """Try Pillow EXIF (from already-opened image), then mdls."""
    dt = _exif_date_pillow(pil_img) or _exif_date_mdls(path)
    if dt:
        return dt, True
    return datetime.today(), False


def format_date(dt: datetime) -> str:
    return dt.strftime("%B %-d")


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _load_manifest() -> list:
    if MANIFEST.exists():
        with open(MANIFEST) as f:
            return json.load(f)
    return []


def _save_manifest(entries: list) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def _build_hash_index(manifest: list) -> dict[int, str]:
    index: dict[int, str] = {}
    for entry in manifest:
        p = REPO_ROOT / entry["src"]
        if not p.exists():
            continue
        h = _dhash_path(p)
        if h is not None:
            index[h] = entry["src"]
    return index


def _file_size_str(path: Path) -> str:
    try:
        b = path.stat().st_size
        return f"{b/1_000_000:.1f} MB" if b >= 1_000_000 else f"{b/1_000:.0f} KB"
    except Exception:
        return "?"


def _parse_drop_data(data: str) -> list[str]:
    """tkinterdnd2 returns space-separated paths; braces wrap paths with spaces."""
    paths: list[str] = []
    i = 0
    while i < len(data):
        if data[i] == "{":
            end = data.index("}", i)
            paths.append(data[i + 1:end])
            i = end + 2
        else:
            end = data.find(" ", i)
            if end == -1:
                paths.append(data[i:])
                break
            paths.append(data[i:end])
            i = end + 1
    return [p for p in paths if p]


# ── Photo card ────────────────────────────────────────────────────────────────

class PhotoCard:
    """One row in the photo queue. Metadata loads asynchronously."""

    def __init__(self, parent: tk.Widget, src: Path, hash_index: dict[int, str],
                 remove_cb, metadata_cb, root: tk.Tk, row: int):
        self.src          = src
        self._remove_cb   = remove_cb
        self._metadata_cb = metadata_cb  # called when async load finishes
        self._root        = root
        self._destroyed   = False
        self._thumbnail_ref = None

        # These are written from background thread, read from main thread only
        # after _apply_metadata is called via after().
        self.file_hash: int | None = None
        self.dup_of:    str | None = None

        self._build_ui(parent, row)

        # Load everything (thumbnail, EXIF, hash) in a background thread
        threading.Thread(
            target=self._load_metadata_bg,
            args=(hash_index,),
            daemon=True,
        ).start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, parent: tk.Widget, row: int):
        self.frame = ttk.Frame(parent, relief="groove", borderwidth=1)
        self.frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        self.frame.columnconfigure(1, weight=1)

        # Thumbnail placeholder
        self._thumb_label = ttk.Label(self.frame, text="…", width=10,
                                       foreground="gray", anchor="center")
        self._thumb_label.grid(row=0, column=0, rowspan=3, padx=(8, 12), pady=8, sticky="n")

        # Filename
        fn_frame = ttk.Frame(self.frame)
        fn_frame.grid(row=0, column=1, sticky="ew", pady=(8, 2))
        fn_frame.columnconfigure(1, weight=1)
        ttk.Label(fn_frame, text="Filename:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_stem = tk.StringVar(value=self.src.stem)
        ttk.Entry(fn_frame, textvariable=self.v_stem, width=32).grid(row=0, column=1, sticky="ew")
        ttk.Label(fn_frame, text=".jpg", foreground="gray").grid(row=0, column=2, padx=(2, 0))

        # Caption
        cap_frame = ttk.Frame(self.frame)
        cap_frame.grid(row=1, column=1, sticky="ew", pady=2)
        cap_frame.columnconfigure(1, weight=1)
        ttk.Label(cap_frame, text="Caption:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_caption = tk.StringVar()
        ttk.Entry(cap_frame, textvariable=self.v_caption, width=40).grid(row=0, column=1, sticky="ew")

        # Date + size info
        info_frame = ttk.Frame(self.frame)
        info_frame.grid(row=2, column=1, sticky="ew", pady=(2, 8))
        info_frame.columnconfigure(1, weight=1)
        ttk.Label(info_frame, text="Date:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_date = tk.StringVar(value="loading…")
        ttk.Entry(info_frame, textvariable=self.v_date, width=16).grid(row=0, column=1, sticky="w")
        self._info_label = ttk.Label(info_frame, text=_file_size_str(self.src), foreground="gray")
        self._info_label.grid(row=0, column=2, padx=(12, 0), sticky="w")

        # Remove button
        ttk.Button(self.frame, text="✕ Remove", command=self._remove).grid(
            row=0, column=2, padx=(8, 8), pady=(8, 2), sticky="ne")

        # Duplicate warning slot (added later if needed)
        self._dup_label: ttk.Label | None = None

    # ── Background metadata load ──────────────────────────────────────────────

    def _load_metadata_bg(self, hash_index: dict[int, str]):
        """Runs in a daemon thread. Opens image once for all metadata."""
        pil_img = _open_pil_image(self.src)

        # EXIF date (try Pillow EXIF on the opened image, then mdls)
        dt, from_meta = get_photo_date(self.src, pil_img)
        date_str = format_date(dt)
        date_hint = "" if from_meta else " (estimated)"

        # Perceptual hash + duplicate check
        h   = _dhash(pil_img)
        dup = _find_duplicate(h, hash_index) if h is not None else None

        # PIL thumbnail resize (ImageTk must be created on main thread)
        thumb_pil = None
        if pil_img is not None:
            try:
                t = pil_img.copy()
                t.thumbnail((80, 80), Image.LANCZOS)
                thumb_pil = t
            except Exception:
                pass

        if not self._destroyed:
            self._root.after(0, lambda: self._apply_metadata(
                date_str, date_hint, h, dup, thumb_pil))

    def _apply_metadata(self, date_str: str, date_hint: str,
                        h: int | None, dup: str | None, thumb_pil):
        if self._destroyed:
            return

        self.file_hash = h
        self.dup_of    = dup

        # Update date entry
        self.v_date.set(date_str)
        if date_hint:
            cur = self._info_label.cget("text")
            self._info_label.config(text=f"{cur}{date_hint}")

        # Update thumbnail
        if thumb_pil is not None and _PIL_AVAILABLE:
            try:
                tk_img = ImageTk.PhotoImage(thumb_pil)
                self._thumbnail_ref = tk_img
                self._thumb_label.config(image=tk_img, text="")
            except Exception:
                pass
        elif thumb_pil is None:
            self._thumb_label.config(text="?")

        # Duplicate warning
        if dup and self._dup_label is None:
            self._dup_label = ttk.Label(
                self.frame,
                text=f"⚠  Duplicate of {dup}",
                foreground="#cc6600",
            )
            self._dup_label.grid(row=3, column=1, columnspan=2, sticky="w", pady=(0, 6))

        self._metadata_cb()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _remove(self):
        self._destroyed = True
        self.frame.destroy()
        self._remove_cb(self)

    @property
    def stem(self) -> str:
        return self.v_stem.get().strip() or self.src.stem

    @property
    def caption(self) -> str:
        return self.v_caption.get().strip()

    @property
    def date(self) -> str:
        return self.v_date.get().strip() or format_date(datetime.today())

    @property
    def is_duplicate(self) -> bool:
        return self.dup_of is not None


# ── Main app ──────────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        if _DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("Add Photos — Malawi Med Gallery")
        self.root.configure(bg="#f0f0f0")
        self.root.minsize(600, 400)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._cards: list[PhotoCard] = []
        self._manifest: list = _load_manifest()
        self._hash_index: dict[int, str] = {}

        # Build hash index of existing gallery photos in background
        threading.Thread(target=self._build_index, daemon=True).start()

        self._build_ui()

    def _build_index(self):
        self._hash_index = _build_hash_index(self._manifest)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Drop zone
        dz_border = tk.Frame(self.root, bg="#c0c0c0")
        dz_border.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        dz_border.columnconfigure(0, weight=1)

        dz_bg = "#e8f5ee"
        dz = tk.Frame(dz_border, bg=dz_bg, height=100, cursor="hand2")
        dz.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        dz.columnconfigure(0, weight=1)
        dz.pack_propagate(False)

        label_text = (
            "Drop photos here\nor click to browse"
            if _DND_AVAILABLE else
            "Click to browse photos\n(install tkinterdnd2 for drag-and-drop)"
        )
        dz_label = tk.Label(
            dz, text=label_text,
            bg=dz_bg, fg="#2d6a4f",
            font=("Helvetica", 13),
            justify="center",
        )
        dz_label.pack(expand=True, fill="both", padx=16, pady=16)

        if _DND_AVAILABLE:
            for widget in (dz, dz_label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        dz.bind("<Button-1>", lambda _: self._browse())
        dz_label.bind("<Button-1>", lambda _: self._browse())

        # Scrollable queue
        queue_outer = ttk.Frame(self.root)
        queue_outer.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        queue_outer.columnconfigure(0, weight=1)
        queue_outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(queue_outer, highlightthickness=0, bg="#f0f0f0")
        scrollbar = ttk.Scrollbar(queue_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._queue_frame = ttk.Frame(canvas)
        self._queue_frame.columnconfigure(0, weight=1)
        win = canvas.create_window((0, 0), window=self._queue_frame, anchor="nw")

        self._queue_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * e.delta / 120), "units"))

        self._empty_label = ttk.Label(
            self._queue_frame, text="No photos added yet", foreground="gray")
        self._empty_label.grid(row=0, column=0, pady=24)

        # Bottom bar
        bottom = ttk.Frame(self.root, padding=(12, 6, 12, 12))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)

        ttk.Button(bottom, text="Process & Add to Gallery",
                   command=self._process).grid(row=0, column=0, padx=(0, 12))

        self._status_var = tk.StringVar(value="No photos queued")
        ttk.Label(bottom, textvariable=self._status_var,
                  foreground="gray").grid(row=0, column=1, sticky="w")

        if not _PIL_AVAILABLE:
            ttk.Label(
                bottom,
                text="Pillow not installed — thumbnails and duplicate detection unavailable",
                foreground="#cc0000",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_drop(self, event):
        paths = _parse_drop_data(event.data)
        valid = [Path(p) for p in paths if Path(p).suffix.lower() in IMAGE_EXTS]
        if valid:
            self._add_photos(valid)

    def _browse(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        paths = filedialog.askopenfilenames(
            title="Select photos",
            filetypes=[("Images", exts), ("All files", "*.*")],
        )
        if paths:
            self._add_photos([Path(p) for p in paths])

    def _add_photos(self, paths: list[Path]):
        existing = {c.src.resolve() for c in self._cards}
        new_paths = [p for p in paths if p.resolve() not in existing]
        if not new_paths:
            return

        self._empty_label.grid_remove()

        for path in new_paths:
            row = len(self._cards)
            card = PhotoCard(
                self._queue_frame, path, self._hash_index,
                remove_cb=self._remove_card,
                metadata_cb=self._update_status,
                root=self.root,
                row=row,
            )
            self._cards.append(card)

        self._update_status()

    def _remove_card(self, card: PhotoCard):
        self._cards.remove(card)
        for i, c in enumerate(self._cards):
            c.frame.grid(row=i, column=0, sticky="ew", padx=8, pady=4)
        if not self._cards:
            self._empty_label.grid(row=0, column=0, pady=24)
        self._update_status()

    def _update_status(self):
        total = len(self._cards)
        dups  = sum(1 for c in self._cards if c.is_duplicate)
        ready = total - dups
        if total == 0:
            self._status_var.set("No photos queued")
        elif dups:
            self._status_var.set(
                f"{ready} photo{'s' if ready != 1 else ''} ready  ·  "
                f"{dups} duplicate{'s' if dups != 1 else ''} (will be skipped)")
        else:
            self._status_var.set(
                f"{ready} photo{'s' if ready != 1 else ''} ready")

    # ── Process ───────────────────────────────────────────────────────────────

    def _process(self):
        if not self._cards:
            messagebox.showinfo("No photos", "Add some photos first.")
            return

        to_process = [c for c in self._cards if not c.is_duplicate]
        if not to_process:
            messagebox.showinfo(
                "All duplicates",
                "All queued photos are duplicates of existing gallery photos.",
            )
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        added:  list[dict] = []
        errors: list[str]  = []

        for card in to_process:
            dest = OUTPUT_DIR / f"{card.stem}.jpg"

            if dest.exists():
                rel = f"assets/compressed/{dest.name}"
                if rel not in {e["src"] for e in self._manifest}:
                    if not messagebox.askyesno(
                        "File exists",
                        f"{dest.name} already exists in assets/compressed/.\nOverwrite?",
                    ):
                        continue

            try:
                subprocess.run(
                    ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "75",
                     "-Z", "1600", str(card.src), "--out", str(dest)],
                    check=True, capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                errors.append(f"{card.src.name}: {e.stderr.decode().strip() or str(e)}")
                continue

            entry = {
                "src":     f"assets/compressed/{dest.name}",
                "caption": card.caption,
                "date":    card.date,
            }
            added.append(entry)

            h = card.file_hash
            if h is not None:
                self._hash_index[h] = entry["src"]

        if added:
            updated = added + self._manifest
            _save_manifest(updated)
            self._manifest = updated

        msg_parts = []
        if added:
            msg_parts.append(
                f"Added {len(added)} photo{'s' if len(added) != 1 else ''} "
                f"to photos/manifest.json")
        if errors:
            msg_parts.append(f"\nErrors ({len(errors)}):\n" + "\n".join(errors))
        messagebox.showinfo("Done", "\n".join(msg_parts) or "Nothing to do.")

        # Clear successfully processed cards; keep duplicates
        processed = {c.src for c in to_process}
        for c in to_process:
            c._destroyed = True
            c.frame.destroy()
        self._cards = [c for c in self._cards if c.src not in processed]
        for i, c in enumerate(self._cards):
            c.frame.grid(row=i, column=0, sticky="ew", padx=8, pady=4)
        if not self._cards:
            self._empty_label.grid(row=0, column=0, pady=24)
        self._update_status()

    def run(self):
        self.root.mainloop()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _DND_AVAILABLE:
        print(
            "Note: tkinterdnd2 not found. Drag-and-drop disabled.\n"
            "Install with: pip install tkinterdnd2\n"
        )
    if not _PIL_AVAILABLE:
        print(
            "Note: Pillow not found. Thumbnails and duplicate detection disabled.\n"
            "Install with: pip install Pillow\n"
        )
    App().run()
