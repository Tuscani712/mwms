# WMS Pages Workflow — Phase 1 Completion Path

> Single source of truth for the remaining frontend pages, the backend logic they need, settings that surface in the eventual Admin → Settings page, and the edge cases each consumer must respect.
>
> **Sequencing principle**: specific pages first, settings page last. Each page below appends its candidate knobs to `SETTINGS_REGISTRY.md` so the settings UI is later a render-from-registry, not a speculative build.
>
> **Order is dependency-driven**: inventory → quality → production → reports → settings.

---

## Status snapshot (2026-05-20)

| Page | Backend | Frontend | Notes |
|---|---|---|---|
| `login.html` | ✅ | ✅ | Wired with multi-site picker + MFA challenge support |
| `index.html` (dashboard) | ⚠️ partial | ⚠️ partial | KPI tiles currently mock; no `/reports/dashboard` endpoint yet — SCO-52 |
| `profile.html` | ✅ | ✅ | Full identity + password + MFA + avatar upload |
| `users.html` | ✅ | ✅ | Admin user CRUD + hierarchy + **hard-purge w/ typed-DELETE modal (SCO-85)** |
| `admin.html` | ✅ | ✅ | Subnav + tile grid wired to Users / Org Metadata / Sites / Branding |
| `admin-orgmeta.html` | ✅ | ✅ | Roles + Departments + Shifts CRUD (SCO-77..82) |
| `admin-sites.html` | ✅ | ✅ | **NEW (SCO-84)** — site CRUD + toggle-online + master-site protection |
| `admin-branding.html` | ❌ | ⚠️ localStorage-only | No server persistence — folded into SCO-53 |
| `receiving.html` | ✅ | ✅ | Wired |
| `shipping.html` | ✅ | ✅ | Wired |
| `inventory.html` | ✅ | ✅ | **DONE (SCO-49)** — lot search + KPIs + adjust |
| `quality.html` | ❌ | ❌ | **SCO-50** (scaffold HTML exists, not wired) |
| `production.html` | ❌ | ❌ | **SCO-51** (scaffold HTML exists, not wired) |
| `reports.html` | ❌ | ❌ | **SCO-52** (scaffold HTML exists; also rewires dashboard KPIs) |
| `settings.html` (new) | ❌ | ❌ | **SCO-53** — registry-driven admin settings |

**Recent additions (post-2026-05-15):**
- **SCO-84** — Sites admin CRUD: `POST/PUT/DELETE/GET/{id}/toggle-online`. Master-site protections, audit events, in-process toggle cooldown. Commit `88d2ec8`.
- **SCO-85** — User hard-purge: `POST /admin/users/{id}/purge`. Lvl 5 only, typed-DELETE confirmation modal (no `confirm()`), audit FK nullification. Commit `f08233a`.
- **SCO-86** — `start.sh` launcher hardened: race-free restart, `wait_for_port_free/open` helpers, `[t]` smoke test with full auth + CRUD round-trips (13/13 green). Folded into commits 88d2ec8 + f08233a.

---

## 1. Inventory module — SCO-49

