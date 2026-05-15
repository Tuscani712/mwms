# WMS Multi-Site Architecture

**Status**: Conceptual · Phase 1.5 / Phase 2 implementation
**Last Updated**: 2026-05-15
**Decision Owner**: Meatbag

---

## Overview

The WMS is designed as a **federated multi-site system** rather than a single-tenant monolith. Each physical facility (warehouse, plant, cold storage, reverse logistics center) operates as an **autonomous site instance** with its own backend, database, and users. A **Master Control Site (MCS)** sits at the corporate level and coordinates cross-site operations.

This architecture answers the operational reality:

- Warehouses operate **independently** in day-to-day work — a Dallas operator should not be able to accidentally pick from Houston inventory.
- Each site has its **own staffing, shifts, and operating procedures** — users belong to *their site*, not to a global pool.
- Network/connectivity to remote sites can be unreliable — a site must keep operating even if MCS is unreachable.
- Corporate-level oversight (rolled-up KPIs, cross-site transfers, recall coordination) still needs a single pane of glass.

---

## ARCHITECTURE LAYERS

### Layer 1: Site Instances (Autonomous)

Each site is a **complete, self-contained WMS deployment**:

```
SITE: WHS-001 · DAL
├── Backend (FastAPI / Node)
├── Databases:
│   ├── User DB (site-local — only this site's operators)
│   ├── Inventory DB (this site's stock)
│   ├── Chat DB (site-internal communications)
│   └── Metrics DB
├── Frontend (served from site host)
├── Health endpoint:  GET /api/health
│     → { status, build, boot_ts, uptime, db_ok, queue_ok }
├── Ping endpoint:    GET /api/health/ping  → 200 OK (smallest possible response)
└── Hosts a single facility (or a small co-located group)
```

Each site enforces:
- **Login authentication** against its **own user DB** — credentials don't cross sites.
- **Permissions** are evaluated within the site's own context (titles, templates, granular perms).
- **Audit logs** stay local to the site (with periodic replication to MCS for corporate audit).
- **Operational data** (orders, lots, inventory transactions) lives at the site.

### Layer 2: Master Control Site (MCS)

The MCS is itself a WMS instance but with **elevated coordination responsibilities**:

```
MCS · CORP
├── Site Directory (canonical list of sites + their endpoints + status)
├── Cross-Site User Federation:
│   ├── Maps users to one-or-more home sites
│   ├── Optional SSO/SAML provider (when client uses centralized identity)
│   └── User provisioning fan-out (one source → all assigned sites)
├── Cross-Site Reporting:
│   ├── Rolled-up KPIs across all sites (read-only aggregate)
│   ├── Inter-site transfer coordination
│   └── Corporate audit log (replicated from sites)
├── Recall Coordinator:
│   ├── Lot genealogy cross-site lookup (find affected lots in any site)
│   └── Recall broadcast (notify all sites of affected lots)
├── Permission Template Library:
│   ├── Master templates that sites can subscribe to / customize
│   └── Push template updates to subscribing sites
└── Health Aggregator: polls all sites, exposes corporate dashboard
```

The MCS does **not** hold operational inventory. It is a **directory + coordinator + aggregator**, not a transactional WMS for any specific floor.

### Layer 3: Site Directory Protocol

A small, well-defined protocol the login page (and any site) can use to discover the universe:

```
GET https://mcs.example.com/api/sites
[
  {
    "id": "mcs",
    "code": "MCS · CORP",
    "name": "Master Control · Corporate",
    "host": "https://mcs.example.com",
    "role": "master",
    "build": "v0.1.0",
    "boot_ts": "2026-03-12T14:00:00Z"
  },
  {
    "id": "whs-001-dal",
    "code": "WHS-001 · DAL",
    "name": "Dallas Distribution",
    "host": "https://dal.wms.example.com",
    "build": "v0.1.0",
    "boot_ts": "2026-04-03T22:00:00Z"
  },
  ...
]
```

Each site **caches** the directory locally and refreshes when MCS is reachable, allowing graceful degradation when MCS is down.

---

## LOGIN FLOW

