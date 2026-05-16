# WMS Implementation Roadmap: Phase 1 (MVP) vs Phase 2 (Enhancement)

## Overview
**Phase 1**: Core functional MVP with operational foundation (est. 4-6 months)  
**Phase 2**: Polish, advanced features, external portals (est. 3-4 months)

---

## Current Status (2026-05-15)

### ✅ Frontend Scaffold (v0.1)
- 10 pages live (Dashboard, Login w/ multi-site picker, Receiving, Shipping, Production, Quality, Inventory, Reports, Admin, Admin-Branding)
- Industrial Editorial design system: tokens.css, base.css, components.css, page.css, dashboard.css
- Live clock, uptime ticker, ping pill (Green ≤74ms · Yellow 75-149ms · Red ≥150ms)
- Client logo upload + brand-mark swap via localStorage

### ✅ Backend Scaffold (v0.1)
- FastAPI + SQLAlchemy 2.0 + SQLite (Postgres-portable), Pydantic v2
- JWT auth with per-site claims, bcrypt password hashing
- Schema: Sites, Users, SKUs, Locations, Lots, LotGenealogy, ASNs, Receipts, Orders, Picks, Shipments, QCHolds
- Mock seeder: 141 users, 128 SKUs, 535 lots, 48 ASNs, 60 orders, 12 shipments across 5 sites
- 16 pytest tests covering auth, receiving flow, shipping flow, health
- Ruff lint clean

### ✅ Receiving Module (Core endpoints + Frontend wired)
- `GET /receiving/inbound` — open ASNs
- `POST /receiving/check-in` — assign dock door
- `POST /receiving/receipts` — record receipt + variance + auto-create Lot
- `GET /receiving/putaway-suggestions/{asn_id}` — FIFO primary + overflow
- Frontend table populates live when authed; falls back to mock on demo

### ✅ Shipping Module (Core endpoints + Frontend wired)
- `GET /shipping/orders` — orders list
- `GET /shipping/consolidation/{order_id}/{line_id}` — FIFO/FEFO multi-lot plan
- `POST /shipping/picks` — assign picks across lots (decrements lot qty)
- `POST /shipping/truck-load` — load order onto shipment, track weight
- `GET /shipping/packing-slip/{order_id}` — generate slip from picks

### ✅ Session UX (operator layer · in progress)
- Active site label (`WHS-002 · HOU`) persists in `localStorage.wms.activeSiteLabel` at login
- All pages auto-bind `data-bind="site-name"` / `data-bind="user-name"` / `data-bind="user-initial"` to the live session
- User chip (top-right) is a click-to-sign-out trigger — confirm dialog clears token + session keys → back to login
- Login form shows inline error banner on 401 (no more silent dashboard redirect)
- "Backend unreachable" vs "Bad credentials" surfaced as distinct error messages

### ✅ User Management — Profile Layer
- New `profile.html` page reached in **3 clicks max** from anywhere: click the user chip in the topbar.
- **Read-only identity panel**: Real Name, Employee ID, Site, Department, Role, Shift, Permission Level, Active status.
- **Editable settings panel**: Email, Password, Chat Display Name (approval-gated), Display Picture (approval-gated), Theme (Coming Soon stub), Logout.
- **Field-level visibility/editability** resolved per request with precedence **user > role > site > global**. Client can disable/enable any field at any scope via a single row in `user_profile_fields`.
- **Approval workflow**: `display_name` and `display_picture` create `ProfileChangeRequest` rows; Level 3+ users (or in future, direct supervisors) decide via `/admin/profile/requests/{id}/decide`.
- Operator-role default policy seeded: email visible but not editable (forces request to supervisor); theme visible but not editable (coming soon).
- 7 new pytest tests covering: identity readout, email gate, password current-password check, request submission, user-scope override of role-scope, admin approval applying the change.