**Page**: `inventory.html` (design exists; no backend).
**Script**: `scripts/inventory.js` (new).
**Backend**: `wms/api/v1/inventory.py` + `wms/services/inventory.py` (new).

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/inventory/lots` | Paginated lot search |
| GET | `/api/v1/inventory/sku/{sku_code}` | SKU aggregate detail |
| GET | `/api/v1/inventory/kpis` | Site KPI tiles (5-min cache) |
| POST | `/api/v1/inventory/adjust` | Lot qty adjustment (Lvl 3+) |
| GET | `/api/v1/inventory/below-safety-stock` | SKUs under safety stock |

### Filters on `/lots`
`sku_code`, `lot_code`, `location_code`, `qa_hold` (bool), `expiring_within_days`, `aging_bucket` (one of `0-30/31-60/61-90/90+`), `q` (free text, case-insensitive), `limit`, `offset`.

### Logic & edge cases
- **Available qty**: `sum(lots WHERE qa_hold=false AND expires_at > now AND quantity > 0)`. QA-held and expired lots are visible but **never counted in available**.
- Lots in `is_overflow` or `is_qa_hold` locations get a UI badge.
- Adjustment is atomic: read-modify-write inside a transaction. Adjustment that brings qty below zero is rejected with 400.
- Negative adjustment emits `inventory.adjusted` with `was`/`now` in detail. Positive adjustment with `abs(delta) > inventory.adjust_large_threshold` requires Lvl 4+.
- Multi-site: `site_id` claim filters every query. Cross-site only via MCS Lvl 4+.
- Search: case-insensitive `LIKE LOWER(...)` with `%`/`_` escaped (LIKE-injection safety).
- `limit` clamped to `inventory.search_limit_max` (default 200). `offset` clamped at 0.
- Empty-state UI for "no lots match"; zero-state KPIs return zeros, not 500.

### Candidate settings → registry
- `inventory.aging_bucket_days` (list[int], default `[30, 60, 90]`)
- `inventory.expiring_soon_days` (int, default `7`)
- `inventory.adjust_large_threshold` (int, default `100`)
- `inventory.kpi_cache_ttl_sec` (int, default `300`)
- `inventory.search_limit_max` (int, default `200`)

### Tests
Paginated search, filter combinations, qa_hold exclusion, expired exclusion, adjust permission gate, adjust below-zero refusal, adjust audit event, multi-site isolation, LIKE-injection safety, empty-state shape.

---

## 2. Quality (QA) module — SCO-50

**Page**: `quality.html`. **Script**: `scripts/quality.js` (new).
**Backend**: `wms/api/v1/quality.py` + `wms/services/quality.py` (new).

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/quality/holds` | Paginated holds list (default `status=open`) |
| GET | `/api/v1/quality/holds/{id}` | Full hold detail (lot, supplier, age) |
| POST | `/api/v1/quality/holds` | Open hold on a lot |
| POST | `/api/v1/quality/holds/{id}/decide` | Release / rework / destroy (Lvl 3+) |
| GET | `/api/v1/quality/kpis` | Open count, severity histogram, oldest-open-days |
| GET | `/api/v1/quality/suppliers/performance` | Supplier defect % + trend |

### Logic & edge cases
- **Decide semantics**:
  - `release` → clears `lot.qa_hold=false`; lot returns to available.
  - `destroy` → zeroes `lot.quantity`, emits `lot.destroyed` audit; requires `quality.destroy_requires_level` (default 4).
  - `rework` → clears `lot.qa_hold` AND opens a *draft* production work order linked to the lot.
- Opening a hold on a lot that's already qa_held returns **409** with the existing hold ID (no duplicate holds).
- Idempotency: a second `decide` on the same hold returns 409 with the prior resolution.
- Cannot release a destroyed lot (quantity=0 implies no recovery).
- Audit events on every transition: `qc.hold.opened`, `qc.hold.released`, `qc.hold.destroyed`, `qc.hold.rework_opened`.
- **Escalation tiers** (UI color, server-flagged on each row):
  - ≤14d green / 15-21d yellow / 22-30d orange / >30d red.
- **Supplier performance**:
  - `defect_pct = holds_count / receipts_count` over window (default 90 days).
  - Trend = current window vs prior window.
  - Empty prior window → trend is `null`, not divide-by-zero crash.

### Candidate settings → registry
- `quality.hold_escalation_days` (list[int], default `[14, 21, 30]`)
- `quality.supplier_perf_window_days` (int, default `90`)
- `quality.destroy_requires_level` (int, default `4`)

### Tests
Open hold sets `lot.qa_hold=true`; duplicate-open 409; release returns to available; destroy zeroes qty; rework spawns draft WO; idempotent decide 409; age-bucket computation at boundaries (14/15/21/22/30/31); supplier trend with empty prior window; permission gates.

