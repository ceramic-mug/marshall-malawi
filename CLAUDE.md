# Malawi Med — CLAUDE.md

## Project Overview

**Malawi Med** is a student-run global health initiative sending 16 medical students from Huntington, West Virginia to Ekwendeni, Malawi for 3 weeks in April 2026. This repo is their public-facing website + internal member portal.

- **Live URL**: https://www.malawi-med.org
- **Hosting**: GitHub Pages, branch `main`, custom domain via `CNAME`
- **Stack**: Static HTML/CSS/JS — no build step, no framework, no server
- **Previous name**: Marshall for Malawi (rebranded Feb 2026 — all references removed)

---

## File Structure

```
/
├── index.html          # Homepage (hero, about, donate sections)
├── about.html          # Mission, projects, team
├── blog.html           # Blog & photos
├── donate.html         # Donation page (checks + Venmo)
├── contact.html        # Contact form (Google Form embed)
├── style.css           # Global stylesheet — used by all public pages
├── favicon.ico         # Root favicon (duplicate of assets/logo/favicon.ico)
├── CNAME               # GitHub Pages domain: www.malawi-med.org
├── google_form_source.html  # Saved Google Form source (reference only, not served as a page)
├── convert_photos.py   # Utility: converts HEIC photos → compressed JPG
│
├── assets/
│   ├── malawi-med-logo.png         # Primary logo (1406×1657 RGBA, 3 MB)
│   ├── malawi-med-logo-small.png   # Web-optimized logo (used in nav/headers)
│   ├── malawi-med-logo.pxd         # Pixelmator source for logo
│   ├── malawi-med-qr-FINAL.png     # QR code → malawi-med.org (500×500)
│   ├── front-page-photo.jpg        # Team photo with Malawi flag (homepage)
│   ├── marshall_flag_photo.jpg     # Internal filename — kept as-is
│   ├── hero_artistic.png           # Waterfall hero background
│   ├── about_artistic.png          # About page artistic image
│   ├── malawi_sunset.jpg           # Used in members portal hero
│   ├── africa_with_malawi.png      # Map graphic
│   ├── compressed/                 # Web-optimized photos (max 1600px, 75% quality)
│   ├── photos_for_gallery/         # Raw + JPG pairs for gallery use
│   └── logo/                       # Favicon set + site.webmanifest (PWA)
│       ├── favicon.ico / favicon-16x16.png / favicon-32x32.png
│       ├── apple-touch-icon.png
│       ├── android-chrome-192x192.png / android-chrome-512x512.png
│       └── site.webmanifest        # PWA manifest — name: "Malawi Med", theme: #00592D
│
├── members/
│   ├── index.html          # Password gate (password: "thomas")
│   ├── members.html        # Main portal — trip guide, packing, logistics, promotional materials
│   ├── language-guide.html # Tumbuka language guide (300+ words)
│   ├── lodging-gallery.html# SFHC compound photos
│   │
│   ├── Flyers (8.5"×11" portrait)
│   │   ├── flyer.html          # General flyer
│   │   ├── flyer-impact.html   # Impact-first design
│   │   ├── flyer-clinical.html # Clinical focus design
│   │   └── flyer-minimal.html  # Modern minimal design
│   │
│   ├── Table Tents (11"×8.5" landscape, fold-and-stand)
│   │   ├── tent-stable.html            # Default
│   │   ├── tent-stable-identical.html  # 360° identical sides
│   │   ├── tent-stable-info.html       # Info-rich
│   │   └── tent-stable-artistic.html   # Vivid/artistic
│   │
│   ├── Dinner Posters (portrait, Walmart print services)
│   │   ├── poster-dinner-bold.html         # Full green bg, huge "10%", 20×30
│   │   ├── poster-dinner-elegant.html      # White editorial, two-column, 20×30
│   │   ├── poster-dinner-vivid.html        # Split diagonal design, 20×30 (8in×12in)
│   │   └── poster-dinner-vivid-8x10.html   # Same split design, sized for 8×10 (8in×10in)
│   │
│   ├── Table Pamphlet
│   │   └── pamphlet-dinner.html    # Two 4"×6" cards per landscape sheet, fold & cut
│   │
│   └── resources/
│       ├── Apply for a Malawi Visa.pdf
│       ├── STEP_Registration_Guide.pdf
│       ├── MSTG_6th_Edition_2023.pdf
│       ├── malawi-intergrated-clinical-hiv-guidelines-1st-edition-2022.pdf
│       └── sfhc/                   # SFHC compound photos (HEIC + JPG pairs)
│
└── drafts/                 # WIP pages not yet published
    ├── team.html           # Draft team/roster page
    └── timeline.html       # Draft trip timeline page
```