### ✅ Password Policy + MFA Enforcement (security layer)
- New `password_policies` table — client-configurable rules with the **same precedence ladder as profile fields** (`user > role > site > global`). One row per scope; first match wins.
- Configurable per scope: `min_length`, `require_uppercase`, `require_lowercase`, `require_digit`, `require_special`, `require_mfa`.
- Validator runs at `PUT /profile/password` — rejects weak passwords with a structured error naming the failing rule (`"Password must contain a special character"`, etc.).
- `GET /profile/password-policy` lets the frontend render the *active* rules for the calling user (e.g., "Must be 12+ chars with a digit and special").
- Admin endpoints (`/admin/policy/password` GET/PUT) — Level 3+ can author rules for any scope.
- **TOTP MFA (RFC 6238)** — stdlib-only implementation, no extra deps:
  - `POST /profile/mfa/setup` returns `{secret, otpauth_uri, backup_codes}` (8 one-time codes shown once; stored bcrypt-hashed).
  - `POST /profile/mfa/verify` activates the enrollment after the user proves the authenticator works.
  - When `require_mfa` resolves true and the user IS enrolled, login returns `{access_token: null, mfa_required: true, mfa_challenge_token}` instead of a token; client posts to `POST /auth/mfa/verify {challenge_token, code}` to complete login. Accepts TOTP **or** a one-time backup code (consumed on use).
  - When `require_mfa` resolves true but the user is NOT enrolled, login returns a token with `mfa_enrolled: false` so the frontend redirects to forced enrollment.
  - Admin recovery: `POST /admin/policy/mfa-reset {user_id}` — Level 4+ at the same site clears MFA for a lost-device user.
- 10 new pytest tests covering: enrollment + verify, challenge flow, backup-code single-use, policy-driven gating, admin reset, non-admin denial — **all 37 tests green, ruff clean.**

### ✅ Security Audit + Pre-Staged Fixes (SCO-38 + SCO-39/40/41 + SCO-42/43/44 + SCO-45/46/47/48)
- **Red-team audit** of the codebase + docs produced `SECURITY_AUDIT.md` with 26 findings (1 critical, 6 high, 8 medium, 7 low, 5 info), each annotated with attack scenario, suggested fix, and stage-now/defer judgement. Seven follow-up tickets proposed (SEC-1..SEC-7).
- **Seven fixes pre-staged**, each chosen because scaffolding now is cheaper than retrofitting later:
  - **C-1** — `Settings.assert_secure_for_env()` refuses to boot prod with the dev sentinel `secret_key`.
  - **H-2** — `POST /profile/mfa/disable` requires `{current_password}` (XSS-stolen tokens can no longer disable MFA).
  - **H-4 prep** — `login_attempts` schema in place for SEC-1's future rate-limiter (saves a second migration).
  - **M-4** — Generic "Invalid or expired challenge token" (removes signature-vs-expiry oracle).
  - **L-4** — `get_current_user` rejects tokens for sites with `is_online=False`.
  - **L-7** — `User.__repr__` scrubs `hashed_password` (debug-print safe).
  - **M-6** — Email format regex on admin user payloads (blocks `<script>` and obvious garbage).
- **M-1** — bcrypt byte-length validator on `PasswordUpdate.new_password` and `UserCreate.password` (rejects UTF-8 > 72 bytes with 422 before bcrypt silently truncates).
- **M-5** — `BodySizeLimitMiddleware` caps JSON bodies at 1 MB (returns 413); upload endpoint exempt because it has a stricter content-aware cap.
- **L-2** — Compat upper bounds on every runtime + dev dependency in `pyproject.toml`.
- **M-7** — `display_picture_url` conservative allowlist (`/uploads/avatars/` only); rejects `http(s)://`, `data:`, `javascript:`, `file:`, traversal, protocol-relative paths.
- **M-8** — `POST /profile/mfa/regenerate-codes` (password-gated). Rotates the backup-code set; old codes immediately fail verification.
- **I-4** — `ApprovalDecision.notes` capped at `max_length=500` in schema (DB column was already 500; client now gets a clean 422).
- **L-1 (partial)** — `audit_log` table + `wms/services/audit_log.py` writer. Wired to login success/failure, password change, MFA disable, and MFA backup-code regeneration. SEC-6 still owns shipping/alerting/retention.
- 46 regression tests across four audit-fix test files. **125/125 pytest green**, ruff clean.