---

## 3. Production module — SCO-51

**Page**: `production.html`. **Script**: `scripts/production.js` (new).
**Backend**: `wms/api/v1/production.py` + `wms/services/production.py` + `wms/models/work_orders.py` (new).

### New tables
- `recipes(id, sku_id, version, locked_by, created_at)`
- `recipe_lines(recipe_id, ingredient_sku_id, qty_per_unit, uom)`
- `work_orders(id, recipe_id, recipe_version_snapshot, target_qty, status, started_at, completed_at, site_id, supervisor_id)`
- `work_order_reservations(work_order_id, lot_id, qty_reserved)`
- Reuse existing `lot_genealogy` for parent→child edges.

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/production/recipes` | List recipes (by SKU, version) |
| POST | `/api/v1/production/recipes` | Create recipe v1 |
| PUT | `/api/v1/production/recipes/{id}` | Edit → version bump |
| GET | `/api/v1/production/work-orders` | List with status filter |
| POST | `/api/v1/production/work-orders` | Create draft, snapshots recipe version |
| POST | `/api/v1/production/work-orders/{id}/preflight` | Reserve ingredient lots FIFO/FEFO |
| POST | `/api/v1/production/work-orders/{id}/start` | Move reserved → running |
| POST | `/api/v1/production/work-orders/{id}/complete` | Record yield + genealogy + decrement reservations |
| POST | `/api/v1/production/work-orders/{id}/cancel` | Release reservations (supervisor-only) |

### Logic & edge cases
- **Status state machine**: `draft → reserved → running → completed`. No back-skip; `cancel` is the only exit from `reserved`/`running` short of `completed`.
- **Recipe versioning**: editing a locked recipe creates a new version row. Running work orders keep their `recipe_version_snapshot`. Old versions stay queryable.
- **Atomic reservation**: pre-flight uses `BEGIN IMMEDIATE` (SQLite) / `SELECT ... FOR UPDATE` (Postgres) across all candidate lots, then writes reservation rows. Two simultaneous pre-flights on the same scarce lot must serialize, not double-allocate.
- **Shortage policy**: if any line is short, pre-flight returns **200** with `shortages[]` (NOT an error). `start` refuses unless `override=true` + override-reason + Lvl `production.shortage_override_requires_level` (default 4).
- **Yield variance**: > `production.yield_variance_threshold` (default 1%) emits `production.yield_variance_high` audit event AND a dashboard alert row. Both over- and under-yield count.
- **Genealogy**: every `complete` writes `lot_genealogy(parent_lot_id, child_lot_id, quantity_consumed)` rows per reservation. Orphan check (child lot with zero parents) flagged in nightly integrity scan.
- **BOM unit conversion**: recipe in kg, lot in lbs → convert via SKU's `unit_weight_kg`. If conversion impossible, preflight rejects with structured error.
- Cannot `complete` a WO not in `running`. Cannot `start` one not in `reserved`.
- `cancel` releases all reservation rows for the WO; idempotent (canceling a canceled WO returns 200 noop).

### Candidate settings → registry
- `production.yield_variance_threshold` (float, default `0.01`)
- `production.shortage_override_requires_level` (int, default `4`)
- `production.recipe_edit_requires_level` (int, default `3`)
- `production.fefo_threshold_days` (int, default `7` — promote existing constant)

### Tests
Recipe create + edit-bumps-version; WO retains version snapshot after recipe edit; preflight reserves FIFO; two parallel preflights serialize on the same lot; shortage returned not raised; `start` refused without override after shortage; `complete` writes genealogy edges; yield variance audit event (both directions); BOM unit conversion happy path + impossible-conversion; `cancel` releases reservations; idempotent cancel.

---

## 4. Reports & Metrics module — SCO-52

**Page**: `reports.html` + KPI tiles on `index.html`. **Scripts**: `scripts/reports.js` (new) + extend `scripts/dashboard.js`.
**Backend**: `wms/api/v1/reports.py` + `wms/services/metrics.py` (new — read-only aggregator).

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/reports/dashboard` | Home-page KPIs (cached) |
| GET | `/api/v1/reports/receiving` | Windowed: receipts, variance %, by-supplier |
| GET | `/api/v1/reports/shipping` | Orders shipped, on-time %, FEFO compliance |
| GET | `/api/v1/reports/production` | Yield % by recipe, WO count, variance histogram |
| GET | `/api/v1/reports/inventory-aging` | Aging buckets across all lots |
| GET | `/api/v1/reports/genealogy/{lot_code}` | Full ancestry walk |
| GET | `/api/v1/reports/outliers` | Per-user picks/hour anomalies |
| GET | `/api/v1/reports/export/csv` | Streamed CSV (params: `report=<name>&from=&to=...`) |