```
Operator at any site URL
  │
  ▼
Login page renders
  │
  ├── Fetches client logo + facility name (local)
  ├── Fetches site directory (from MCS, or cached)
  └── Shows: client logo, facility name, status strip with SITE SELECTOR
              │
              ▼
       Operator clicks "Site · WHS-001 · DAL ▾"
              │
              ▼
       Picker shows all sites with live ping + uptime + build
              │
              ├── (a) Operator selects their own site → form posts to THIS site's /auth
              │       Backend validates against THIS site's user DB
              │       Success → redirect to THIS site's dashboard
              │
              ├── (b) Operator selects a different site → redirect to that site's
              │       /login URL (preserving the selected-site preference in localStorage)
              │       That site renders its own login, operator authenticates there
              │
              └── (c) Operator selects MCS → MCS login flow
                      Only corporate admins / federated users can authenticate here
```

**Critical guarantee**: An operator can only sign in to sites where their credentials exist. If their account isn't provisioned at the selected site, the site backend returns `401 unauthorized` — the login fails cleanly, the operator is reminded which sites they belong to.

---

## USER PROVISIONING MODELS

The WMS supports two provisioning patterns:

### Pattern A: Site-Local Users (Default)
- User accounts created **at the site** by a Level 4+ admin.
- Credentials stored in that site's User DB.
- No coupling to MCS — fully autonomous.
- **Best for**: small organizations, single-warehouse operations, or sites that prefer total autonomy.

### Pattern B: Federated Users (Optional)
- User accounts originate at MCS, with an "assigned sites" list.
- MCS pushes the account (and any subsequent changes) to all assigned site DBs.
- Removal at MCS cascades to all sites.
- SSO/SAML integration available at MCS.
- **Best for**: enterprises with central HR/IAM, sites that share staff, or compliance-driven orgs that need a single audit lineage.

A user *may* exist in multiple sites simultaneously (e.g., a roving supervisor with access to both DAL and HOU). Each site evaluates that user's permissions independently — the user could be a Manager in DAL and a regular Operator in HOU.

---

## STATUS STRIP DATA SOURCES (per-site)

The login page status strip shows data **for the currently-selected site**:

| Field | Source | Update Frequency |
|-------|--------|------------------|
| Site code | Site Directory | On site switch |
| Build | `GET /api/health` of selected site | On site switch + every 60s |
| Status | Derived from ping result (Online/Degraded/Offline) | Every 5s |
| Uptime | Computed from `boot_ts` in `/api/health` | Every 1s (clientside increment) |
| Ping | Client RTT to `GET /api/health/ping` of selected site | Every 5s |

Switching site causes **all 5 values to repoint** to the new site's endpoints — the page never shows a mismatched cocktail of values.

---

## NETWORK & FAILURE MODES

### Site Reachable, MCS Unreachable
- Operator can still log in to a known site (cached directory).
- Cross-site features (transfers, corporate reports) are disabled with a notice.
- Audit replication queues locally and drains when MCS comes back.

### MCS Reachable, Target Site Unreachable
- Login picker shows the offline site with red "OFFLINE" ping pill.
- Selecting an offline site shows a clear error: *"Site is currently unreachable. Try again or contact your administrator."*
- No silent failures.

### MCS + Target Both Unreachable
- Operator sees offline state for the active site.
- Login button is disabled with an explainer.
- Browser can still serve cached static assets (login page renders).

### Partial Site Failure (e.g., DB down but server up)
- `/api/health` returns `db_ok: false`.
- Status shows "Degraded" with a tooltip explaining which subsystem is down.
- Login attempts return a graceful 503.

---

## SECURITY CONSIDERATIONS

- **Per-site sessions**: A session token issued by Site A is **not valid** at Site B. Cross-site requests require re-authentication or a federated MCS token.
- **CORS**: Each site's API only accepts requests from its own origin (and MCS).
- **Site Directory tampering**: Directory is signed by MCS; sites verify the signature before trusting the list. Prevents a compromised MCS from injecting a malicious "spoof" site URL.
- **User isolation**: A query for users at Site A cannot return Site B users — DB-level enforcement, not just app-level.
- **Audit integrity**: Site audit logs are append-only and signed. MCS replication is one-way (sites push to MCS, MCS cannot rewrite site history).