### ✅ Admin User Management (SCO-33: SCO-35 + SCO-36 + SCO-37)
- **Backend CRUD** (SCO-35) — `POST/GET/PUT/DELETE /api/v1/admin/users` + `/reactivate`. Paginated list with `site_id`, `role`, `level_min/max`, `q` search, `include_inactive`. Soft-delete via `is_active=false`.
- **Permission model** layered: Lvl 3+ entry; **strict outrank** rule (Lvl 3 cannot edit another Lvl 3); **cross-site requires MCS Lvl 4+**; cannot self-deactivate.
- **Hierarchy layer** (SCO-36) — 5-tier ladder (Corp → Site Mgr → Site/Dept Supervisor → Dept/Position Leader → Operator) with `GET /admin/users/tiers/labels` reference endpoint.
- **Supervisor invariants** enforced server-side: strict outrank, same-site (unless MCS), no cycles, no self-supervision. Cycle detection walks the supervisor chain on every assignment.
- **Assignment endpoints** — `/admin/users/{id}/{supervisor,department,shift}` plus `/subordinates` listing direct reports (active only).
- **Admin frontend** (SCO-37) — new `users.html` reachable in 3 clicks (Dashboard → Admin → Manage users tile). Filterable table with role/tier pills, search-as-you-type (250ms debounce), pagination, deactivate/reactivate inline, edit modal with dynamically-filtered supervisor picker (auto-refreshes when target tier changes), client-side HTML escaping on every rendered field.
- **30 new tests** (16 CRUD + 14 hierarchy + 2 end-to-end). Total **79 pytest tests, all green**. Ruff clean.

### ✅ Profile Picture Browse + Sanitized Upload
- New **"Browse…"** button on the profile picture row (`profile.html`) opens a native file picker scoped to `image/png,image/jpeg,image/webp,image/gif`.
- Selected file shows filename + size pre-upload; client-side 2 MB guardrail mirrors server cap.
- Backend `POST /profile/picture/upload`: **server never trusts the client.** Bytes are parsed by Pillow (`verify()` then `Image.open(...).load()`), format-checked against a decode-side whitelist (PNG/JPEG/WebP/GIF — SVG/BMP/TIFF rejected), capped at 2 MB and 2048 px/side, then **re-encoded** through Pillow so EXIF/ICC metadata is stripped and polyglot payloads (e.g., HTML/JS appended after a valid PNG) are silently dropped.
- Saved as `data/uploads/avatars/{user_id}-{6-hex}.{decoded_ext}` — server-generated path, no traversal surface.
- Static-served at `/uploads/` with `X-Content-Type-Options: nosniff` + `Content-Security-Policy: default-src 'none'` so browsers can't reinterpret bytes as executable.
- The returned URL still flows through the existing `/profile/display-picture-request` approval queue — Lvl 3+ approval gate is intact.
- 10 new pytest tests covering: PNG/JPEG/WebP acceptance, SVG rejection, fake-PNG-actually-text rejection, oversize, oversized dimensions, polyglot strip, path-traversal filename, and full upload→approval flow.

### ✅ Local Dev Launcher (`./start.sh`)
- One-shot environment check + boot:
  - Detects Python 3, creates `backend/.venv` if missing
  - Installs deps only when imports fail (cache-friendly)
  - Seeds DB only when `backend/data/wms.db` is absent
  - Detects port collisions on 8000 / 8765, interactively offers to kill occupants
  - Tracks PIDs in `.run/{backend,frontend}.pid`, logs in same dir
- Post-launch menu: status, tail logs, restart, open browser, quit
- Graceful CTRL+C via `trap shutdown INT TERM`

### 🔜 Next Up — see [`PAGES_WORKFLOW.md`](./PAGES_WORKFLOW.md) for full per-page workflow, endpoints, edge cases, and tests

**Page completion path (dependency-ordered)**:
1. **SCO-49** — Inventory module (backend + `inventory.html` wiring, search/KPIs/adjust/safety-stock)
2. **SCO-50** — Quality (QA) module (hold workflow, escalation tiers, supplier defect trending)
3. **SCO-51** — Production module (work orders, recipe BOM with versioning, genealogy, atomic reservation)
4. **SCO-52** — Reports & Metrics (dashboard KPIs, CSV streaming, outliers, genealogy walks)
5. **SCO-53** — Admin → System Settings page (registry-driven, type/bound-validated, branding upload, site-offline toggle)