---

## Brand Identity

### Colors (CSS custom properties in `style.css`)
| Variable | Hex | Use |
|---|---|---|
| `--primary-color` | `#00592D` | Main green — buttons, headers, accents |
| `--secondary-color` | `#1E824C` | Emerald green — gradients, secondary elements |
| `--accent-color` | `#CE1126` | Malawi flag red — decorative accents, alerts |
| `--text-dark` | `#2D3436` | Body text |
| `--text-muted` | `#636E72` | Secondary text |

### Typography
- **Headings / Display**: `Playfair Display` (serif, 700–900 weight) — elegant, editorial
- **Body / UI**: `Inter` (sans-serif, 400–800 weight) — clean, modern
- **Icons**: Bootstrap Icons (`bi bi-*`)

### Logo
- Primary: `assets/malawi-med-logo-small.png` — used in all nav bars and print headers
- Full resolution: `assets/malawi-med-logo.png` — 1406×1657 RGBA PNG
- The logo has a shield shape with the Malawi flag colors — do NOT filter/invert it on green backgrounds; it reads fine as-is

---

## Key Conventions

### Public Pages
- All use Bootstrap 5 (CDN) + `style.css` + Google Fonts (Inter)
- Navbar is fixed-top, glassmorphic (`backdrop-filter: blur`)
- All pages share the same nav and footer pattern from `index.html`
- No JavaScript framework — vanilla JS only for scroll effects and toggles

### Members Portal
- Auth: `sessionStorage.getItem('isLoggedIn') === 'true'` — set on login, checked on each portal page
- Password: `thomas` (set in `members/index.html`)
- All portal pages use `../style.css` and `../assets/` for shared resources
- Auth check script must be the first script in `<head>` to prevent flash

### Print Materials
- All print HTML files use inch-based CSS (`width: 8.5in`, `height: 11in`, etc.)
- Always include `-webkit-print-color-adjust: exact; print-color-adjust: exact;`
- `@page { size: ...; margin: 0; }` inside `@media print`
- PDF downloads use `html2pdf.js` from cdnjs CDN
- Toolbar (`.no-print` / `.toolbar`) hides on print via `display: none`
- Asset paths from `members/` reference `../assets/`

### Poster Sizing
| File | Canvas | Walmart Size |
|---|---|---|
| `poster-dinner-bold.html` | 8in × 12in | 20×30 |
| `poster-dinner-elegant.html` | 8in × 12in | 20×30 |
| `poster-dinner-vivid.html` | 8in × 12in | 20×30 |
| `poster-dinner-vivid-8x10.html` | 8in × 10in | 8×10 |
| Flyers | 8.5in × 11in | Standard letter |
| Table tents | 11in × 8.5in | Landscape letter |
| Pamphlet | 11in × 8.5in | 2× 4"×6" cards |

---

## Key Content Details

### The Trip
- **Who**: 16 medical students from Huntington, West Virginia
- **Where**: Ekwendeni, Malawi (Ekwendeni Mission Hospital + SFHC compound)
- **When**: April 2026
- **Duration**: 3 weeks
- **Fundraising**: 10% of dining proceeds at the fundraising dinner

### Fundraising & Donation
- Checks payable to: **Malawi Med**, 21 Sunwatch Dr., Huntington WV 25705
- Venmo note format: `"Donation for ${cause} - Malawi Med"`
- 501(c)(3) fiscal sponsor: **Global Medical Education Foundation**

### Contact
- Student email: `mayo49@marshall.edu` — intentionally kept (active student email)
- Website: malawi-med.org

### Fundraising Dinner Language (match exactly in materials)
- `10% of all proceeds today`
- `goes toward supporting 16 local medical students on a global health trip to Malawi this April.`
- `Scan to Learn More & Give`

---

## What NOT to Touch
- `CNAME` — required for GitHub Pages custom domain
- `google_form_source.html` — reference file for the Google Form embed in contact.html
- `assets/logo/site.webmanifest` — PWA config
- `assets/malawi-med-qr-FINAL.png` — final QR code, do not regenerate
- `mayo49@marshall.edu` in `contact.html` — intentional, leave as-is

## Assets to Keep But Not Serve
- `*.pxd` files — Pixelmator source files for logo/map graphics
- `convert_photos.py` — utility script for compressing HEIC photos
- `members/resources/sfhc/` — HEIC originals alongside JPGs

---

## Deployment
- Push to `main` branch → GitHub Pages auto-deploys
- No build step required
- Images should be compressed before committing (use `convert_photos.py` or similar)
