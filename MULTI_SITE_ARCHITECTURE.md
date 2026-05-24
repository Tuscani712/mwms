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

## COMMERCIAL LIFECYCLE — NEGOTIATION → DEPLOYMENT → DECOMMISSION

> **Status**: Proposal · 2026-05-21 · Awaiting Meatbag review.
> **Why this section exists**: prior sections describe how the *technical* federation works once a client is running. This section describes how a client *becomes* a running client, how we control them commercially, and how they exit. It introduces a second control plane (the **Vendor Control Plane**) that has been implicit until now.

### Two Control Planes (Critical Distinction)

We have been talking about "the master server" as if it were one thing. It is two:

| Plane | Owner | Lives Where | Trust Boundary | Job |
|---|---|---|---|---|
| **Vendor Control Plane (VCP)** | **Us** (the vendor) | Our cloud | Cross-tenant; sees every client | License issuance + validation, signed installer/update distribution, feature flagging, fleet telemetry rollup, billing hooks, support remote-access broker |
| **Master Control Site (MCS)** | **Client** | Client infra (cloud or on-prem) | Single tenant; sees only their own sites | Site directory, user federation, cross-site KPI rollup, recall coordination, backup orchestration, license cache (verified against VCP) |

**Rule**: VCP can talk to many MCSes. An MCS talks to exactly one VCP (ours). Sites talk only to their MCS (never directly to VCP). This three-tier shape is what lets us shut off a non-paying client without touching their site operations directly, and what lets a client keep running for the grace period if our VCP is unreachable.

### The Full Lifecycle (Negotiation → Decom)

```
┌─ Phase 0: PRE-SALES ────────────────────────────────────────────────┐
│  Lead → Discovery call → Demo → NDA (if needed) → Site survey       │
│  Outputs: Needs Assessment doc, draft sizing, proposed plan + addons│
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 1: COMMERCIAL ───────────────────────────────────────────────┐
│  Quote → MSA + DPA + SLA sign → PO/Invoice → Payment cleared        │
│  Outputs: Signed contracts, client_id minted in VCP, billing seat   │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 2: LICENSE ISSUANCE ─────────────────────────────────────────┐
│  VCP mints signed License Token (JWT-style) bound to client_id     │
│  Token carries: plan, addons[], max_sites, max_users, expiry,      │
│                 entitled_features[], support_tier, signature       │
│  Token + installer download link delivered via client portal       │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 3: PRE-DEPLOYMENT ───────────────────────────────────────────┐
│  Tech check: Ubuntu version, RAM/CPU/disk, network egress to VCP,  │
│              DNS records, TLS cert (or LetsEncrypt automation),    │
│              backup target chosen, time sync OK                    │
│  Master data prep: items, customers, suppliers, recipes, lots      │
│  User roster: extracted from client HR or built fresh              │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 4: MCS DEPLOYMENT ───────────────────────────────────────────┐
│  Install MCS with: WMS_VCP_URL + License Token + admin bootstrap   │
│  MCS calls VCP → validates license → caches signed entitlements    │
│  First admin account created at MCS via setup wizard               │
│  ↓                                                                  │
│  SMALL-CLIENT FORK: if license allows single-server mode, MCS      │
│  also runs as the only site (master+site=same host, same DB).      │
│  Larger clients proceed to Phase 5.                                 │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 5: SITE ENROLLMENT (per additional site) ────────────────────┐
│  At MCS: admin creates site record → MCS mints Enrollment Key      │
│  (already scaffolded in SCO-118 UI — pending backend wire-up)      │
│  Key delivered to site installer → site boots → MCS verifies →     │
│  site marked "Enrolled" → site fetches initial config from MCS     │
│  License max_sites enforced by MCS at enrollment time              │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 6: GO-LIVE ──────────────────────────────────────────────────┐
│  Cutover plan: dry-run / parallel-run / hard-cut                   │
│  Hypercare window (typically 14d): elevated support tier, daily    │
│  check-ins, monitored telemetry                                    │
│  Sign-off → site moves to "Production" lifecycle state             │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 7: OPERATE ──────────────────────────────────────────────────┐
│  License heartbeat: MCS → VCP daily (carries fleet health digest)  │
│  Update channel: VCP publishes signed release manifests; MCS       │
│    schedules per-site rollouts per client policy (canary/staged)   │
│  Backup orchestration: MCS coordinates site-local + offsite copies │
│  Telemetry: opt-in errors + perf summaries flow MCS→VCP            │
│  Renewals + addon upgrades: VCP re-mints license → MCS picks up    │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─ Phase 8: DECOMMISSION / OFFBOARDING ───────────────────────────────┐
│  Client-initiated OR vendor-initiated (non-payment, breach)        │
│  Data export bundle (CSV + signed audit archive) delivered         │
│  License revoked at VCP → MCS enters wind-down (read-only N days)  │
│  Sites archived → keys destroyed → MCS uninstall + data retention  │
│    per DPA (typically 30/90 days then cryptographic erase)          │
└─────────────────────────────────────────────────────────────────────┘
```