### Logic & edge cases
- All endpoints **read-only** — no writes from this module.
- Cache key = `(site_id, report_name, params_hash)`. TTL = `reports.cache_ttl_sec` (300s).
- Manual `?refresh=1` bypasses cache; emits `reports.cache_busted` event (catches abuse via audit log).
- Empty data → return zeros, never raise.
- **Date-range guard**: max `reports.date_range_max_days` (default 365). Longer → 400.
- **CSV streaming**: row-by-row generator using `StreamingResponse`, NOT an in-memory list. Hard cap at `reports.csv_max_rows` (default 50,000).
- **Genealogy walk**: recursive walk with `reports.genealogy_max_depth` (default 25) to prevent runaway queries on pathological cycles. Cycle detection raises 409.
- **Outlier detection**: bucket picks by user over window, compute mean+stddev, flag anything > `(1+threshold)*mean` or < `(1-threshold)*mean`. Threshold default 0.20. Threshold flag applies to both directions (under-performers AND suspiciously-fast).
- **Multi-site rollup**: MCS only. Non-MCS callers always see only their own site.

### Candidate settings → registry
- `reports.cache_ttl_sec` (int, default `300`)
- `reports.csv_max_rows` (int, default `50000`)
- `reports.date_range_max_days` (int, default `365`)
- `reports.outlier_threshold` (float, default `0.20`)
- `reports.genealogy_max_depth` (int, default `25`)

### Tests
Dashboard KPI shape; cache hit vs miss; manual refresh emits audit event; CSV is streamed (assert generator type, not list); date-range guard at 366; outlier flagging in both directions; genealogy walks parents only (not children); cycle detection 409; empty-data returns zeros.

---

## 5. Admin → System Settings page — SCO-53

**Page**: `settings.html` (new), reached from Admin tile.
**Script**: `scripts/settings.js` (new).
**Backend**: `wms/api/v1/settings.py` + `wms/services/settings_store.py` + `wms/services/settings_registry.py` + `wms/models/settings.py` (new).