Settings page lands **last** so it renders from a known registry (`SETTINGS_REGISTRY.md`) instead of speculating. Each page above appends its candidate knobs to the registry in the same commit that introduces the consumer code.

**Other deferred work (not in the 5-task path)**:
- Frontend wiring for MFA enrollment UI on `/profile.html` (QR code render, backup-code display, "Set up MFA" CTA when policy requires)
- Frontend wiring for the 2-step login challenge (post password → if `mfa_challenge_token` present, show 6-digit input)
- MCS / corporate-rollup layer (admin-scoped endpoints + view)
- Alembic migrations (currently using `create_all` for dev convenience)
- Multi-site federation (per-site DBs, MCS service)
- Remaining audit findings: H-1 rate-limit, H-3 token storage, H-5 PyJWT, H-6 CSP; M-2 password history, M-3 HTML escape sweep; L-1 shipping/alerting (SEC-6), L-5 token TTL, L-6 CSRF

---

## PHASE 1: CORE MVP (Foundational)

### Priority 1 - CRITICAL PATH (Foundation)

#### Module 1: Core Inventory Management
- [x] SKU master data + UOM support (units, lbs, volume)
- [x] Location master data + capacity rules (qty/weight limits)
- [x] Lot/batch tracking (UID generation + scanning)
- [x] Inventory tiers (on-hand, available, QA_HOLD, reserved, blocked)
- [x] FIFO putaway + FIFO picking logic
- [x] Inventory adjustments + reason codes + audit trail
- [x] Real-time inventory visibility (queries)

#### Module 2: Receiving Operations
- [x] Inbound scan + ASN matching
- [x] Variance handling (>1% requires approval)
- [x] Quality check (QC) - mandatory, blocking
- [x] Damage assessment (minor vs major)
- [x] Location assignment (FIFO + capacity rules)
- [x] Label generation + printing
- [x] Receiving reports (shift-based)

#### Module 3: Shipping Operations
- [x] Order management + pending orders view
- [x] Pick task assignment + execution
- [x] FIFO picking validation
- [x] FEFO picking (expiration <7 days, configurable)
- [x] Multi-lot shipment consolidation
- [x] Single packing slip (multi-lot format)
- [x] Order modification workflow (picked vs unpicked)
- [x] Truck weight limit enforcement
- [x] Shipping reports (accuracy, on-time %)

#### Module 4: Production Operations
- [x] Work order management
- [x] Recipe/BOM definition + versioning
- [x] Ingredient consumption tracking
- [x] Pre-flight availability check (reserve ingredients)
- [x] Ingredient shortage handling (override + consolidation)
- [x] Yield tracking (actual vs expected)
- [x] Yield variance alerts (>1% threshold)
- [x] Lot genealogy: ingredient lots → produced lots (real-time + batch reporting)
- [x] Production reports (throughput, yield %)

#### Module 5: Quality Assurance
- [x] Item hold workflow (QC issues)
- [x] Hold duration monitoring (14d, 15-21d, 21-30d, 30+ escalation)
- [x] Item release/destroy decisions
- [x] QA_HOLD inventory separation (not in available)
- [x] Supplier defect tracking (% + trend + cost impact)
- [x] QA reports (hold metrics, supplier performance)

#### Module 6: Metrics & Reporting
- [x] Operational dashboard (5-min refresh, cached)
- [x] KPI reports (daily + on-demand)
- [x] Outlier detection (per-user + team baselines, 20% threshold)
- [x] Supplier performance tracking (on-time, defect %, cost)
- [x] Lot genealogy report (daily auto + manual on-demand)
- [x] Inventory aging report (items > N days)
- [x] QA hold aging (items > N days)
- [x] Supplier defect rate trending

#### Module 7: User Management & Permissions
- [x] 5-level permission hierarchy (Lvl 1-5)
- [x] Role-based access control (module-level)
- [x] User + shift management
- [x] Department/team hierarchy
- [x] Audit logging (all actions, reasons, before/after values)
- [x] Session management + password policy
- [x] API token generation + rate limiting