---

## DATA OWNERSHIP MATRIX

| Data | Owner | Replicated to MCS? |
|------|-------|---------------------|
| Inventory transactions | Site | No |
| Lot records | Site | Reference only (for genealogy lookups) |
| User accounts | Site (with optional MCS source) | If federated |
| Permission assignments | Site | Aggregated for audit only |
| Audit logs | Site | Yes (one-way) |
| Chat | Site | No (site-internal) |
| KPI rollups | Site | Yes (numeric aggregates only) |
| Recipes / BOMs | Site (with optional MCS source) | If subscribed |
| Customer/Supplier master | Site (with optional MCS source) | If subscribed |

---

## ADMIN INTERFACES (per layer)

### Site-Level Admin (Level 4-5 at each site)
- Manage local users, titles, permission templates
- Configure local settings (FEFO threshold, yield variance %, etc.)
- View local audit trail
- Upload site's client logo + facility name (per-site branding)

### MCS-Level Admin (corporate)
- Manage site directory (add/remove sites)
- Federate users across sites
- Push permission template updates to subscribed sites
- View corporate dashboard (rolled-up KPIs)
- Initiate cross-site recall procedures
- Coordinate cross-site inventory transfers

---

## IMPLEMENTATION PHASING

### Phase 1 (MVP) — Single Site
- Build full single-site WMS without multi-site complications.
- Login page **shows site selector** (even with one site, to set the pattern).
- Site Directory is a single-entry hard-coded list.
- `/api/health` and `/api/health/ping` endpoints implemented.

### Phase 1.5 — Multi-Site Foundation
- MCS scaffolded (separate deployment of the same codebase, with `role: master` config).
- Site Directory API on MCS, sites fetch + cache it.
- Login page populates picker from MCS directory.
- Per-site authentication enforced (sessions don't cross sites).

### Phase 2 — Federation & Coordination
- MCS user federation (push provisioning to sites).
- Corporate KPI rollup dashboard at MCS.
- Cross-site lot genealogy queries (recall lookups).
- Inter-site inventory transfer workflows.
- SSO/SAML integration option at MCS.

### Phase 2+ — Advanced
- Multi-region MCS replication (HA at corporate layer).
- Site-to-site direct messaging (for transfer coordination, no MCS hop).
- Cross-site supervisor handoff (roving staff with seamless site switching).

---

## OPEN QUESTIONS

1. **MCS bootstrap**: How does the first site know where MCS lives? (Config file? DNS? Environment variable?) — **Proposed**: env var `WMS_MCS_URL` at site install time, with optional override in admin settings.

2. **Site fail-over**: If a primary site goes down, can a sister site take over its workload? — **Proposed**: Not in Phase 1. In Phase 2+, MCS-coordinated standby pairs.

3. **Cross-site inventory visibility**: Should a Dallas operator be able to *see* (read-only) Houston inventory? — **Proposed**: Only if granted `can_view_cross_site_inventory` permission, and only via MCS-aggregated views (sites don't expose inventory APIs to each other directly).

4. **Chat across sites**: Can DAL chat with HOU? — **Proposed**: Phase 2 feature; sites have local chat by default, MCS hosts an optional cross-site corporate channel.

5. **MCS billing / licensing**: Is MCS a free coordinator or a separately-licensed product? — **Decision deferred to commercial team.**

---

## RELATED DOCS

- `WMS_plan.txt` — Core feature spec (single-site behavior)
- `IMPLEMENTATION_ROADMAP.md` — Phasing across MVP / Enhancement
- `PERMISSION_SYSTEM.md` — Per-site permission evaluation
- `FRONTEND_DESIGN_SCHEMA.md` — UI patterns (site selector on login)
- `frontend/login.html` — Reference implementation of site picker UI

---

**Version**: 1.0
**Status**: Architecture approved · awaiting Phase 1.5 implementation start
