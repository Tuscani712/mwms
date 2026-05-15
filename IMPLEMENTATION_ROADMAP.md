# WMS Implementation Roadmap: Phase 1 (MVP) vs Phase 2 (Enhancement)

## Overview
**Phase 1**: Core functional MVP with operational foundation (est. 4-6 months)  
**Phase 2**: Polish, advanced features, external portals (est. 3-4 months)

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