### New table
`settings(key PK, value_json, type, scope_type, scope_value, updated_by, updated_at)` — same scope precedence as `password_policies` and `user_profile_fields`: `user > role > site > global`, first match wins.

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/admin/settings/registry` | UI form schema (keys, types, defaults, bounds, descriptions, who-can-edit) |
| GET | `/api/v1/admin/settings` | Resolved values for caller's scope |
| PUT | `/api/v1/admin/settings/{key}` | Upsert at given scope; type + bounds validated |
| POST | `/api/v1/admin/settings/{key}/reset` | Delete override at scope → falls through to next precedence |
| POST | `/api/v1/admin/settings/reload` | Bust the in-process cache |
| POST | `/api/v1/admin/settings/branding/logo` | Per-site logo upload (reuses avatar Pillow pipeline) |

### Logic & edge cases
- **Registry is code-defined**, NOT DB-defined (`wms/services/settings_registry.py`). Adding a new setting = one registry entry + a default + a getter that consumes it. Prevents arbitrary keys from being injected via PUT.
- **Type validation per entry** — `int`, `bool`, `enum`, `list[int]`, `float`. Bounds (`min`/`max`) enforced server-side.
- Every PUT / RESET emits `settings.changed` with `key, old_value, new_value, scope, actor_id` in detail.
- **Branding sub-form**: logo upload reuses `wms/services/uploads.py` Pillow pipeline. Stored at `data/uploads/branding/{site_id}.{ext}`. Public-served at `/uploads/branding/{site_id}.{ext}`. CSP + nosniff headers same as avatars.
- **Site-offline toggle**: client-side confirm modal + server-side cooldown (min 60s between toggles) to prevent flap. Toggling immediately invalidates all tokens for that site (existing L-4 logic).
- **Cache**: per-process LRU. `reload` clears it. Multi-worker / multi-process deployment needs pub/sub later — flagged in roadmap, NOT pre-staged.
- **Reset to default** = `null` value at the requested scope → falls through to next precedence.
- **Resilience**: every getter has a hardcoded fallback default so a corrupt row never crashes startup.
- Permission gates: Lvl 4+ for site-scope; Lvl 5 / MCS for cross-site or global scope.

### Tests
Registry-only keys accepted (random key → 400); type validation rejects wrong types; bounds enforced (min-1 / max+1 rejected); scope precedence resolution; reset falls through; reload clears cache (cache_hit before reload, cache_miss after); audit event with full detail; branding upload reuses Pillow pipeline; site-offline cooldown returns 429 within 60s of last toggle; corrupt row falls back to default not 500.

---

## 6. Sites admin module — SCO-84 ✅ SHIPPED 2026-05-20

**Page**: `admin-sites.html`. **Script**: `scripts/admin-sites.js`.
**Backend**: extended `wms/api/v1/sites.py`.

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/sites` | List (open to login picker) |
| GET | `/api/v1/sites/{id}` | Detail + user_count + department_count |
| POST | `/api/v1/sites` | Create (MCS Lvl 5) |
| PUT | `/api/v1/sites/{id}` | Update name/city/timezone/build_version (MCS Lvl 4) |
| DELETE | `/api/v1/sites/{id}` | Hard delete (MCS Lvl 5, FK-safe) |
| POST | `/api/v1/sites/{id}/toggle-online` | Flip `is_online` (MCS Lvl 4, cooldown) |

### Logic & edge cases
- **Site id format**: `^[A-Z][A-Z0-9-]{1,31}$`, uppercased server-side. Immutable after create.
- **One-master rule**: refusing `is_master=true` when a master already exists (409).
- **Toggle cooldown**: 60s minimum between toggles per site, in-process dict (`_last_toggle_at`). Returns 429 within window. NB: multi-worker deployments need a shared store — flagged in code.
- **Master site protections**: cannot delete, cannot take offline. Prevents auth-path lockout.
- **FK-safe delete**: refuses with 409 if any users or departments still reference the site. Returns counts in the error detail so the admin knows what to reassign.
- **Audit events**: `site.created`, `site.updated`, `site.deleted`, `site.online_toggled`. Update event uses diff-only detail (`{field: {was, now}}`).
- **Frontend gating**: destructive controls hidden when caller isn't master-Lvl-5. Server still enforces independently.

### Tests
12 covering: list-open-to-any, operator denied, non-master-Lvl-5 denied, full CRUD happy path, cannot-delete-master, cannot-take-master-offline, refuse-when-users-exist, refuse-when-departments-exist, id-format validation, duplicate-409, one-master-409, cooldown release after window.

---

## 7. User hard-purge — SCO-85 ✅ SHIPPED 2026-05-20

