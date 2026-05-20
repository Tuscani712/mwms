# WMS Backend Schema · v0.1

> FastAPI + SQLAlchemy 2.0 + SQLite (Postgres-portable). Auth: JWT with per-site claims.

## Tables

### `sites`
Master directory of all warehouses/plants/MCS. Loaded by the login picker and stamped on every other row.

| Column | Type | Notes |
|---|---|---|
| `id` | str (PK) | Human code: `WHS-001`, `MCS`, etc. |
| `name`, `city`, `timezone` | str | |
| `is_master` | bool | Identifies the Master Control Site |
| `is_online`, `build_version` | bool, str | Surfaced in login status strip |

### `users`
Per-site identity. **Same employee can have rows at multiple sites with different roles.**

| Column | Type | Notes |
|---|---|---|
| `id` | int (PK) | |
| `site_id` | FK → sites | Scopes every login + every API call |
| `employee_code` | str (UQ) | Operator-facing ID |
| `email`, `full_name`, `role`, `permission_level` | | `role` is a legacy free string. **Preferred:** `role_id` FK below. |
| `hashed_password` | str | bcrypt |
| `is_active`, `last_login_at` | | |
| `department`, `shift` | str (nullable) | Legacy free strings. **Preferred:** `department_id` / `shift_id` FKs below. |
| `role_id` | FK → roles (nullable) | SCO-77 soft FK. When set, drives the auto-fill of `permission_level` from `roles.default_permission_level` (SCO-80). |
| `department_id` | FK → departments (nullable) | SCO-77 soft FK. Must match the user's site_id. |
| `shift_id` | FK → shifts (nullable) | SCO-77 soft FK. Must match the user's site_id. |
| `display_name` | str (nullable) | Chat-only; requires Lvl 3+ approval to change |
| `display_picture_url` | str (nullable) | Avatar URL; requires Lvl 3+ approval to change |
| `supervisor_id` | FK → users (nullable) | For future supervisor-approval routing |
| `theme` | str | UI theme preference ("dark" default, light theme stub in tokens.css) |

### `roles`, `departments`, `shifts` (SCO-76 org-metadata)
First-class entities driving the user-create pickers. Replace the free-string `User.role` / `User.department` / `User.shift` columns over time (soft migration — both forms live in parallel).

| Table | Per-site? | Columns | Notes |
|---|---|---|---|
| `roles` | nullable site_id | `name`, `default_permission_level` (1-5), `site_id` (NULL = global template), `is_active` | NULL site_id makes the role assignable from any site. Site-specific roles only assignable to users at that site. |
| `departments` | yes | `name`, `site_id`, `is_active` | Unique (site_id, name). "WHERE within the site" — Receiving, Shipping, QA, Maintenance, etc. |
| `shifts` | yes | `name`, `start_time`, `end_time`, `site_id`, `is_active` | Unique (site_id, name). Times stored as `Time` (not strings) so sites in different timezones aren't forced into a single corporate cadence. |

**Permission gates** (`services/orgmeta.py`):
- Lvl 3+ at a site can manage that site's departments / shifts / site-specific roles.
- Managing **global** roles (site_id IS NULL) requires MCS admin (Lvl 4+).
- Cross-site mutation requires MCS admin (Lvl 4+).

### `user_profile_fields`
Visibility/editability rules for profile fields. **Resolved at request time** with precedence
`user > role > site > global` — first match wins, defaults applied otherwise.

| Column | Notes |
|---|---|
| `scope_type` | one of: `global`, `site`, `role`, `user` |
| `scope_value` | NULL for global; site_id / role / employee_code otherwise |
| `field_name` | one of: `email`, `password`, `display_name`, `display_picture`, `theme` |
| `visible`, `editable` | booleans |

A client locking down email edits for all operators at WHS-001:
```
INSERT INTO user_profile_fields (scope_type, scope_value, field_name, visible, editable)
VALUES ('role', 'operator', 'email', true, false);
```