### License Authority — Design Sketch

The VCP includes a **License Authority Service** with this contract:

**License Token (issued at sale, refreshed on renewal/upgrade):**
```jsonc
{
  "iss": "vcp.wms.example.com",
  "sub": "client_<uuid>",
  "iat": 1747860000,
  "exp": 1779396000,           // 1-year term (typical)
  "grace_seconds": 1209600,    // 14d offline grace after exp / unreachable VCP
  "plan": "scale",              // starter | growth | scale | enterprise
  "addons": ["recipes", "cold_chain", "recall_coordinator", "sso"],
  "limits": {
    "max_sites": 5,
    "max_users_per_site": 50,
    "max_active_lots": 100000,
    "max_storage_gb": 500
  },
  "features": ["multi_site", "federated_users", "mcs_backup_offsite"],
  "support_tier": "gold",
  "telemetry_required": true,   // gold/enterprise can negotiate this off
  "signature": "ed25519:..."
}
```

**Validation flow:**
1. MCS boot → reads token from `/etc/wms/license.token` → verifies signature against VCP public key (shipped with installer).
2. MCS calls `POST vcp/v1/license/heartbeat` daily with `{client_id, token_hash, fleet_digest}`.
3. VCP responds with `{status: valid|grace|revoked, refresh_token?, feature_flags?}`.
4. On `revoked` → MCS enters read-only mode after a configurable warning window (default 72h, gives client time to call billing).
5. On unreachable VCP → MCS keeps operating until `grace_seconds` elapses, then degrades.

**Why ed25519 signed tokens + heartbeat (not just an API call):**
- Survives short VCP outages — clients don't go down when our cloud blips.
- Token can't be forged without our private key, so tampering with `/etc/wms/license.token` is detectable.
- Heartbeat shape lets us push *changes* (new addon, raised limit) without re-issuing a token.
- Fleet digest in the heartbeat gives us inventory of running versions for support / CVE response.

### Software Distribution + Updates

VCP also acts as the **release authority**:

| Artifact | Signed By | Distributed To | Consumed When |
|---|---|---|---|
| Installer (Ubuntu .deb / Docker image) | VCP release key | Client portal download | Phase 4 deploy |
| Release manifest (per channel: stable, edge) | VCP release key | MCS subscribes to channel | MCS polls every 6h |
| Site binary bundle | VCP release key | MCS pulls + caches, fans out to sites | Per site policy |
| CVE / hotfix bundle | VCP release key | MCS auto-applies on `critical` flag | Immediate |

**Per-site rollout policy** (configured at MCS, enforced by MCS):
- `auto`: install on next maintenance window
- `staged`: canary one site for 24h, then fleet
- `manual`: admin clicks "Deploy" per site
- `pinned`: this site holds at version X (compliance freeze / GxP qualification)

**Rollback**: MCS keeps last 2 binaries per site; rollback is a single command against a site.

### Backup Strategy (clarifying your "master controls backups")

