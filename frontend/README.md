# WMS Frontend — Industrial Editorial

Production-grade frontend scaffold for the Warehouse Management System. Built with intentional design language: **brutalist precision meets editorial typography meets instrumentation density.**

---

## Aesthetic Direction

- **Deep ink canvas** (`#0C0C0F`) — reduces eye strain over long warehouse shifts.
- **Display serif**: *Instrument Serif* (italic) for headlines, KPI values, action titles.
- **Body sans**: *Geist* — modern, distinctive, never generic.
- **Mono**: *JetBrains Mono* — every SKU, lot, timestamp, code label gets mechanical authority.
- **Molten amber accent** (`#FF6B1A`) — single dominant accent.
- **Hairline rules** — typographic dividers (1px borders) build the grid structure.
- **Subtle grain + vignette** — atmospheric depth.

This is **NOT** generic SaaS — no Inter/Roboto fonts, no purple gradients, no cookie-cutter cards.

---

## File Structure

```
frontend/
├── index.html              # Dashboard (operations console)
├── login.html              # Sign-in with multi-site picker
├── receiving.html          # Inbound dock + ASN matching + QC
├── shipping.html           # Pick queue + multi-lot consolidation
├── production.html         # Work orders + recipe BOM + genealogy
├── quality.html            # QA holds + escalation tiers + decisions
├── inventory.html          # Search-first inventory lookup
├── reports.html            # Quick reports + run history
├── admin.html              # Admin hub + pending approvals + audit
├── admin-branding.html     # Logo upload + facility name + site ID
├── README.md
├── styles/
│   ├── tokens.css          # Design tokens (colors, fonts, spacing, motion)
│   ├── base.css            # Resets, typography, atmospheric grain
│   ├── components.css      # Reusable UI vocabulary (buttons, panels, KPIs, etc.)
│   ├── page.css            # Shared page structures (head, tables, filters, subnav)
│   └── dashboard.css       # Dashboard-specific composition + topbar/ticker/footer
├── scripts/
│   ├── shell.js            # Cross-page shell (clock, chat toggle, branding load)
│   └── dashboard.js        # Dashboard-specific (KPI count-up, refresh ticker)
└── assets/
    └── client-logo.svg     # Placeholder client logo (replaceable via admin)
```

---

## Pages Built

| Route | What's on it |
|-------|--------------|
| `index.html` | Operations console: hero, KPI cluster, action grid, alerts feed, chat dock, footer |
| `login.html` | Split layout, client logo, **status strip with multi-site selector** (live per-site ping) |
| `receiving.html` | Inbound queue, ASN-matching, QC inspection, putaway suggestions (FIFO + overflow) |
| `shipping.html` | Pick queue, multi-lot consolidation, FEFO triggers, truck weight budget |
| `production.html` | Work order schedule, recipe BOM with ingredient consumption, lot genealogy panel |
| `quality.html` | Hold aging tiers (14/21/30/30+), held lots table, release/destroy/rework decisions |
| `inventory.html` | Hero search input, recent lookups, safety-stock alerts, cycle-count schedule |
| `reports.html` | Quick-report tiles (genealogy, supplier, outliers, aging), run history table |
| `admin.html` | Subnav, admin tiles (users/titles/templates/sites/branding/audit), pending approvals, audit tail |
| `admin-branding.html` | Drag-drop logo upload, facility name + site ID, live preview |

---

## Consistent UX Patterns Across Pages

Every module page follows the same skeleton:

```
┌────────────────────────────────────────────┐
│ TOPBAR · brand · nav · time · user-chip   │  ← sticky, blur-backed
├────────────────────────────────────────────┤
│ STATUS TICKER · site + 4-5 live metrics    │
├────────────────────────────────────────────┤
│ PAGE HEAD · breadcrumb · title · lede ·    │
│              page actions                  │
├────────────────────────────────────────────┤
│                                            │
│  KPI ROW · 4 instrument displays           │
│                                            │
│  PRIMARY SECTION · filter bar + table      │
│                                            │
│  SECONDARY SECTION · main+aside detail     │
│                                            │
├────────────────────────────────────────────┤
│ FOOTER · build · status                    │
└────────────────────────────────────────────┘
                                ┌─────────────┐
                                │ CHAT DOCK   │  ← fixed, collapsible
                                └─────────────┘
```

The repeating elements (topbar, ticker, footer, chat-dock) share the same CSS classes and HTML structure across pages, so a single design change ripples everywhere.

---

## Client Logo Replaces Brand Mark

When a client uploads their logo via **Admin → Branding**, the default "Wms/" wordmark in the top-left of every page is replaced with their logo. This applies to:

- The topbar `.brand-mark` on all module pages (Dashboard, Receiving, Shipping, etc.)
- The marquee-header on the login page

The swap is driven by `localStorage.wms.clientLogo`. When backend lands, this becomes a `GET /api/branding` call that serves the active site's logo. The template pattern is:

```html
<a href="index.html" class="brand">
  <img class="brand-logo" data-bind="brand-logo" alt="" hidden />
  <span class="brand-mark" data-bind="brand-mark"><em>Wms</em>/</span>
  <span class="brand-tagline">…</span>
</a>
```

