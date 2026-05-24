# WMS Software

> Warehouse Management System — multi-site, multi-tenant, with a Master Control Site for federation. FastAPI + SQLAlchemy backend, vanilla-JS "industrial editorial" frontend.

**Status:** Phase 1 MVP — feature-complete on Modules 1–8 (P1 + P2). Phase 1 P3 polish and the full multi-site federation (Phase 2) are open. See [Implementation Status](#implementation-status) below.

---

## Table of Contents

1. [What This Is](#what-this-is)
2. [Quick Start](#quick-start)
3. [Architecture at a Glance](#architecture-at-a-glance)
4. [Project Layout](#project-layout)
5. [Tech Stack](#tech-stack)
6. [Implementation Status](#implementation-status)
   - [Shipped](#shipped-phase-1-modules-18)
   - [In Progress / Queued](#in-progress--queued)
   - [Not Started (Phase 2)](#not-started-phase-2)
7. [Documentation Index](#documentation-index)
8. [Development Workflow](#development-workflow)
9. [Testing](#testing)
10. [License & Ownership](#license--ownership)

---

## What This Is

WMS Software is a warehouse management application designed for **multi-warehouse food-grade operations**. It tracks inventory across receiving → storage → production → shipping, enforces lot/batch traceability for recall readiness, and supports a fleet of independent warehouse sites federated by a central **Master Control Site (MCS)**.

The product separates two concerns that most WMS tools blur together:

- **Site operations** — what an operator does on the floor (receiving, picking, QC holds, lot genealogy). Lives at each warehouse.
- **Fleet governance** — provisioning users across sites, KPI rollup, recall coordination, license control. Lives at the MCS (client-owned) and the **Vendor Control Plane** (vendor-owned).

See [`MULTI_SITE_ARCHITECTURE.md`](./MULTI_SITE_ARCHITECTURE.md) for the full federation model including the commercial lifecycle (negotiation → deployment → decommission).

---

## Quick Start

**One command from the repo root:**

```bash
./start.sh
```

`start.sh` is a hardened launcher that:
- Verifies Python 3.11+
- Creates the venv on first run, installs deps only when imports actually fail
- Seeds the SQLite database when absent (idempotent — never overwrites real data)
- Detects port collisions on `:8765` (frontend) and `:8775` (backend)
- Launches both servers, tracks PIDs in `.run/`, tails logs on demand
- Cleans up cleanly on Ctrl+C

Once running:

| URL | What it is |
|---|---|
| http://localhost:8765/login.html | Frontend entry point |
| http://localhost:8775/docs | Interactive Swagger UI (live API) |
| http://localhost:8775/api/v1/health | JSON liveness probe |

**Default credentials (seeded mock data):**

- MCS admin: `MCS-ADMIN` / `admin1234`
- Any site operator: `WHS-001-001` (or `WHS-002-001`, `WHS-003-001`) / `password123`

The login form requires you to **pick the correct site** — `WHS-001-001` cannot log in against `WHS-002`. This is enforced at the row level, not as a frontend check.

**Manual fallback** (if you want backend and frontend separately) is documented in [`backend/README.md`](./backend/README.md) and [`frontend/README.md`](./frontend/README.md).

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────────────────┐
│                  VENDOR CONTROL PLANE (our cloud)                    │
│  License issuance · signed installers · fleet telemetry rollup       │
│  Talks to many client MCSes; sites NEVER talk to it directly.        │
└──────────────────────────────────────────────────────────────────────┘
                            ▲ (license heartbeat)
                            │
┌──────────────────────────────────────────────────────────────────────┐
│                MASTER CONTROL SITE (per-client deployment)           │
│  Site directory · user federation · KPI rollup · recall coordination │
│  Holds a license cache — sites keep running if VCP is unreachable.   │
└──────────────────────────────────────────────────────────────────────┘
              ▲                ▲                ▲
              │                │                │
      ┌───────┴──────┐  ┌──────┴──────┐  ┌──────┴──────┐
      │  Site WHS-001│  │ Site WHS-002│  │ Site WHS-003│
      │  Dallas      │  │ Houston     │  │ Austin      │
      │              │  │             │  │             │
      │  FastAPI     │  │  FastAPI    │  │  FastAPI    │
      │  + SQLite    │  │  + SQLite   │  │  + SQLite   │
      │  + static FE │  │  + static FE│  │  + static FE│
      └──────────────┘  └─────────────┘  └─────────────┘
```

**Key invariants:**

1. JWTs are scoped to `(employee_code, site_id)` — a stolen token from one site does not authenticate against another.
2. Each site runs the same backend image; the MCS is "just another site" with extra endpoints enabled by config.
3. The frontend is fully static (no SSR, no build step required for development) — it talks to the local site's backend over fetch.

---

## Project Layout

```
WMS_Software/
├── README.md                       ← this file
├── start.sh                        ← one-command local launcher
├── package.json                    ← npm scripts for stylelint only
├── .gitignore
│
├── backend/                        ← FastAPI + SQLAlchemy
│   ├── README.md                   ← backend-only quick start + endpoints
│   ├── pyproject.toml              ← deps + ruff + pytest config
│   ├── .env.example                ← copy to .env (never commit)
│   ├── wms/
│   │   ├── main.py                 ← FastAPI app + CORS + router wiring
│   │   ├── core/                   ← config · security · DI
│   │   ├── db/                     ← engine · base · session
│   │   ├── models/                 ← SQLAlchemy ORM (Site, User, SKU, Lot, ASN, …)
│   │   ├── schemas/                ← Pydantic request/response shapes
│   │   ├── services/               ← business logic (receiving, shipping, production)
│   │   ├── api/v1/                 ← routers (auth, sites, receiving, shipping, …)
│   │   └── seeders/seed.py         ← idempotent mock data (5 sites · 141 users · 535 lots)
│   └── tests/                      ← pytest suite (250+ tests as of 2026-05-22)
│
├── frontend/                       ← static HTML/CSS/JS — no build step
│   ├── README.md                   ← design system + page inventory
│   ├── index.html                  ← operations dashboard
│   ├── login.html                  ← multi-site picker with live ping
│   ├── receiving.html              ← dock check-in → QC → FIFO putaway
│   ├── shipping.html               ← pick queue → FEFO consolidation → truck load
│   ├── production.html             ← recipes · BOM · work orders · genealogy
│   ├── quality.html                ← QA hold aging · release/destroy/rework
│   ├── inventory.html              ← SKU search + lot detail + safety-stock alerts
│   ├── reports.html                ← genealogy · supplier · outlier · aging
│   ├── admin*.html                 ← admin hub · branding · sites · users · org meta
│   ├── profile.html                ← user profile + settings + sign-out
│   ├── styles/                     ← tokens · base · components · page · dashboard
│   ├── scripts/                    ← shell · nav-init · api · per-page loaders
│   └── assets/                     ← placeholder logos · favicon
│
└── docs/ (top-level *.md)          ← see Documentation Index below
```

---

## Tech Stack

**Backend**
- Python 3.11+
- FastAPI 0.110+, Uvicorn (standard)
- SQLAlchemy 2.0 (ORM, Postgres-portable schema currently running on SQLite)
- Alembic (migrations — schema currently bootstrapped by seeder; Alembic ready for v1.0 cutover)
- Pydantic 2 + pydantic-settings
- bcrypt (password hashing) + python-jose (JWT, HS256)
- Pillow (avatar upload sanitization)
- pytest + httpx for tests, Ruff for lint/format

**Frontend**
- Vanilla HTML + CSS + ES modules — **no framework, no build step**
- Stylelint 17 + `stylelint-value-no-unknown-custom-properties` to catch undefined-token bugs in CI
- Design tokens in `frontend/styles/tokens.css` (single source of truth for color/type/spacing/motion)
- Fonts: Instrument Serif (display) · Geist (body) · JetBrains Mono (code/labels)

**Storage**
- Development: SQLite at `backend/data/wms.db` (gitignored)
- Production target: PostgreSQL — schema is portable, only the connection string changes

**Auth**
- JWT bearer tokens with `(employee_code, site_id, role)` claims
- Per-site row-level enforcement at login and at every authenticated request
- 5-level permission hierarchy (Lvl 1 operator → Lvl 5 admin)

---

## Implementation Status

> Source of truth: [`IMPLEMENTATION_ROADMAP.md`](./IMPLEMENTATION_ROADMAP.md). This section is a high-altitude summary; the roadmap has per-feature checkboxes and ship dates.

### Shipped (Phase 1, Modules 1–8)

All **Priority 1 (Critical Path)** and **Priority 2 (High Value)** modules from the Phase 1 roadmap are functional, wired end-to-end, and covered by tests.

| # | Module | What's done |
|---|---|---|
| 1 | **Core Inventory** | SKU master, locations w/ capacity rules, lot/batch tracking, on-hand/QA-hold/reserved tiers, FIFO putaway + picking, inventory adjustments + audit |
| 2 | **Receiving** | Inbound scan, ASN matching, variance (>1% triggers approval), blocking QC, damage assessment, FIFO location assignment, label generation, cancel/undo, multi-line ASN modal |
| 3 | **Shipping** | Orders + pending view, pick task execution, FIFO + FEFO (<7d expiration trigger), multi-lot consolidation, single packing slip, truck weight enforcement, modification workflow |
| 4 | **Production** | Work orders, recipe/BOM versioning, ingredient consumption, pre-flight reservation, shortage handling, yield tracking + variance alerts, lot genealogy (ingredient → produced) |
| 5 | **Quality Assurance** | Item hold workflow, escalation tiers (14d/15-21d/21-30d/30+), release/destroy decisions, QA-HOLD separation from available stock, supplier defect tracking |
| 6 | **Metrics & Reporting** | Operations dashboard (5-min cache), KPI reports, outlier detection (per-user vs team baseline, 20% threshold), supplier performance, lot genealogy, inventory + QA aging |
| 7 | **Users & Permissions** | 5-level RBAC, role-based module access, shift management, department/team hierarchy, full audit trail (action + reason + before/after), session + password policy, MFA scaffold, API tokens + rate limiting |
| 8 | **System & Infrastructure** | Multi-site federation (single-binary), encryption at rest/transit (config-ready), automated backup hooks, audit hot/cold split, per-warehouse config, integration API framework |

**Priority 2 (Operational Efficiency) — all shipped:**
- Slow-moving inventory + clearance recs · Safety-stock + reorder points · Expiration KPIs · Cycle counts (configurable) · Chat system · Daily genealogy auto-report · Multi-warehouse transfers · Supplier performance trending

**Frontend pages shipped (14 total):** Dashboard · Login (multi-site picker) · Receiving · Shipping · Production · Quality · Inventory · Reports · Admin · Admin-Branding · Admin-Sites · Admin-Orgmeta · Users · Profile.

**Cross-cutting infrastructure shipped:**
- Hardened `./start.sh` launcher with port-collision detection, PID tracking, log tailing, smoke tests, lint shortcuts
- Stylelint CI catching undefined-token bugs that would silently render wrong styles
- Shared toast utility, confirm-modal, multi-line modal — single source of truth for cross-page UX
- 401 session-expired global banner (decoupled producer/consumer pattern)
- Industrial Editorial design system with `tokens.css` as single SoT
- Security audit (SECURITY_AUDIT.md) with all flagged items remediated

### In Progress / Queued

These are tracked in the roadmap and have queued tickets but are not yet shipped:

- **SCO-139 Phase 2** — `receipt_drafts` table + per-operator accountability (operator A starts a receipt, B takes over, audit preserves both contributions)
- **SCO-139 Phase 3** — Admin → Receiving → Stuck ASNs tool (Lvl 3+ release of ASNs stuck in `receiving` > 24h)
- **Procurement workflow + revised cycle counts** (deferred from PAGES_WORKFLOW §1 v2)

### Not Started (Phase 2)

These are explicitly out of scope for the MVP but planned. See [`IMPLEMENTATION_ROADMAP.md`](./IMPLEMENTATION_ROADMAP.md) §"PHASE 2" for the full list.

**Phase 1 P3 — Nice-to-have MVP completion:**
- Handheld RF device pairing for picking
- Email notifications + dashboard alerts (the alert *render path* exists; the email transport does not)
- Advanced per-feature role customization UI
- Client-facing configuration UI for operational thresholds
- Multi-currency support
- Advanced report filtering

**Phase 2 P1 — Advanced workflows:**
- **Rework Module** (full decision tree, work orders, yield recalc, audit)
- **Labor Management** (task routing optimization, time-and-motion, productivity metrics, capacity planning, training/cert tracking)
- **Advanced Forecasting** (ML demand prediction, seasonal adjustment, dynamic safety stock)

**Phase 2 P2 — External integration:**
- **Supplier Portal** (self-service ASN upload, PO acknowledgment, supplier-facing defect dashboard)
- **Customer Portal** (order status, tracking numbers, customer-facing genealogy, invoices, RMA submission)
- **Returns Management** (RMA workflow, return receipt + inspection, refund/credit, return analytics)

**Phase 2 P3 — Operational optimization:**
- **Equipment Maintenance** (preventive scheduling, downtime tracking, OEE, maintenance cost)
- **Multi-Warehouse Orchestration** (demand allocation, transfer optimization, cross-warehouse KPI comparison)
- **Multi-Site Federation Phase 2+** (MCS user federation, corporate KPI rollup, cross-site recall genealogy, SSO/SAML, HA replication, roving-staff handoff)
- **Yard Management** (truck staging, dock optimization, wait-time analytics, carrier performance)

**Commercial layer (proposal stage):**
- The two-control-plane model (VCP + MCS), license issuance/validation, signed installer distribution, billing hooks, and decommission flow are specified in `MULTI_SITE_ARCHITECTURE.md` but not yet implemented. This is the path to shipping the product as a SaaS.

---

## Documentation Index

| Doc | Purpose |
|---|---|
| [`IMPLEMENTATION_ROADMAP.md`](./IMPLEMENTATION_ROADMAP.md) | Per-feature status with ship dates; Phase 1 vs Phase 2 breakdown; success metrics |
| [`MULTI_SITE_ARCHITECTURE.md`](./MULTI_SITE_ARCHITECTURE.md) | Federation model · VCP vs MCS · ping thresholds · commercial lifecycle (negotiation → decom) |
| [`BACKEND_SCHEMA.md`](./BACKEND_SCHEMA.md) | ORM model reference — every table, FK, and invariant |
| [`FRONTEND_DESIGN_SCHEMA.md`](./FRONTEND_DESIGN_SCHEMA.md) | Industrial Editorial design system — tokens, type scale, component vocabulary |
| [`PAGES_WORKFLOW.md`](./PAGES_WORKFLOW.md) | Per-page user flows · endpoints touched · edge cases · test coverage |
| [`PERMISSION_SYSTEM.md`](./PERMISSION_SYSTEM.md) | 5-level RBAC · module access matrix · audit log shape |
| [`SECURITY_AUDIT.md`](./SECURITY_AUDIT.md) | All audit findings, severity, remediation status |
| [`SETTINGS_REGISTRY.md`](./SETTINGS_REGISTRY.md) | Configurable thresholds (FEFO trigger window, variance %, hold aging tiers, …) |
| [`WMS_plan.txt`](./WMS_plan.txt) | Original product spec — leveled feature inventory (Lvl 1–5) |
| [`answers.txt`](./answers.txt) | Decision log — Q&A captured during scoping |
| [`backend/README.md`](./backend/README.md) | Backend-only quick start, endpoint reference, mock-data summary |
| [`frontend/README.md`](./frontend/README.md) | Frontend-only quick start, page inventory, design principles |

---

## Development Workflow

**Branching:** `main` is the integration branch. Direct commits land there during MVP; feature branches expected once external contributors join.

**Commit style:** Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`). Tickets are tracked as `SCO-<n>` IDs in commit subjects and roadmap entries.

**Pre-commit checks** (run manually before pushing):

```bash
# Backend
cd backend
ruff check . && ruff format --check . && pytest -v

# Frontend
npm run lint:css
```

Or use the launcher shortcut: `./start.sh` then press `[t]` for a full smoke test (backend tests + CSS lint).

**Environment variables** (see `backend/.env.example`):

| Var | Default | Notes |
|---|---|---|
| `WMS_ENV` | `development` | Toggles dev-only routes and verbose error responses |
| `WMS_SECRET_KEY` | placeholder | **Must** be set to a 32-byte hex value in production (`openssl rand -hex 32`) |
| `WMS_DB_URL` | `sqlite:///./data/wms.db` | Switch to `postgresql+psycopg://…` for prod |
| `WMS_JWT_ALGORITHM` | `HS256` | |
| `WMS_JWT_EXPIRE_MINUTES` | `480` | 8-hour shift |
| `WMS_CORS_ORIGINS` | localhost | Comma-separated allowlist |
| `WMS_SITE_ID_DEFAULT` | `WHS-001` | Used by login picker first paint |

---

## Testing

```bash
cd backend
pytest -v                  # full suite, ~250+ tests, in-memory SQLite
pytest tests/test_workflow_e2e.py -v   # end-to-end: receive → store → produce → ship
```

Test fixtures use `password123` / `pw1234` deliberately — these are not real credentials and never escape the test runner (the in-memory SQLite is torn down per test).

**Frontend** has no JS test runner yet (vanilla static site, no framework). Stylelint catches CSS regressions; visual changes are validated manually against the design system reference in `FRONTEND_DESIGN_SCHEMA.md`.

---

## License & Ownership

- **License:** UNLICENSED (proprietary). All rights reserved.
- **Source:** [github.com/Tuscani712/mwms](https://github.com/Tuscani712/mwms)
- **Project status:** Pre-1.0, active development.

This codebase is not currently accepting external contributions. If you are a stakeholder or contracted contributor, see the `IMPLEMENTATION_ROADMAP.md` for the next-up queue and coordinate via the existing chat channels before opening branches.
