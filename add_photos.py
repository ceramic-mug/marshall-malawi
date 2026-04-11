#!/usr/bin/env python3
"""
add_photos.py — Malawi Med gallery manager
  Add Photos  — drag-and-drop ingestion, compression, manifest update
  Edit Gallery — rotate/caption/date/remove existing gallery photos

Run from the repo root: python3 add_photos.py
Requires: pip install tkinterdnd2 Pillow
"""
import json
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
    from PIL import Image, ImageOps, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT      = Path(__file__).parent
OUTPUT_DIR     = REPO_ROOT / "assets" / "compressed"
MANIFEST       = REPO_ROOT / "photos" / "manifest.json"
IMAGE_EXTS     = {".heic", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
HEIC_EXTS      = {".heic", ".heif"}
HASH_THRESHOLD = 10


# ── Image helpers ─────────────────────────────────────────────────────────────

def _open_pil_image(path: Path):
    """Open any image as PIL. HEIC converted via sips to a temp JPEG first."""
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
                img.load()
            finally:
                tmp.unlink(missing_ok=True)
            return img
        return Image.open(path)
    except Exception:
        return None


def _make_thumb_base(pil_img, size: int = 80):
    """Return EXIF-corrected + resized PIL image ready for display, or None."""
    if pil_img is None or not _PIL_AVAILABLE:
        return None
    try:
        oriented = ImageOps.exif_transpose(pil_img)
    except Exception:
        oriented = pil_img
    try:
        t = oriented.copy()
        t.thumbnail((size, size), Image.LANCZOS)
        return t
    except Exception:
        return None


def _render_thumb(thumb_base, rotation: int = 0):
    """Return ImageTk.PhotoImage from thumb_base at given CW rotation. Call on main thread."""
    if thumb_base is None or not _PIL_AVAILABLE:
        return None
    try:
        img = thumb_base.rotate(-rotation, expand=True)  # PIL rotates CCW; negate for CW
        img.thumbnail((80, 80), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def _dhash(pil_img, hash_size: int = 8) -> int | None:
    if pil_img is None or not _PIL_AVAILABLE:
        return None
    try:
        img = pil_img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
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
        exif = pil_img._getexif()  # type: ignore[attr-defined]
        if not exif:
            return None
        for tag_id, value in exif.items():
            if TAGS.get(tag_id) == "DateTimeOriginal":
                return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def _exif_date_mdls(path: Path) -> datetime | None:
    try:
        r = subprocess.run(
            ["mdls", "-name", "kMDItemContentCreationDate", str(path)],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"(\d{4}-\d{2}-\d{2})", r.stdout)
        if m:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
    except Exception:
        pass
    return None


def get_photo_date(path: Path, pil_img=None) -> tuple[datetime, bool]:
    dt = _exif_date_pillow(pil_img) or _exif_date_mdls(path)
    return (dt, True) if dt else (datetime.today(), False)


def format_date(dt: datetime) -> str:
    return dt.strftime("%B %-d")


def _manifest_sort_key(entry: dict) -> tuple:
    """Sort key for manifest entries: newest date first, unparseable (Pre-trip etc.) last."""
    try:
        # Append dummy year to avoid year-less parsing deprecation (Python 3.15+)
        dt = datetime.strptime(entry.get("date", "").strip() + " 2000", "%B %d %Y")
        return (0, -(dt.month * 100 + dt.day))
    except ValueError:
        return (1, 0)


def _sorted_manifest(entries: list) -> list:
    return sorted(entries, key=_manifest_sort_key)


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


def _make_scrollable(parent: tk.Widget) -> tuple[tk.Canvas, ttk.Frame]:
    """Return (canvas, inner_frame) for a scrollable area inside parent."""
    outer = ttk.Frame(parent)
    outer.grid(sticky="nsew")
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    canvas = tk.Canvas(outer, highlightthickness=0, bg="#f0f0f0")
    sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    inner = ttk.Frame(canvas)
    inner.columnconfigure(0, weight=1)
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
    return canvas, inner


# ── Shared thumbnail column ───────────────────────────────────────────────────

def _build_thumb_col(parent: tk.Widget, on_ccw, on_cw):
    """Build thumbnail + ↺/↻ column. Returns (container, thumb_label, btn_ccw, btn_cw)."""
    col = ttk.Frame(parent)
    lbl = ttk.Label(col, text="…", width=10, foreground="gray", anchor="center")
    lbl.grid(row=0, column=0, columnspan=2, pady=(0, 4))
    btn_ccw = ttk.Button(col, text="↺", width=3, state="disabled", command=on_ccw)
    btn_ccw.grid(row=1, column=0, padx=(0, 1))
    btn_cw  = ttk.Button(col, text="↻", width=3, state="disabled", command=on_cw)
    btn_cw.grid(row=1, column=1)
    return col, lbl, btn_ccw, btn_cw


# ── PhotoCard — incoming photo in Add tab ─────────────────────────────────────

class PhotoCard:
    def __init__(self, parent: tk.Widget, src: Path, hash_index: dict[int, str],
                 remove_cb, metadata_cb, root: tk.Tk, row: int):
        self.src            = src
        self._remove_cb     = remove_cb
        self._metadata_cb   = metadata_cb
        self._root          = root
        self._destroyed     = False
        self._thumbnail_ref = None
        self._thumb_base    = None
        self._rotation      = 0
        self.file_hash: int | None = None
        self.dup_of:    str | None = None

        self._build_ui(parent, row)
        threading.Thread(target=self._load_bg, args=(hash_index,), daemon=True).start()

    def _build_ui(self, parent: tk.Widget, row: int):
        self.frame = ttk.Frame(parent, relief="groove", borderwidth=1)
        self.frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        self.frame.columnconfigure(1, weight=1)

        col, self._thumb_label, self._btn_ccw, self._btn_cw = _build_thumb_col(
            self.frame, lambda: self._rotate(-90), lambda: self._rotate(90))
        col.grid(row=0, column=0, rowspan=3, padx=(8, 12), pady=8, sticky="n")

        fn = ttk.Frame(self.frame)
        fn.grid(row=0, column=1, sticky="ew", pady=(8, 2))
        fn.columnconfigure(1, weight=1)
        ttk.Label(fn, text="Filename:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_stem = tk.StringVar(value=self.src.stem)
        ttk.Entry(fn, textvariable=self.v_stem, width=32).grid(row=0, column=1, sticky="ew")
        ttk.Label(fn, text=".jpg", foreground="gray").grid(row=0, column=2, padx=(2, 0))

        cap = ttk.Frame(self.frame)
        cap.grid(row=1, column=1, sticky="ew", pady=2)
        cap.columnconfigure(1, weight=1)
        ttk.Label(cap, text="Caption:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_caption = tk.StringVar()
        ttk.Entry(cap, textvariable=self.v_caption, width=40).grid(row=0, column=1, sticky="ew")

        inf = ttk.Frame(self.frame)
        inf.grid(row=2, column=1, sticky="ew", pady=(2, 8))
        inf.columnconfigure(1, weight=1)
        ttk.Label(inf, text="Date:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_date = tk.StringVar(value="loading…")
        ttk.Entry(inf, textvariable=self.v_date, width=16).grid(row=0, column=1, sticky="w")
        self._info_lbl = ttk.Label(inf, text=_file_size_str(self.src), foreground="gray")
        self._info_lbl.grid(row=0, column=2, padx=(12, 0), sticky="w")

        ttk.Button(self.frame, text="✕ Remove", command=self._remove).grid(
            row=0, column=2, padx=(8, 8), pady=(8, 2), sticky="ne")
        self._dup_label: ttk.Label | None = None

    def _load_bg(self, hash_index: dict[int, str]):
        pil_img   = _open_pil_image(self.src)
        dt, found = get_photo_date(self.src, pil_img)
        date_str  = format_date(dt)
        date_hint = "" if found else " (estimated)"
        h         = _dhash(pil_img)
        dup       = _find_duplicate(h, hash_index) if h is not None else None
        thumb     = _make_thumb_base(pil_img)
        if not self._destroyed:
            self._root.after(0, lambda: self._apply(date_str, date_hint, h, dup, thumb))

    def _apply(self, date_str, date_hint, h, dup, thumb):
        if self._destroyed:
            return
        self.file_hash = h
        self.dup_of    = dup
        self._thumb_base = thumb
        self.v_date.set(date_str)
        if date_hint:
            self._info_lbl.config(text=f"{self._info_lbl.cget('text')}{date_hint}")
        if thumb is not None:
            self._refresh_thumb()
            self._btn_ccw.config(state="normal")
            self._btn_cw.config(state="normal")
        else:
            self._thumb_label.config(text="?")
        if dup and self._dup_label is None:
            self._dup_label = ttk.Label(self.frame,
                text=f"⚠  Duplicate of {dup}", foreground="#cc6600")
            self._dup_label.grid(row=3, column=1, columnspan=2, sticky="w", pady=(0, 6))
        self._metadata_cb()

    def _rotate(self, delta: int):
        self._rotation = (self._rotation + delta) % 360
        self._refresh_thumb()

    def _refresh_thumb(self):
        tk_img = _render_thumb(self._thumb_base, self._rotation)
        if tk_img:
            self._thumbnail_ref = tk_img
            self._thumb_label.config(image=tk_img, text="")

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


# ── GalleryCard — existing photo in Edit tab ──────────────────────────────────

class GalleryCard:
    def __init__(self, parent: tk.Widget, entry: dict, root: tk.Tk, row: int):
        self.entry          = entry
        self.src            = REPO_ROOT / entry["src"]
        self._root          = root
        self._destroyed     = False
        self._thumbnail_ref = None
        self._thumb_base    = None
        self._rotation      = 0       # CW degrees to apply on save
        self.marked_removal = False

        self.v_caption = tk.StringVar(value=entry.get("caption", ""))
        self.v_date    = tk.StringVar(value=entry.get("date", ""))

        self._build_ui(parent, row)
        threading.Thread(target=self._load_thumb_bg, daemon=True).start()

    def _build_ui(self, parent: tk.Widget, row: int):
        self.frame = ttk.Frame(parent, relief="groove", borderwidth=1)
        self.frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        self.frame.columnconfigure(1, weight=1)

        col, self._thumb_label, self._btn_ccw, self._btn_cw = _build_thumb_col(
            self.frame, lambda: self._rotate(-90), lambda: self._rotate(90))
        col.grid(row=0, column=0, rowspan=3, padx=(8, 12), pady=8, sticky="n")

        # Filename (read-only display)
        fn = ttk.Frame(self.frame)
        fn.grid(row=0, column=1, sticky="ew", pady=(8, 2))
        fn.columnconfigure(1, weight=1)
        ttk.Label(fn, text="File:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(fn, text=self.src.name, foreground="#444").grid(
            row=0, column=1, sticky="w")
        ttk.Label(fn, text=_file_size_str(self.src),
                  foreground="gray").grid(row=0, column=2, padx=(12, 0))

        # Caption
        cap = ttk.Frame(self.frame)
        cap.grid(row=1, column=1, sticky="ew", pady=2)
        cap.columnconfigure(1, weight=1)
        ttk.Label(cap, text="Caption:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(cap, textvariable=self.v_caption, width=40).grid(row=0, column=1, sticky="ew")

        # Date
        dt_f = ttk.Frame(self.frame)
        dt_f.grid(row=2, column=1, sticky="ew", pady=(2, 8))
        ttk.Label(dt_f, text="Date:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(dt_f, textvariable=self.v_date, width=16).grid(row=0, column=1, sticky="w")

        # Remove / Restore button
        self._remove_btn = ttk.Button(
            self.frame, text="Remove", command=self._toggle_removal)
        self._remove_btn.grid(row=0, column=2, padx=(8, 8), pady=(8, 2), sticky="ne")

        # Removal banner (hidden until marked)
        self._removal_banner = ttk.Label(
            self.frame,
            text="⚠  Marked for removal — will be deleted when you Save Changes",
            foreground="#cc0000",
        )

    def _load_thumb_bg(self):
        pil_img = _open_pil_image(self.src)
        thumb   = _make_thumb_base(pil_img)
        if not self._destroyed:
            self._root.after(0, lambda: self._set_thumb(thumb))

    def _set_thumb(self, thumb):
        if self._destroyed:
            return
        self._thumb_base = thumb
        if thumb is not None:
            self._refresh_thumb()
            self._btn_ccw.config(state="normal")
            self._btn_cw.config(state="normal")
        else:
            self._thumb_label.config(text="?")

    def _rotate(self, delta: int):
        self._rotation = (self._rotation + delta) % 360
        self._refresh_thumb()

    def _refresh_thumb(self):
        tk_img = _render_thumb(self._thumb_base, self._rotation)
        if tk_img:
            self._thumbnail_ref = tk_img
            self._thumb_label.config(image=tk_img, text="")

    def _toggle_removal(self):
        self.marked_removal = not self.marked_removal
        if self.marked_removal:
            self._remove_btn.config(text="Restore")
            self._removal_banner.grid(
                row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 6))
        else:
            self._remove_btn.config(text="Remove")
            self._removal_banner.grid_remove()

    @property
    def updated_entry(self) -> dict:
        return {
            "src":     self.entry["src"],
            "caption": self.v_caption.get().strip(),
            "date":    self.v_date.get().strip(),
        }


# ── App ───────────────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        if _DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("Malawi Med Gallery")
        self.root.configure(bg="#f0f0f0")
        self.root.minsize(640, 500)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Shared state
        self._manifest:   list           = _load_manifest()
        self._hash_index: dict[int, str] = {}

        # Add tab state
        self._cards:       list[PhotoCard]   = []
        self._add_canvas:  tk.Canvas | None  = None

        # Edit tab state
        self._gallery_cards: list[GalleryCard] = []
        self._edit_canvas:   tk.Canvas | None  = None
        self._edit_loaded    = False

        threading.Thread(target=self._build_hash_index_bg, daemon=True).start()
        self._build_ui()

    def _build_hash_index_bg(self):
        self._hash_index = _build_hash_index(self._manifest)

    # ── Top-level UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self._notebook = nb

        add_frame  = ttk.Frame(nb)
        edit_frame = ttk.Frame(nb)
        add_frame.columnconfigure(0, weight=1)
        add_frame.rowconfigure(1, weight=1)
        edit_frame.columnconfigure(0, weight=1)
        edit_frame.rowconfigure(0, weight=1)

        nb.add(add_frame,  text="Add Photos")
        nb.add(edit_frame, text="Edit Gallery")

        self._build_add_tab(add_frame)
        self._build_edit_tab(edit_frame)

        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

        # Single global mousewheel handler — scrolls whichever canvas is active
        self._active_canvas: tk.Canvas = self._add_canvas
        self.root.bind_all("<MouseWheel>",
            lambda e: self._active_canvas.yview_scroll(
                int(-1 * e.delta / 120), "units"))

    def _on_tab_change(self, _event=None):
        tab = self._notebook.tab(self._notebook.select(), "text")
        if tab == "Edit Gallery":
            self._active_canvas = self._edit_canvas
            if not self._edit_loaded:
                self._load_gallery_tab()
        else:
            self._active_canvas = self._add_canvas

    # ── Add Photos tab ────────────────────────────────────────────────────────

    def _build_add_tab(self, parent: ttk.Frame):
        # Drop zone
        dz_border = tk.Frame(parent, bg="#c0c0c0")
        dz_border.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        dz_border.columnconfigure(0, weight=1)

        dz_bg = "#e8f5ee"
        dz = tk.Frame(dz_border, bg=dz_bg, height=90, cursor="hand2")
        dz.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        dz.columnconfigure(0, weight=1)
        dz.pack_propagate(False)

        dz_lbl = tk.Label(
            dz,
            text="Drop photos here — or click to browse\nJPG · PNG · HEIC  (multi-file OK)"
                 if _DND_AVAILABLE else
                 "Click to browse photos  (install tkinterdnd2 for drag-and-drop)",
            bg=dz_bg, fg="#2d6a4f", font=("Helvetica", 13), justify="center",
        )
        dz_lbl.pack(expand=True, fill="both", padx=16, pady=12)

        if _DND_AVAILABLE:
            for w in (dz, dz_lbl):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
        dz.bind("<Button-1>", lambda _: self._browse())
        dz_lbl.bind("<Button-1>", lambda _: self._browse())

        # Scrollable queue
        queue_outer = ttk.Frame(parent)
        queue_outer.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        queue_outer.columnconfigure(0, weight=1)
        queue_outer.rowconfigure(0, weight=1)

        self._add_canvas, self._queue_frame = _make_scrollable(queue_outer)

        self._add_empty = ttk.Label(
            self._queue_frame, text="No photos queued", foreground="gray")
        self._add_empty.grid(row=0, column=0, pady=24)

        # Bottom bar
        bot = ttk.Frame(parent, padding=(12, 6, 12, 12))
        bot.grid(row=2, column=0, sticky="ew")
        bot.columnconfigure(1, weight=1)

        ttk.Button(bot, text="Process & Add to Gallery",
                   command=self._process).grid(row=0, column=0, padx=(0, 12))
        self._add_status = tk.StringVar(value="No photos queued")
        ttk.Label(bot, textvariable=self._add_status, foreground="gray").grid(
            row=0, column=1, sticky="w")

        if not _PIL_AVAILABLE:
            ttk.Label(bot,
                text="Pillow not installed — thumbnails and duplicate detection unavailable",
                foreground="#cc0000",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    # ── Edit Gallery tab ──────────────────────────────────────────────────────

    def _build_edit_tab(self, parent: ttk.Frame):
        # Scrollable gallery list
        gallery_outer = ttk.Frame(parent)
        gallery_outer.grid(row=0, column=0, sticky="nsew", padx=12, pady=(8, 4))
        gallery_outer.columnconfigure(0, weight=1)
        gallery_outer.rowconfigure(0, weight=1)

        self._edit_canvas, self._edit_frame = _make_scrollable(gallery_outer)

        self._edit_empty = ttk.Label(
            self._edit_frame, text="No photos in gallery", foreground="gray")
        self._edit_empty.grid(row=0, column=0, pady=24)

        # Bottom bar
        bot = ttk.Frame(parent, padding=(12, 6, 12, 12))
        bot.grid(row=1, column=0, sticky="ew")
        bot.columnconfigure(2, weight=1)

        ttk.Button(bot, text="Save Changes",
                   command=self._save_gallery).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(bot, text="Reload Gallery",
                   command=self._reload_gallery).grid(row=0, column=1, padx=(0, 12))
        self._edit_status = tk.StringVar(value="")
        ttk.Label(bot, textvariable=self._edit_status, foreground="gray").grid(
            row=0, column=2, sticky="w")

    def _load_gallery_tab(self):
        """Populate Edit tab from self._manifest. Clears any existing cards."""
        for c in self._gallery_cards:
            c._destroyed = True
            c.frame.destroy()
        self._gallery_cards = []

        if not self._manifest:
            self._edit_empty.grid(row=0, column=0, pady=24)
            self._edit_status.set("Gallery is empty")
            self._edit_loaded = True
            return

        self._edit_empty.grid_remove()
        for i, entry in enumerate(self._manifest):
            card = GalleryCard(self._edit_frame, entry, self.root, row=i)
            self._gallery_cards.append(card)

        self._edit_status.set(f"{len(self._gallery_cards)} photos")
        self._edit_loaded = True

    def _reload_gallery(self):
        pending = any(c.marked_removal or c._rotation != 0 for c in self._gallery_cards)
        if pending:
            if not messagebox.askyesno(
                "Unsaved changes",
                "You have unsaved changes in the gallery editor.\n"
                "Reload and discard them?",
            ):
                return
        self._manifest = _load_manifest()
        self._load_gallery_tab()

    # ── Add Photos — events ───────────────────────────────────────────────────

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
        new = [p for p in paths if p.resolve() not in existing]
        if not new:
            return
        self._add_empty.grid_remove()
        for path in new:
            row  = len(self._cards)
            card = PhotoCard(
                self._queue_frame, path, self._hash_index,
                remove_cb=self._remove_card,
                metadata_cb=self._update_add_status,
                root=self.root, row=row,
            )
            self._cards.append(card)
        self._update_add_status()

    def _remove_card(self, card: PhotoCard):
        self._cards.remove(card)
        for i, c in enumerate(self._cards):
            c.frame.grid(row=i, column=0, sticky="ew", padx=8, pady=4)
        if not self._cards:
            self._add_empty.grid(row=0, column=0, pady=24)
        self._update_add_status()

    def _update_add_status(self):
        total = len(self._cards)
        dups  = sum(1 for c in self._cards if c.is_duplicate)
        ready = total - dups
        if total == 0:
            self._add_status.set("No photos queued")
        elif dups:
            self._add_status.set(
                f"{ready} ready  ·  {dups} duplicate{'s' if dups != 1 else ''} (skipped)")
        else:
            self._add_status.set(f"{ready} photo{'s' if ready != 1 else ''} ready")

    # ── Add Photos — process ──────────────────────────────────────────────────

    def _process(self):
        if not self._cards:
            messagebox.showinfo("No photos", "Add some photos first.")
            return
        to_process = [c for c in self._cards if not c.is_duplicate]
        if not to_process:
            messagebox.showinfo("All duplicates",
                "All queued photos are duplicates of existing gallery photos.")
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
                        f"{dest.name} already exists.\nOverwrite?",
                    ):
                        continue
            try:
                subprocess.run(
                    ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "75",
                     "-Z", "1600", str(card.src), "--out", str(dest)],
                    check=True, capture_output=True,
                )
                if card._rotation != 0:
                    subprocess.run(
                        ["sips", "--rotate", str(card._rotation), str(dest)],
                        check=True, capture_output=True,
                    )
            except subprocess.CalledProcessError as e:
                errors.append(f"{card.src.name}: {e.stderr.decode().strip() or str(e)}")
                continue

            entry = {"src": f"assets/compressed/{dest.name}",
                     "caption": card.caption, "date": card.date}
            added.append(entry)
            if card.file_hash is not None:
                self._hash_index[card.file_hash] = entry["src"]

        if added:
            self._manifest = _sorted_manifest(added + self._manifest)
            _save_manifest(self._manifest)
            self._edit_loaded = False  # mark Edit tab stale

        parts = []
        if added:
            parts.append(f"Added {len(added)} photo{'s' if len(added) != 1 else ''}")
        if errors:
            parts.append(f"Errors ({len(errors)}):\n" + "\n".join(errors))
        messagebox.showinfo("Done", "\n".join(parts) or "Nothing to do.")

        processed = {c.src for c in to_process}
        for c in to_process:
            c._destroyed = True
            c.frame.destroy()
        self._cards = [c for c in self._cards if c.src not in processed]
        for i, c in enumerate(self._cards):
            c.frame.grid(row=i, column=0, sticky="ew", padx=8, pady=4)
        if not self._cards:
            self._add_empty.grid(row=0, column=0, pady=24)
        self._update_add_status()

    # ── Edit Gallery — save ───────────────────────────────────────────────────

    def _save_gallery(self):
        if not self._gallery_cards:
            messagebox.showinfo("Nothing to save", "Gallery is empty.")
            return

        to_remove = [c for c in self._gallery_cards if c.marked_removal]
        to_keep   = [c for c in self._gallery_cards if not c.marked_removal]
        to_rotate = [c for c in to_keep if c._rotation != 0]

        # Confirm file deletion
        delete_files = False
        if to_remove:
            names = "\n".join(f"  • {c.src.name}" for c in to_remove[:6])
            if len(to_remove) > 6:
                names += f"\n  … and {len(to_remove) - 6} more"
            delete_files = messagebox.askyesno(
                f"Remove {len(to_remove)} photo{'s' if len(to_remove) != 1 else ''}",
                f"{names}\n\nAlso delete these files from assets/compressed/?",
            )

        errors: list[str] = []

        # Apply rotations in-place on compressed files
        for card in to_rotate:
            try:
                subprocess.run(
                    ["sips", "--rotate", str(card._rotation), str(card.src)],
                    check=True, capture_output=True,
                )
                card._rotation = 0
                card._thumb_base = None  # force thumb reload next time
            except subprocess.CalledProcessError:
                errors.append(f"Rotation failed: {card.src.name}")

        # Delete files
        for card in to_remove:
            if delete_files:
                try:
                    card.src.unlink(missing_ok=True)
                except Exception:
                    errors.append(f"Delete failed: {card.src.name}")

        # Rebuild manifest, sorted newest-first
        self._manifest = _sorted_manifest([c.updated_entry for c in to_keep])
        _save_manifest(self._manifest)

        # Remove marked cards from UI
        for c in to_remove:
            c._destroyed = True
            c.frame.destroy()
        self._gallery_cards = to_keep
        for i, c in enumerate(self._gallery_cards):
            c.frame.grid(row=i, column=0, sticky="ew", padx=8, pady=4)
        if not self._gallery_cards:
            self._edit_empty.grid(row=0, column=0, pady=24)

        self._edit_status.set(f"{len(self._gallery_cards)} photos")

        parts = []
        if to_remove:
            parts.append(f"{len(to_remove)} removed")
        if to_rotate:
            parts.append(f"{len(to_rotate)} rotated")
        parts.append("manifest saved")
        summary = ", ".join(parts).capitalize() + "."

        if errors:
            messagebox.showwarning("Saved with errors", summary + "\n\n" + "\n".join(errors))
        else:
            messagebox.showinfo("Saved", summary)

    def run(self):
        self.root.mainloop()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _DND_AVAILABLE:
        print("Note: tkinterdnd2 not found. Drag-and-drop disabled.\n"
              "Install with: pip install tkinterdnd2\n")
    if not _PIL_AVAILABLE:
        print("Note: Pillow not found. Thumbnails and duplicate detection disabled.\n"
              "Install with: pip install Pillow\n")
    App().run()