Three-tier:
1. **Site-local snapshot** (every N hours, configurable): site's own disk. Fast restore from same host.
2. **MCS-aggregated**: sites push encrypted backup manifests + chunks to MCS. Survives site host loss.
3. **Vendor-offsite** (optional, license-gated): MCS pushes to vendor-managed bucket (or client's own S3). Survives MCS host loss.

**Restore drill**: monthly automated test that pulls a backup chunk and verifies hash. Reported up to VCP fleet view.

**Retention**: per-tier configurable, defaults 7d / 30d / 365d.

### Gaps in Your Sketch (Things to Add Before Phase 1)

Walking your bullet points and naming what's implied but not stated:

1. **Pre-sales / discovery deliverables** — what document captures "needs assessment"? Proposing a templated *Site Sizing & Plan Selection* form so we don't sell a 5-site enterprise license to a single-warehouse shop. Lives in client portal.
2. **Plan + addon SKU catalog** — there must be a canonical list of plans (starter/growth/scale/enterprise?) and addons (cold-chain, recipes/BOM, recall coordinator, SSO, federated users, vendor-offsite-backup). Without this, license tokens can't have stable `plan`/`addons` enums. **Proposing a `PLANS_AND_ADDONS.md` doc** as the source of truth.
3. **Contracts artifacts** — MSA, DPA (data processing), SLA, security questionnaire response. These influence the license token (`support_tier`, `telemetry_required`, retention windows).
4. **Client portal** — for license download, installer download, support tickets, billing. Not in scope today but referenced in the lifecycle so we don't forget it.
5. **License Authority architecture** — covered above. Was missing from your sketch entirely; you said "potentially a separate master server" — *yes, separate, and not optional in my view*.
6. **Signed installer + release channels** — your sketch said "master controls per-site software revision" but didn't say where the binaries come from or who signs them. Without VCP signing, a compromised network can ship a backdoored update to a client.
7. **Telemetry consent + scope** — what we collect, what we don't, opt-out rules per plan. Required for SOC2 + EU clients.
8. **Support remote access** — when a client opens a P1, how do we get in? Proposing a VCP-brokered, time-bound, client-approved reverse-tunnel session (audit-logged at both ends).
9. **Renewal + upgrade flow** — what happens 30/14/7d before expiry? In-product banner driven by token `exp`, email from VCP, billing trigger.
10. **Decom + offboarding** — your sketch ended at deployment. Equally important: data export bundle format, license revocation behavior (immediate vs wind-down), data retention per DPA, cryptographic erase certificate delivered to client.
11. **Hardware sizing tiers** — installer needs a "this host is too small for your plan" check. VCP heartbeat could surface "running on undersized infra" warnings to fleet view.
12. **Time sync / TLS / DNS prereqs** — explicit prerequisites checklist the installer runs before going live. Reduces "it doesn't work and we don't know why" support tickets.
13. **Disaster recovery for MCS itself** — if the client's MCS host dies, what's the playbook? Restore from MCS-tier backup, re-validate license, sites reconnect. Needs a documented runbook before first enterprise sale.
14. **Multi-region / standby MCS** — already in Open Questions §2. Worth keeping; matters for enterprise SLAs.
15. **Compliance posture** — for food/cold-chain, FSMA 204 traceability is the big one. The architecture should keep this in scope so we don't paint ourselves out of it.
16. **Internal CRM/operations layer** — *we* need a place to see "Client Acme · Plan: scale · 4 sites · last heartbeat: 2h ago · license expires in 45d · payment current". That's a vendor-side admin UI on top of VCP. Probably the smallest version of this is the same admin scaffolding we already built, repointed at the VCP DB.

### Recommended Next Architectural Tasks (proposal — not creating yet)

In rough priority:

1. **VCP scope doc** — separate `VENDOR_CONTROL_PLANE.md` describing the License Authority, release authority, telemetry collector, and support broker. Today's `MULTI_SITE_ARCHITECTURE.md` covers client-side only.
2. **Plans & Addons catalog** — `PLANS_AND_ADDONS.md` canonical SKU list.
3. **License token schema + sample verifier** — code + doc, so backend devs can test against fixture tokens before VCP exists.
4. **Installer prereq checklist + script** — `scripts/preflight.sh` that the installer runs first.
5. **DPA / data retention policy doc** — `DATA_PROCESSING.md` so the client portal can link to it.
6. **Client portal MVP spec** — separate frontend, separate auth (vendor identity, not client identity).
7. **MCS-tier backup orchestrator spec** — drops into the existing MCS scope; pairs with backup destinations in the license.

Items 1–3 unblock everything else; the rest can stage in.

---

## RELATED DOCS

- `WMS_plan.txt` — Core feature spec (single-site behavior)
- `IMPLEMENTATION_ROADMAP.md` — Phasing across MVP / Enhancement
- `PERMISSION_SYSTEM.md` — Per-site permission evaluation
- `FRONTEND_DESIGN_SCHEMA.md` — UI patterns (site selector on login)
- `frontend/login.html` — Reference implementation of site picker UI
- *(proposed)* `VENDOR_CONTROL_PLANE.md` — VCP scope, License Authority, release signing, telemetry contract
- *(proposed)* `PLANS_AND_ADDONS.md` — canonical plan + addon SKU catalog
- *(proposed)* `DATA_PROCESSING.md` — DPA, retention, cryptographic erase policy

---

**Version**: 1.2
**Status**: Architecture approved · frontend dummy-form scaffolding shipped (SCO-118, 2026-05-21) · Commercial Lifecycle + VCP proposal added 2026-05-21 (awaiting review) · awaiting test VMs for backend wire-up

---

## FRONTEND SCAFFOLDING STATUS (SCO-118)

The Admin · Sites page now visualizes the full lifecycle / enrollment model *ahead* of the backend implementing it. All not-yet-wired fields and actions are visible-but-disabled with "wire-up pending" tooltips so admins can see the shape of what's coming.

Scaffolded surfaces (see `frontend/admin-sites.html` + `frontend/scripts/admin-sites.js` for inline wiring-contract comments):

| Surface | Endpoint (pending) | Today | Once wired |
|---|---|---|---|
| Lifecycle filter chips | `GET /sites?lifecycle=…` | Online/Offline live, others "—" | All 5 chips functional |
| Lifecycle status pill (6 states) | `site.lifecycle` column | Derived from `is_online` | Real state from schema |
| Enrollment status pill (4 states) | `site.enrollment.status` | Always "enrolled" | Real state from schema |
| Site Type dropdown | `POST /sites` body | Disabled, defaults to warehouse | Persisted, drives routing |
| Address (host or IP:port) | `POST /sites` body | Captured, not persisted | Validated + reachability-probed |
| Test Connection button | `GET <site>/api/health/ping` | Disabled | Cross-origin proxy or direct probe |
| Authentication Method | `POST /sites` body | Enrollment Key only | mTLS + SSO in Phase 2 |
| Enrollment expiry | `POST /sites` body | Disabled | Backend enforces |
| Enrollment key block | `POST /sites` response | Client-generated 256-bit token | Server-generated, hash-stored, shown once |
| Copy install command | n/a | `curl ... \| SITE_ID=... ENROLLMENT_KEY=... bash` | Real installer URL |
| MCS Subscriptions | `POST /sites` body | Disabled | Drives subscription replication |
| Provisioning Model | `POST /sites` body | Pattern A only | Pattern B routes through MCS user federation |
| Decommission action | `POST /sites/{id}/decommission` | Stub modal | Soft-retire, reversible |
| Archive action | `POST /sites/{id}/archive` | Stub modal | Long-term storage, decommissioned-only |
| Rotate key action | `POST /sites/{id}/enrollment/rotate` | Stub modal | Invalidate old key, issue new, show once |
| Revoke action | `POST /sites/{id}/enrollment/revoke` | Stub modal | Immediate MCS handshake block |
| Hard delete action | `DELETE /sites/{id}` (existing) | Typed-confirm with site ID | Same — server still refuses on dependencies |
| Lifecycle history drawer | `GET /sites/{id}/lifecycle-events` | Empty-state scaffold | Audit timeline per site |
| Archived collapsible section | `GET /sites?include_lifecycle=archived` | Empty-state scaffold | List of archived sites with restore option |

When the two Ubuntu test VMs are in hand, wire-up becomes a series of small per-endpoint diffs — the contracts, validation, and UX are already designed and visible.