### `profile_change_requests`
Approval queue for fields gated by `APPROVAL_REQUIRED` in `services/profile.py` —
currently `display_name` and `display_picture`.

| Column | Notes |
|---|---|
| `user_id` | who requested |
| `field_name`, `requested_value` | the proposed change |
| `status` | `pending` / `approved` / `rejected` |
| `decided_by`, `decided_at`, `decision_notes` | filled in by approver (Lvl 3+) |

Approve endpoint: `POST /api/v1/admin/profile/requests/{id}/decide`. Approver must be at the
same site (or MCS). On approval, the requested value is written to the user row.

### `password_policies`
Per-scope password complexity + MFA rules. **Same resolution pattern as `user_profile_fields`** —
walks `user > role > site > global`, first row wins, sensible defaults if no row matches.

| Column | Notes |
|---|---|
| `scope_type` | one of: `global`, `site`, `role`, `user` |
| `scope_value` | NULL for global; site_id / role / employee_code otherwise |
| `min_length` | int, default 4 (validator floor) |
| `require_uppercase`, `require_lowercase`, `require_digit`, `require_special` | bools |
| `require_mfa` | bool — if true, a TOTP second factor is enforced at login for any matching user |

Example: lock down all level-3+ users to 12+ characters with MFA:
```
INSERT INTO password_policies (scope_type, scope_value, min_length, require_uppercase,
                               require_digit, require_special, require_mfa)
VALUES ('role', 'supervisor', 12, true, true, true, true);
```

### `user_mfa`
TOTP enrollment per user — RFC 6238, SHA1, 6 digits, 30-second window, ±1 step drift tolerance.

| Column | Notes |
|---|---|
| `user_id` | FK → users (unique — one MFA row per user) |
| `secret` | base32-encoded 160-bit secret, shown once at setup |
| `enabled` | false during pending enrollment, true after verify |
| `backup_codes_json` | JSON array of bcrypt-hashed one-time codes (8 codes generated at setup, consumed on use) |
| `verified_at`, `last_used_at` | audit timestamps |