**Page**: `users.html` (extended). **Script**: `scripts/users.js` (extended).
**Backend**: extended `wms/api/v1/admin_users.py` + `wms/services/users_admin.py`.

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/admin/users/{id}/purge` | Hard-delete user row (Lvl 5, irreversible) → 204 |

The existing `DELETE /admin/users/{id}` is unchanged — it remains a soft-archive (`is_active=False`, reversible via `/reactivate`). Purge is the distinct irreversible verb.

### Logic & edge cases
- **Permission**: Lvl 5 only.
- **Self-purge refused**: 403 with "yourself" in detail.
- **Last-admin guard**: refuses to delete the only remaining active Lvl 5 user (system-lockout protection). Coverage at the service layer (HTTP path requires multiple concurrent admins for test setup).
- **Subordinate guard**: 409 if the user has any active subordinates pointing at them via `supervisor_id`. Detail includes the count.
- **Audit preservation**: instead of cascade-deleting `audit_log` rows that reference the target via `user_id`/`actor_id`, we `UPDATE … SET … = NULL` for both columns. The historical trail survives the user it describes.
- **User-owned cascade**: `UserMFA` (1:1) and `ProfileChangeRequest` (NOT NULL `user_id`) rows are deleted explicitly. `ProfileChangeRequest.decided_by` is nullified.
- **Audit event**: `user.purged` recorded *before* the row is deleted, with full snapshot (id/employee_code/email/full_name/site_id/role/permission_level/was_active) in `detail_json`.

### Frontend confirmation
- Custom modal (NOT `window.confirm()` — clients can disable native dialogs).
- "Delete forever" button is disabled until the input value exactly equals `DELETE` (case-sensitive).
- Dismissible via Cancel button / X / Escape / backdrop click — none can trigger the call.
- In-modal error surface for server-side refusals (409 subordinate count, 403 last-admin).

### Tests
8 covering: happy path 204, GET-after-purge 404, audit-event-with-snapshot, audit-history-preserved-with-FK-nulled, Lvl 4 denied, self-purge denied, last-admin guard (service layer), subordinate-blocked, 404-for-missing-user.

---

## Cross-cutting workflow rules (apply to every new page)

1. **Auth gate** — every endpoint uses `get_current_user`; site claim validated.
2. **Multi-site isolation** — cross-site only via MCS Lvl 4+.
3. **Audit log** — every state transition writes via `wms/services/audit_log.py:record()`.
4. **Body size cap** — `BodySizeLimitMiddleware` already covers all JSON; uploads use their own caps.
5. **Frontend escape discipline** — every rendered field flows through `escapeHtml()`. No `innerHTML` of server data. Pending audit M-3 covers a sweep.
6. **Pagination convention** — `limit` ≤ registry-defined max; `offset` clamped at 0.
7. **Empty-state UI** — every list page renders a zero-state; never a blank pane.
8. **Loading-state UI** — every fetch shows a skeleton or spinner; 401 redirects to login; 5xx shows a retry banner.
9. **Settings registry contract** — adding a knob = appending one row to `SETTINGS_REGISTRY.md` in the same commit.

---

## Swagger / OpenAPI verification

FastAPI auto-publishes `/openapi.json` and `/docs`. Each new router (`inventory`, `quality`, `production`, `reports`, `settings`) must be mounted in `wms/main.py:create_app()`. Each endpoint must have `response_model`, `summary`, and `tags=[...]` so the Swagger group reads cleanly.

**Acceptance check per task**:
```bash
curl -s http://127.0.0.1:8775/openapi.json | jq '.paths | keys | map(select(startswith("/api/v1/<module>")))'
```
must return the expected new paths, and `/docs` must render the new tag without missing-schema errors.

---

**Version**: 1.1  
**Last Updated**: 2026-05-20  
**Owner**: Meatbag / claude  
**See also**: `IMPLEMENTATION_ROADMAP.md`, `BACKEND_SCHEMA.md`, `FRONTEND_DESIGN_SCHEMA.md`, `SETTINGS_REGISTRY.md`