#### Module 8: System & Infrastructure
- [x] PostgreSQL database (relational integrity)
- [x] Multi-database architecture (User DB, Inventory DB, Chat DB, Metrics DB)
- [x] Data encryption at rest + in transit
- [x] Automated backups (daily)
- [x] Audit trail (hot 1-month, archive N years)
- [x] Per-warehouse configuration (if multi-warehouse)
- [x] Integration APIs (basic framework for Phase 2)

---

### Priority 2 - HIGH VALUE (Operational Efficiency)

#### Feature Set
- [x] Slow-moving inventory tracking + clearance recommendations
- [x] Safety stock management + reorder points
- [x] QC + Ingredient expiration enforcement (KPI + alerts)
- [x] Expired ingredient override tracking (metrics)
- [x] Cycle count (annual + configurable audits)
- [x] Chat system (instant messaging + groups)
- [x] Daily lot genealogy auto-report generation
- [x] Inventory transfers (multi-warehouse if enabled)
- [x] Supplier performance trending

---

### Priority 3 - NICE-TO-HAVE (MVP Completion)

#### Feature Set
- [ ] Handheld RF device pairing (picking)
- [ ] Email notifications + dashboard alerts
- [ ] Advanced role customization (per-feature toggles)
- [ ] Client configuration UI (thresholds, settings)
- [ ] Multi-currency support (if needed)
- [ ] Advanced filtering in reports

---

## PHASE 2: ENHANCEMENTS & ADVANCED FEATURES

### Priority 1 - HIGH IMPACT (Advanced Workflows)

#### Rework Module (Full)
- [ ] Rework decision tree (cost-benefit analysis)
- [ ] Rework work order creation + tracking
- [ ] Yield recalculation (rework vs scrap cost)
- [ ] Rework completion audit trail
- [ ] Rework metrics + reporting

#### Labor Management
- [ ] Task assignment + routing optimization
- [ ] Time-and-motion tracking (labor hours per task)
- [ ] Productivity metrics (picks/hour, units/hour by employee)
- [ ] Shift capacity planning
- [ ] Training + certification tracking

#### Advanced Forecasting
- [ ] Demand prediction (historical data → ML models)
- [ ] Seasonal demand adjustment
- [ ] Safety stock optimization (dynamic)
- [ ] Forecast accuracy tracking + alerts
- [ ] Demand vs actual trending

---

### Priority 2 - MEDIUM IMPACT (External Integration)

#### Supplier Portal
- [ ] Self-service ASN upload
- [ ] Supplier performance dashboard
- [ ] Defect tracking + trending (supplier view)
- [ ] PO acknowledgment workflow

#### Customer Portal
- [ ] Order status visibility
- [ ] Shipment tracking + tracking numbers
- [ ] Lot genealogy report (customer-facing)
- [ ] Invoice + receipt access
- [ ] Returns/complaint submission

#### Returns Management
- [ ] RMA (Return Merchandise Authorization) workflow
- [ ] Inbound return receipt + inspection
- [ ] Refund/credit decision workflow
- [ ] Return analytics + trending

---

### Priority 3 - NICE-TO-HAVE (Operational Optimization)

#### Equipment Maintenance
- [ ] Preventive maintenance scheduling
- [ ] Machine downtime tracking (integration with production)
- [ ] OEE (Overall Equipment Effectiveness) calculation
- [ ] Maintenance cost tracking

#### Multi-Warehouse Orchestration
- [ ] Demand allocation across warehouses
- [ ] Warehouse transfer optimization
- [ ] Inventory redistribution recommendations
- [ ] Cross-warehouse KPI comparisons