Enrollment flow: `POST /profile/mfa/setup` (returns secret + otpauth URI + plaintext backup codes,
last time they're visible) → user scans QR → `POST /profile/mfa/verify` with 6-digit code → enabled.

Login flow when `require_mfa=true` for the resolved policy and the user is enrolled:
1. `POST /auth/login` returns `{access_token: null, mfa_required: true, mfa_challenge_token: "..."}`
2. Client prompts for TOTP / backup code
3. `POST /auth/mfa/verify` with `{challenge_token, code}` → full access token

Lost-device recovery: `POST /admin/policy/mfa-reset {user_id}` requires Level 4+ admin at the
same site (or MCS). Clears the row so the user re-enrolls on next login.

### `skus`, `locations`, `lots`, `lot_genealogy`
Inventory primitives.
- **SKU** carries `requires_qc`, `shelf_life_days`, `reorder_point`, `safety_stock`, `unit_weight_kg`.
- **Location** has `capacity`, `is_overflow`, `is_qa_hold` flags.
- **Lot** is the atomic traceable unit — `lot_code`, `sku_id`, `location_id`, `quantity`, `qa_hold`, `expires_at`, `supplier`.
- **LotGenealogy** is a many-to-many edge table linking parent lots → child lots with `quantity_consumed`. Production traceability requires this.

### Inbound: `asns`, `asn_lines`, `receipts`, `receipt_lines`
- **ASN** has `status` ∈ scheduled/arrived/receiving/received, plus `dock_door`, `eta`, `arrived_at`.
- **ASNLine** = SKU × expected_qty × received_qty × qc_status.
- **Receipt** records the act of receiving an ASN; `received_by` (user), `received_at`, `variance_notes`.
- **ReceiptLine** ties an ASN line to its new Lot, recording `qty_variance` as a first-class number.

### Outbound: `orders`, `order_lines`, `picks`, `shipments`
- **Order**: `status` ∈ open/picking/picked/loaded/shipped; `priority`, `ship_by`, `customer`, `truck_id`.
- **OrderLine**: SKU × qty_ordered × qty_picked × fefo_required.
- **Pick**: lot-level assignment (`lot_id`, `qty_picked`, `strategy` = FIFO/FEFO, `picker_id`).
- **Shipment**: truck container — `truck_capacity_kg`, `loaded_weight_kg`, `status`.

### Quality: `qc_holds`
Issue tracker for lots requiring quality decisions. `reason`, `severity`, `resolution` (release/rework/destroy), `opened_at`/`resolved_at`.

## Multi-site enforcement

Every domain table has `site_id`. The `get_current_user` dependency validates that the JWT's `site_id` claim matches an active user row at that site. A stolen WHS-001 token cannot query WHS-002 data — the user lookup itself fails.

## Migration story

- Dev: `Base.metadata.create_all` runs at app startup against SQLite for zero-friction iteration.
- Prod: Alembic. Models use a stable naming convention so generated migrations are diffable.
- Postgres-ready: no SQLite-specific types in the model layer.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/login` | Login → JWT with `{sub, site_id, role}` |
| GET | `/api/v1/auth/me` | Current user |
| GET | `/api/v1/sites` | All sites for login picker |
| GET | `/api/v1/health` | Status + build + uptime |
| GET | `/api/v1/health/ping` | Latency probe (frontend ping pill) |
| GET | `/api/v1/receiving/inbound` | Open ASNs |
| POST | `/api/v1/receiving/check-in` | Assign dock door, set status=receiving |
| POST | `/api/v1/receiving/receipts` | Record receipt + QC, mint Lots, capture variance |
| GET | `/api/v1/receiving/putaway-suggestions/{asn_id}` | FIFO primary + overflow locations |
| GET | `/api/v1/shipping/orders?status=...` | Orders list |
| GET | `/api/v1/shipping/consolidation/{order_id}/{line_id}` | Multi-lot FIFO/FEFO plan |
| POST | `/api/v1/shipping/picks` | Assign picks across lots |
| POST | `/api/v1/shipping/truck-load` | Load picked order, update truck weight budget |
| GET | `/api/v1/shipping/packing-slip/{order_id}` | Generate slip |
| GET | `/api/v1/profile` | Current user identity + per-field visibility/editability + pending requests |
| PUT | `/api/v1/profile/email` | Update email (rejected with 403 if field policy says not editable) |
| PUT | `/api/v1/profile/password` | Update password (requires current_password) |
| POST | `/api/v1/profile/display-name-request` | Submit display-name change → pending |
| POST | `/api/v1/profile/display-picture-request` | Submit display-picture change → pending |
| GET | `/api/v1/profile/requests` | My own change requests (history) |
| GET | `/api/v1/admin/profile/requests` | Pending requests visible to approver (Lvl 3+) |
| POST | `/api/v1/admin/profile/requests/{id}/decide` | Approve or reject |
| GET | `/api/v1/admin/profile/field-visibility` | List field-policy rows |
| PUT | `/api/v1/admin/profile/field-visibility` | Upsert a policy row (Lvl 3+) |
| GET | `/api/v1/profile/password-policy` | Resolved password policy for the calling user |
| GET | `/api/v1/admin/policy/password` | List all password policy rows (Lvl 3+) |
| PUT | `/api/v1/admin/policy/password` | Upsert a password policy row (Lvl 3+) |
| POST | `/api/v1/admin/policy/mfa-reset` | Clear a user's MFA enrollment (Lvl 4+) |
| GET | `/api/v1/profile/mfa/status` | Whether the calling user is enrolled in MFA |
| POST | `/api/v1/profile/mfa/setup` | Begin enrollment — returns secret, otpauth URI, backup codes |
| POST | `/api/v1/profile/mfa/verify` | Activate MFA by submitting a valid TOTP code |
| POST | `/api/v1/profile/mfa/disable` | User-initiated MFA removal (requires `{current_password}`) |
| POST | `/api/v1/profile/mfa/regenerate-codes` | Rotate MFA backup codes (requires `{current_password}`); old codes invalidated |
| POST | `/api/v1/auth/mfa/verify` | Step 2 of login — exchange challenge token + code for an access token |
| POST | `/api/v1/profile/picture/upload` | Multipart avatar upload — sanitizes + re-encodes via Pillow, returns sanitized URL |
| GET  | `/uploads/avatars/{file}` | Static-served avatars, `Content-Security-Policy: default-src 'none'` + `nosniff` |
| GET  | `/api/v1/admin/users` | Paginated user list. Filters: `site_id`, `role`, `level_min/max`, `q`, `include_inactive`, `limit`, `offset`. Same-site only for non-MCS. |
| POST | `/api/v1/admin/users` | Create user (Lvl 3+, strict outrank-only; MCS Lvl 4+ for cross-site). Returns 201. Accepts `role_id` / `department_id` / `shift_id`; auto-fills `permission_level` from role default (SCO-80). |
| GET  | `/api/v1/admin/users/{id}` | Fetch one (same-site for non-MCS) |
| PUT  | `/api/v1/admin/users/{id}` | Update mutable fields (email/full_name/role/permission_level/department/shift + FK ids; cross-site FK targets refused with 400) |
| GET  | `/api/v1/admin/roles` | List roles. Defaults to caller's site + globals; MCS Lvl 4+ sees everything. |
| POST | `/api/v1/admin/roles` | Create role. site_id=NULL ⇒ global, requires MCS Lvl 4+. Site-specific ⇒ Lvl 3+ at that site. |
| PUT/DELETE | `/api/v1/admin/roles/{id}` | Update or deactivate. |
| GET/POST/PUT/DELETE | `/api/v1/admin/departments` | Per-site CRUD (Lvl 3+ own-site; MCS Lvl 4+ cross-site). |
| GET/POST/PUT/DELETE | `/api/v1/admin/shifts` | Per-site CRUD (Lvl 3+ own-site; MCS Lvl 4+ cross-site). Times sent as `HH:MM:SS`. |
| DELETE | `/api/v1/admin/users/{id}` | Soft-delete via `is_active=false`. Cannot self-delete. |
| POST | `/api/v1/admin/users/{id}/reactivate` | Restore an inactive user |
| PUT  | `/api/v1/admin/users/{id}/supervisor` | Set/clear supervisor; enforces 5-tier outrank + same-site (or MCS) + cycle detection |
| PUT  | `/api/v1/admin/users/{id}/department` | Transfer department |
| PUT  | `/api/v1/admin/users/{id}/shift` | Change shift |
| GET  | `/api/v1/admin/users/{id}/subordinates` | Direct reports, active only |
| GET  | `/api/v1/admin/users/tiers/labels` | 5-tier ladder reference data for UI pickers |

## FEFO trigger

A line uses FEFO instead of FIFO when **either**:
1. `order_lines.fefo_required = true` (operator-set), OR
2. The earliest available lot for that SKU expires within `FEFO_THRESHOLD_DAYS` (default 7).

## Test coverage

`pytest` suite covers:
- Login success / wrong password / wrong site / JWT enforcement
- ASN inbound list, check-in flow, receipt with variance, putaway suggestions
- Order list, consolidation plan, pick assignment, insufficient-inventory error, truck load, packing slip
- Health endpoints
- Password policy resolution + complexity enforcement at the change-password endpoint
- MFA enrollment, TOTP verification, login-challenge flow, backup-code consumption, admin reset
- Avatar upload: format whitelist (PNG/JPEG/WebP/GIF), size + dimension caps, SVG rejection, polyglot strip via re-encode, server-generated filenames
- Admin user CRUD: permission gates at every entrypoint, same-site scoping, level-bound promotion, self-delete refusal, soft-delete + reactivate, role/search/pagination
- Hierarchy: tier labels endpoint, supervisor outrank invariant, same-site requirement (with MCS exception), self-supervisor refusal, cycle detection (A→B→C→A), dept/shift assignments, direct-reports listing excluding inactive
- End-to-end: full admin lifecycle (create → list → edit → assign supervisor → deactivate → reactivate) and paginated-search-then-supervisor-swap flows

125 tests · in-memory SQLite (StaticPool) · zero file artifacts. 46 of those tests are dedicated audit-fix regressions across `tests/test_security_audit_{fixes,quickwins,batch2,batch3}.py`.

## Audit log

Security-relevant events go to the `audit_log` table (`event_type`, `user_id`, `actor_id`, `site_id`, `ip`, `user_agent`, `occurred_at`, `detail_json`). Written by `wms/services/audit_log.py:record()`. Current emitters: `auth.login.{success,failure}`, `auth.password.changed`, `auth.mfa.disabled`, `auth.mfa.backup_codes_regenerated`. Log shipping, retention, and dashboards land with SEC-6.

## File uploads & avatar URL allowlist

`display_picture_url` accepts only paths under `/uploads/avatars/` produced by the sanitized upload pipeline. `http(s)://`, `data:`, `javascript:`, `file:`, traversal segments (`..`), and protocol-relative `//` paths are rejected with 400 at request-submission time. To open external avatars later, extend `_ALLOWED_PICTURE_PREFIXES` in `wms/services/profile.py`.

## Org hierarchy & permission model

5-tier ladder is the load-bearing decision for every admin operation:

| Level | Tier |
|---|---|
| 5 | Corporate (Corp) |
| 4 | Site Manager |
| 3 | Site / Department Supervisor |
| 2 | Department / Position Leader |
| 1 | Operator |

Permission rules in `services/users_admin.py` and `services/hierarchy.py`:

1. **Entry gate** — caller must be Level 3+ OR any MCS user to access `/admin/users`.
2. **Cross-site ops** — require the caller to be at the MCS site **and** Level 4+.
3. **Strict outrank** — caller can only modify users *below* their own level. Lvl 3 cannot touch another Lvl 3; promote-at-or-above-self is blocked.
4. **No self-deactivation** — lockout-prevention guardrail.
5. **Supervisor invariants** — supervisor must outrank (strict), be at the same site (or be MCS), can't be the user themselves, can't create cycles.

## File uploads

Avatars (display pictures) flow through `POST /api/v1/profile/picture/upload`. Hardening:

1. **Pillow-based decode + re-encode.** Bytes are parsed with `PIL.Image.open(...).verify()`, then re-saved through Pillow. Anything that isn't a real, parseable image is rejected; the persisted file is always Pillow's canonical re-encoding (EXIF/ICC stripped, polyglots broken).
2. **Format whitelist** (decode-side, not Content-Type-side): PNG, JPEG, WebP, GIF. **SVG explicitly rejected** (XSS vector). BMP / TIFF / ICO rejected (decoder CVE history; not needed).
3. **Size cap** — `max_upload_bytes` (default 2 MB). Read with `await file.read(max + 1)` so oversize aborts before the whole body lands in memory.
4. **Dimension cap** — `max_image_dimension` (default 2048 px) per side.
5. **Server-generated paths** — `data/uploads/avatars/{user_id}-{6-hex}.{ext}`. The extension is the decoded format, not the uploaded filename. No path-traversal surface.
6. **Static serving** — FastAPI `StaticFiles` at `/uploads/`. Middleware adds `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'` so browsers can't reinterpret bytes as HTML/JS.
7. **Approval gate preserved** — the upload returns a URL; the user still has to submit it via `/profile/display-picture-request`, which goes through the same Lvl 3+ approval workflow as a manually-pasted URL.

## Mock data seeder

`python -m wms.seeders.seed` populates the schema with reproducible mock data (seed=42):

- 5 sites (MCS + 4 warehouses; WHS-004 simulated offline)
- ~141 users across roles
- ~128 SKUs
- ~535 lots
- ~48 ASNs
- ~60 orders
- 12 shipments, ~25 QC holds

Default credentials: `MCS-ADMIN` / `admin1234`, or any `WHS-00X-001` / `password123`.
