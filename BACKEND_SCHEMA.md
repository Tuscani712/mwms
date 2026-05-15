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
| `email`, `full_name`, `role`, `permission_level` | | role ∈ operator/lead/supervisor/manager/admin |
| `hashed_password` | str | bcrypt |
| `is_active`, `last_login_at` | | |
| `department`, `shift` | str (nullable) | Read-only on profile page; client-managed |
| `display_name` | str (nullable) | Chat-only; requires Lvl 3+ approval to change |
| `display_picture_url` | str (nullable) | Avatar URL; requires Lvl 3+ approval to change |
| `supervisor_id` | FK → users (nullable) | For future supervisor-approval routing |
| `theme` | str | UI theme preference ("dark" default, light theme stub in tokens.css) |

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

23 tests · in-memory SQLite (StaticPool) · zero file artifacts.

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