#### Multi-Site Federation (see MULTI_SITE_ARCHITECTURE.md)
- [ ] **Phase 1**: Site selector visible on login (single-entry directory hardcoded)
- [ ] **Phase 1**: Per-site `/api/health` + `/api/health/ping` endpoints
- [ ] **Phase 1.5**: Master Control Site (MCS) scaffolded as separate deployment
- [ ] **Phase 1.5**: Site Directory API on MCS — sites fetch + cache, signed payload
- [ ] **Phase 1.5**: Per-site authentication enforced (sessions don't cross sites)
- [ ] **Phase 1.5**: Site Directory cached locally for graceful MCS-offline mode
- [ ] **Phase 2**: MCS user federation (push provisioning to assigned sites)
- [ ] **Phase 2**: Corporate KPI rollup dashboard at MCS
- [ ] **Phase 2**: Cross-site lot genealogy queries (recall lookups)
- [ ] **Phase 2**: Cross-site inventory transfer workflows
- [ ] **Phase 2**: SSO/SAML integration at MCS
- [ ] **Phase 2+**: Multi-region MCS replication (HA)
- [ ] **Phase 2+**: Cross-site supervisor handoff (roving staff)

#### Yard Management
- [ ] Truck staging + dock door optimization
- [ ] Wait time reduction analytics
- [ ] Dock utilization metrics
- [ ] Carrier performance tracking (punctuality, capacity)

---

## TECHNICAL IMPLEMENTATION NOTES

### Phase 1 Technology Stack
- **Database**: PostgreSQL (relational)
- **Backend**: Python/FastAPI or Node.js (event-driven)
- **Frontend**: React (dashboard) + HTML/CSS
- **Real-Time**: WebSockets (for 5-min metric refreshes)
- **Message Queue**: RabbitMQ or Kafka (async inventory updates)
- **Caching**: Redis (real-time counts)
- **Deployment**: Docker + Kubernetes (optional for Phase 1)

### Phase 2 Technology Additions
- **ML/AI**: Demand forecasting model (TensorFlow, PyTorch)
- **Mobile**: React Native (RF devices + mobile app)
- **APIs**: REST + GraphQL (customer/supplier portals)
- **Analytics**: Data warehouse (Snowflake/BigQuery for advanced reporting)

---

## SUCCESS METRICS

### Phase 1 (MVP Launch)
- [ ] All 7 core modules functional + tested
- [ ] 80%+ inventory accuracy (cycle count)
- [ ] <1% data entry errors (barcode scanning)
- [ ] Supervisor satisfaction (usability survey)
- [ ] Zero critical security vulnerabilities
- [ ] <4hr mean time to recover (backup restore test)

### Phase 2 (Enhancement Launch)
- [ ] Rework module fully integrated (cost tracking)
- [ ] Forecast accuracy >85% (demand prediction)
- [ ] Customer portal adoption >90% (users active)
- [ ] Labor efficiency +15% (task routing optimization)
- [ ] Multi-warehouse support fully operational

---

## TIMELINE ESTIMATE

**Phase 1**: 4-6 months (Oct 2026 - Mar 2027)
- Months 1-2: Core inventory + receiving + shipping
- Months 3-4: Production + QA + metrics
- Months 5-6: User management + system + testing + launch

**Phase 2**: 3-4 months (Apr 2027 - Jul 2027)
- Month 1: Rework + labor management
- Month 2: Forecasting + portals
- Month 3-4: Optimization + launch

---

## RISK MITIGATION

**Risk**: Multi-warehouse configuration complexity
**Mitigation**: Phase 1 supports single-warehouse; add multi-warehouse in Phase 1.5 once core is stable

**Risk**: Multi-site federation complexity (auth, data isolation, MCS coordination)
**Mitigation**: Phase 1 ships site selector pattern with single-entry directory (no MCS). Phase 1.5 introduces MCS as a separate deployment of the same codebase with `role: master` config — incremental rollout. Per-site session enforcement is hard-required from day one to prevent cross-site security drift later.

**Risk**: Lot genealogy real-time queries become slow with large datasets  
**Mitigation**: Index genealogy tables by lot ID; batch reporting for large date ranges

**Risk**: Operator training on FIFO/FEFO rules  
**Mitigation**: Implement visual UI cues (green = FIFO, yellow = FEFO); in-app help tooltips

**Risk**: Supplier defect tracking adoption  
**Mitigation**: Integrate with receiving QC; auto-calculate from quality data (no manual input needed)

---

## NEXT STEPS

1. **Finalize Phase 1 spec** (WMS_plan.txt + API schema)
2. **Set up development environment** (git repo, CI/CD)
3. **Create database schema** (entity-relationship diagrams)
4. **Define API endpoints** (REST spec)
5. **Begin Receiving module** (backend + frontend)
6. **Weekly sprints** (2-week sprints for Phase 1)

---

**Version**: 1.0  
**Last Updated**: 2026-05-15  
**Owner**: Meatbag / Development Team