`shell.js` (and `dashboard.js`) auto-swap the visibility on every page load.

---

## Multi-Site Login Picker

The login page status strip contains a **site selector** (click "Site · WHS-001 · DAL ▾"). Opens a popover listing all sites from the directory, each with a live ping pill, build version, and uptime. Master Control Site marked with amber `[MASTER]` badge. Selecting a site repoints all status strip values to that site's endpoints.

### Ping Color Thresholds
- ≤ 74 ms → green glow
- 75-149 ms → yellow glow
- ≥ 150 ms → red glow + blink
- Network fail → gray "OFFLINE"

See `../MULTI_SITE_ARCHITECTURE.md` for the full architecture spec.

---

## Design Tokens (`tokens.css`)

Single source of truth. Change one variable, the entire interface updates.

- **Typography**: font families, type scale (11px → 104px), tracking, line height
- **Color**: graduated dark canvas, rule lines, ink (text) palette, signal colors
- **Spacing**: 4px-base scale (`--space-1` → `--space-32`)
- **Motion**: easing curves, durations, keyframes
- **Elevation**: minimal industrial shadows + inset highlights

A light-theme override (`[data-theme="light"]`) is stubbed in for future client white-labeling.

---

## Component Vocabulary (`components.css` + `page.css`)

- `.btn` (+ `--primary`, `--ghost`, `--icon`, `--sm`, `--lg`, `btn-arrow`)
- `.panel` — surface with top-rule + inset shadow + `.panel-head` / `.panel-body` / `.panel-foot`
- `.kpi` — instrument display with animated accent rail
- `.action-tile` — large clickable tile with code label + radial hover glow
- `.alert` — single-row alert with status dot, title, time, source
- `.dot` — status indicators (`--ok`, `--warn`, `--crit`, `--info`, `--amber`)
- `.tag` — small status pills, mono-uppercase
- `.chat-dock` — fixed bottom-right persistent chat, collapsible
- `.data-table` — consistent tabular data with mono numerics + hover states
- `.filter-bar` — search input + filter chips
- `.subnav` — secondary navigation (used on admin)
- `.meter` — progress bars (capacity, completion %)
- `.callout` — large stat readout in a panel

---

## To View

**Recommended — single command from project root:**

```bash
./start.sh
```

This handles env, deps, DB seeding, port collisions, PID tracking, and clean shutdown via CTRL+C.
Interactive menu after launch: `[s]` status, `[b]/[f]` tail logs, `[r]` restart, `[o]` open browser, `[q]` quit.

**Manual two-terminal fallback:**

```bash
# Terminal 1 — frontend
cd frontend && python3 -m http.server 8765

# Terminal 2 — backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m wms.seeders.seed
uvicorn wms.main:app --reload --port 8000
```

Login as `WHS-001-001` / `password123` (or any seeded `WHS-00X-001`). Receiving and Shipping pages
fetch live data from the API on successful login.

## Frontend ↔ Backend wiring

- `scripts/api.js` — auth-aware fetch wrapper. Exposes `window.WMS_API` with `login`, `me`, `sites`,
  `receiving.*`, `shipping.*`, `health`, `ping`.
- `scripts/receiving.js` / `scripts/shipping.js` — page-specific loaders that populate
  `[data-bind="receiving-inbound-rows"]` and `[data-bind="shipping-orders-rows"]`.
- JWT token in `localStorage.wms.token`; user metadata in `localStorage.wms.user`;
  active site display label in `localStorage.wms.activeSiteLabel`.

The login form submits to `POST /api/v1/auth/login`. The selected `site_id` (from the site picker)
is sent with credentials — same employee code at a different site = rejected with HTTP 401.

## Session UX

The active session is surfaced consistently across pages via `data-bind` attributes that
`shell.js` (module pages) and `dashboard.js` (dashboard) populate on load:

| Attribute | What gets injected |
|---|---|
| `data-bind="site-name"` | `wms.activeSiteLabel` (e.g., "WHS-002 · HOU") |
| `data-bind="user-name"` | `user.full_name` from the JWT login response |
| `data-bind="user-initial"` | First letter of full name, uppercase |
| `data-bind="brand-logo"` / `data-bind="brand-mark"` | Client logo swap from `wms.clientLogo` |

The top-right user chip (`#user-chip`) is the **sign-out** trigger — click → confirm → clears
`wms.token`, `wms.user`, `wms.activeSiteLabel` → redirects to login. This is the fastest way to
switch sites or users without leaving the browser.

## Login error handling

The login form distinguishes three outcomes:

- **HTTP 200** → JWT stored, redirect to dashboard
- **HTTP 401** → red inline banner: "Login rejected. User X is not assigned to site Y, or password is incorrect."
- **Network error** → "Backend unreachable" banner with a hint to start the server

A failed login never silently navigates away. The submit button shows "Signing in…" during the request.

---

## Design Principles

> **"Bold maximalism and refined minimalism both work — the key is intentionality, not intensity."**

This scaffold commits to *refined minimalism with editorial precision*. Every italic, mono label, and hairline border was a choice — not a default.

Operators should feel that the tool was *built for them*, by people who understood the work.
