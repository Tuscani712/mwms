# WMS Permission System - Client Configurable Architecture

## Overview
The permission system is **fully client-configurable**, allowing organizations to define their own roles, titles, and permission templates without rigid role hierarchies.

---

## ARCHITECTURE LAYERS

### Layer 1: Titles (Custom Roles)
Client defines role names that match their organizational structure.

**Examples:**
- Picker / Warehouse Associate
- Receiving Clerk
- QA Inspector
- Supervisor / Lead
- Warehouse Manager
- Production Manager
- Inventory Controller
- Plant Manager / Director

**System Built-in Defaults (can be customized):**
- Level 1: Operator (receive, ship, produce, scan, lookup only)
- Level 2: Lead (assign tasks, approve overrides)
- Level 3: Supervisor (department management)
- Level 4: Manager (strategic configuration)
- Level 5: Admin (system control)

### Layer 2: Permission Templates
Reusable bundles of permissions assigned to titles.

**Examples:**
```
PICKING_TEMPLATE:
├─ can_view_pending_orders
├─ can_pick_inventory
├─ can_override_fifo (optional, requires approval)
├─ can_scan_items
└─ can_view_order_details

QA_INSPECTOR_TEMPLATE:
├─ can_hold_items
├─ can_inspect_items
├─ can_release_items
├─ can_destroy_items (requires Lvl 4 approval)
└─ can_view_qc_reports

WAREHOUSE_MANAGER_TEMPLATE:
├─ all_receiving_permissions
├─ all_shipping_permissions
├─ can_assign_tasks
├─ can_override_fifo
├─ can_override_ingredient_shortage
├─ can_manage_users
├─ can_configure_system
└─ can_view_audit_logs

ADMIN_TEMPLATE:
└─ * (all permissions)
```

### Layer 3: Granular Permissions
Individual function-level permissions that can be granted/revoked.

**Examples:**
```
RECEIVING MODULE:
├─ can_receive_inventory (scan + record)
├─ can_qc_items (check qty/condition)
├─ can_override_qc (accept damaged goods)
├─ can_approve_asn (approve ASN variance)
├─ can_assign_location (assign putaway location)
├─ can_override_fifo (manual location assignment)
└─ can_view_receiving_reports

SHIPPING MODULE:
├─ can_view_pending_orders
├─ can_pick_inventory
├─ can_override_fifo (pick out of sequence)
├─ can_override_fefo (ship near-expiration without approval)
├─ can_modify_orders (change order after pick)
├─ can_approve_order_change (approve modifications)
├─ can_pack_inventory
├─ can_stage_shipments
└─ can_view_shipping_reports

PRODUCTION MODULE:
├─ can_create_work_orders
├─ can_execute_production
├─ can_consume_ingredients
├─ can_override_ingredient_shortage
├─ can_use_expired_ingredients
├─ can_track_yield
├─ can_view_recipes
└─ can_view_production_reports

QA MODULE:
├─ can_hold_items
├─ can_inspect_items
├─ can_release_items
├─ can_destroy_items
├─ can_approve_destruction (>=500 cost)
├─ can_view_supplier_defects
└─ can_view_qa_reports

INVENTORY MODULE:
├─ can_lookup_inventory
├─ can_adjust_qty (requires reason code)
├─ can_approve_qty_adjustment
├─ can_transfer_inventory
├─ can_perform_cycle_count
├─ can_view_inventory_reports
├─ can_configure_safety_stock
└─ can_configure_reorder_points

METRICS MODULE:
├─ can_view_operational_metrics
├─ can_view_cost_data
├─ can_view_supplier_performance
├─ can_view_outlier_detection
├─ can_export_genealogy_report
├─ can_view_audit_logs
└─ can_generate_custom_reports

ADMIN MODULE:
├─ can_manage_users
├─ can_configure_titles
├─ can_configure_permission_templates
├─ can_configure_granular_permissions
├─ can_configure_system_settings
├─ can_view_permission_audit_trail
├─ can_export_permission_config
├─ can_import_permission_config
└─ can_change_any_user_permissions

CHAT MODULE:
├─ can_send_messages
├─ can_create_chat_groups
├─ can_escalate_messages
└─ can_view_chat_history
```

---

## PERMISSION ASSIGNMENT FLOW

### Option A: Use Template (Simple)
```
1. Create Title: "Warehouse Manager"
2. Assign Template: "Warehouse_Manager_Template"
3. Assign Users: John, Sarah, Mike
4. Done - all 3 users inherit template permissions
```

### Option B: Use Template + Overrides (Flexible)
```
1. Create Title: "Senior Picker"
2. Assign Template: "Picking_Template"
3. Assign User: John
4. Override Permissions:
   - Grant: can_override_fifo (senior picker can override)
   - Revoke: can_destroy_items (picker shouldn't destroy)
5. Done - John has template + custom overrides
```

### Option C: Custom Permissions (Advanced)
```
1. Create Title: "QA Lead"
2. DON'T assign template (or assign base template)
3. Assign Users: Jane
4. Grant individual permissions:
   - can_hold_items
   - can_inspect_items
   - can_release_items
   - can_destroy_items
   - can_approve_destruction
   - can_assign_tasks
   - can_view_qa_reports
5. Done - Jane has exactly what she needs
```

---

## CLIENT CONFIGURATION UI (Admin Panel)

### Tab 1: Manage Titles
```
┌────────────────────────────────────────┐
│ TITLES (Custom Roles)                  │
├────────────────────────────────────────┤
│ [+ Create New Title]                   │
│                                         │
│ Title Name          Template    Users  │
│ ────────────────────────────────────  │
│ Picker              Picking     45    │
│ [Edit] [Delete] [Archive]             │
│                                         │
│ Warehouse Manager   Manager    5     │
│ [Edit] [Delete] [Archive]             │
│                                         │
│ QA Inspector        QA         8     │
│ [Edit] [Delete] [Archive]             │
│                                         │
│ Production Lead     Production 3     │
│ [Edit] [Delete] [Archive]             │
│                                         │
│ Supervisor          Supervisor 12    │
│ [Edit] [Delete] [Archive]             │
│                                         │
│ Admin               Admin      2     │
│ [Edit] [Delete] [Archive]             │
└────────────────────────────────────────┘
```

### Tab 2: Manage Permission Templates
```
┌────────────────────────────────────────┐
│ PERMISSION TEMPLATES                   │
├────────────────────────────────────────┤
│ [+ Create New Template]                │
│                                         │
│ Template Name          Permissions  │
│ ────────────────────────────────────  │
│ Picking_Template       12 perms     │
│ [Edit] [View Perms] [Assign to Title]│
│                                         │
│ QA_Inspector_Template  8 perms      │
│ [Edit] [View Perms] [Assign to Title]│
│                                         │
│ Manager_Template       25 perms     │
│ [Edit] [View Perms] [Assign to Title]│
│                                         │
│ Admin_Template         All perms    │
│ [Edit] [View Perms] [Assign to Title]│
│                                         │
│ [Import Template] [Export All]         │
└────────────────────────────────────────┘

[Edit Template: Manager_Template]
┌────────────────────────────────────────┐
│ Manager_Template Permissions           │
├────────────────────────────────────────┤
│                                         │
│ RECEIVING:                             │
│ ☑ can_receive_inventory                │
│ ☑ can_qc_items                         │
│ ☑ can_override_qc                      │
│ ☑ can_approve_asn                      │
│ ☑ can_assign_location                  │
│ ☑ can_override_fifo                    │
│ ☐ can_view_receiving_reports           │
│                                         │
│ SHIPPING:                              │
│ ☑ can_view_pending_orders              │
│ ☑ can_pick_inventory                   │
│ ☑ can_override_fifo                    │
│ ☑ can_modify_orders                    │
│ ☑ can_approve_order_change             │
│ ☐ can_view_shipping_reports            │
│                                         │
│ ADMIN:                                 │
│ ☑ can_manage_users                     │
│ ☑ can_configure_system                 │
│ ☑ can_view_audit_logs                  │
│ ☐ can_change_any_user_permissions      │
│                                         │
│ [Save Changes] [Cancel]                │
│ Last Modified: 5/10/26 by Admin User   │
└────────────────────────────────────────┘
```

### Tab 3: Manage Users (Permissions)
```
┌────────────────────────────────────────┐
│ USER PERMISSION MANAGEMENT             │
├────────────────────────────────────────┤
│ [Search Users...]                      │
│ [Filter by Title] [Filter by Dept]     │
│ [Import Users] [Export Users]          │
│                                         │
│ User Name   Title           Overrides  │
│ ────────────────────────────────────  │
│ John Doe    Picker          +1, -0    │
│ [Edit Perms] [View Overrides]          │
│                                         │
│ Sarah Smith Warehouse Mgr   +0, -0    │
│ [Edit Perms] [View Overrides]          │
│                                         │
│ Jane Patel  QA Inspector    +2, -1    │
│ [Edit Perms] [View Overrides]          │
│                                         │
│ Mike Brown  Production Lead +3, -0    │
│ [Edit Perms] [View Overrides]          │
│                                         │
│ [View Permission Change History]       │
│ [Generate Compliance Report]           │
└────────────────────────────────────────┘

[Edit Permissions: John Doe (Picker)]
┌────────────────────────────────────────┐
│ John Doe - Permission Overrides        │
├────────────────────────────────────────┤
│ Base Template: Picking_Template        │
│                                         │
│ ADDITIONAL GRANTS (Override Template): │
│ + can_override_fifo (Senior picker)    │
│ + can_approve_qty_adjustment           │
│                                         │
│ REVOKES (Override Template):           │
│ - (none)                               │
│                                         │
│ [Add Permission] [Remove Permission]   │
│ [Reset to Template] [Save Changes]     │
│                                         │
│ Last Modified: 5/12/26 by Admin       │
│ Modified By: Admin User (reason: promotion) │
└────────────────────────────────────────┘
```

### Tab 4: Permission Audit Trail
```
┌────────────────────────────────────────┐
│ PERMISSION CHANGE HISTORY              │
├────────────────────────────────────────┤
│ [Filter by User] [Filter by Date]      │
│ [Export CSV]                           │
│                                         │
│ Date        User      Action           │
│ ─────────────────────────────────────  │
│ 5/12/26     Admin     John: +can_override_fifo   │
│ 5/12/26     Admin     Grant: Senior promotion    │
│                                         │
│ 5/10/26     Admin     Sarah: New user setup      │
│ 5/10/26     Admin     Assigned: Manager_Template│
│                                         │
│ 5/08/26     Admin     Jane: +can_destroy_items  │
│ 5/08/26     Admin     Reason: QA Lead promo     │
│                                         │
│ 5/05/26     Admin     Edit Template: Manager    │
│ 5/05/26     Admin     +can_override_ingredient_ │
│                       shortage (production need)│
│                                         │
│ [View Full Details] (for each entry)   │
└────────────────────────────────────────┘
```

---

## IMPLEMENTATION FLOW

### Phase 1: Core Configurable System
- [x] Define granular permissions (100+ function-level)
- [x] Create title management (create, edit, archive)
- [x] Create permission template system (create, edit, assign to titles)
- [x] Implement user → title assignment
- [x] Implement permission override system (grant/revoke per user)
- [x] Audit trail (who changed what, when)
- [x] Admin UI for all above
- [x] Export/import permission configurations (for multi-site)

### Phase 2: Advanced Features
- [ ] Role builder UI (drag-drop permissions to create templates)
- [ ] Permission conflict detection (warn if revoking critical perms)
- [ ] Compliance audit reports (who has what permissions)
- [ ] Temporary permission grants (time-limited access)
- [ ] Permission delegation (user A can grant permissions to user B for duration)
- [ ] SSO/LDAP integration (sync roles from external directory)

---

## CLIENT CUSTOMIZATION EXAMPLES

### Example 1: Small Operation (Single Shift)
```
Titles Created:
├─ Picker (5 users)
├─ Supervisor (2 users)
└─ Manager (1 user)

Permission Templates:
├─ Picking_Template (basic picking)
├─ Supervisor_Template (coordinate + approve)
└─ Manager_Template (all admin functions)

No user overrides needed.
```

### Example 2: Large Manufacturing Facility
```
Titles Created:
├─ Receiving Clerk
├─ Quality Analyst
├─ Production Operator
├─ Production Lead
├─ Warehouse Manager
├─ Shipping Coordinator
├─ Inventory Manager
├─ Plant Manager
└─ IT Administrator

Permission Templates:
├─ Receiving_Template
├─ QA_Template
├─ Production_Operator_Template
├─ Production_Lead_Template
├─ Warehouse_Manager_Template
├─ Shipping_Template
├─ Inventory_Template
├─ Manager_Template
└─ Admin_Template

User Overrides:
- Senior Receiving Clerk: Picking_Template + can_approve_asn
- Lead QA Inspector: QA_Template + can_destroy_items
- etc.
```

### Example 3: Multi-Warehouse Organization
```
Master Permission Set: Defined once at corporate level
Per-Warehouse Customization:
├─ Warehouse A (different product mix, staffing)
│  └─ Modify templates: Production_Lead role needs extra permissions
├─ Warehouse B (different shift model)
│  └─ Modify templates: Supervisor role scope is smaller
└─ Warehouse C (fully automated receiving)
   └─ Modify templates: Receiving role removed, Production role expanded

Export/Import:
- Export corporate template set
- Customize per warehouse
- Re-import for updates
```

---

## BEST PRACTICES

1. **Start Simple**: Use default 5-level structure + templates, then customize
2. **Document Titles**: Clearly define what each title does (job description)
3. **Review Regularly**: Audit permissions quarterly for compliance
4. **Minimal Overrides**: Use templates, override only when necessary
5. **Approvals for Sensitive**: Require approval for can_destroy, can_override_safety_rules
6. **Segregation of Duties**: Separate receiving approval from receiving execution (don't give both to same person)
7. **Audit Trail**: Monitor permission changes (who granted what, when, why)
8. **Training**: Document permission model so users understand what they can/can't do

---

## SECURITY CONSIDERATIONS

- ✅ Audit trail: Every permission change logged (user, reason, timestamp)
- ✅ Approval workflow: High-risk permissions require approval (can_destroy_items >$500, can_change_permissions)
- ✅ Delegation: Users can't delegate their own permissions (prevent privilege escalation)
- ✅ Sessions: All permission changes revoke existing sessions (force re-login)
- ✅ MFA: Optional multi-factor auth for high-risk operations (destroy items, change permissions)
- ✅ Read-Only Audit: Audit logs are immutable (can't be edited/deleted)

---

## MULTI-SITE PERMISSION MODEL

When multi-site federation is enabled (see MULTI_SITE_ARCHITECTURE.md), permissions are **scoped per-site**:

- A user's titles and permissions are **evaluated independently at each site** they belong to.
- The same user can be a **Manager** at WHS-001 and an **Operator** at WHS-002 — permissions don't merge or roam.
- Session tokens are **site-bound** — a session at WHS-001 cannot make authenticated calls to WHS-002.
- Permission templates can be **published from MCS** (master template library) and subscribed to per-site, allowing corporate standardization without removing local customization rights.
- Audit log is local to each site; MCS receives a one-way replicated copy for cross-site corporate audit.

### MCS-Level Permissions (corporate admin)
A small set of permissions only exist at the MCS layer:

```
MCS PERMISSIONS:
├─ can_manage_site_directory       (add/remove sites)                         ✅ SCO-84
├─ can_federate_users              (provision a user across sites)
├─ can_publish_master_templates    (push template updates)
├─ can_initiate_cross_site_recall  (broadcast recall to all sites)
├─ can_view_corporate_rollup       (aggregated KPIs across all sites)
└─ can_coordinate_site_transfers   (cross-site inventory transfers)
```

These are **only** held by corporate-level admins, never by site-local users.

### Implemented permission gates (current code)

| Action | Required gate | Where enforced | Ticket |
|---|---|---|---|
| List users (`GET /admin/users`) | Lvl 3+ (or any MCS user) | `users_admin.require_admin` | SCO-35 |
| Create / update / soft-delete user | Lvl 3+ strict outrank, MCS Lvl 4+ cross-site | `users_admin.assert_can_manage` | SCO-35 |
| **Hard-purge user** (`POST /admin/users/{id}/purge`) | **Lvl 5 only.** Not self. Not last active Lvl 5. No active subordinates. | `users_admin.purge_user` | **SCO-85** |
| Roles / Departments / Shifts CRUD | Lvl 3+ own-site, MCS Lvl 4+ globals/cross-site | `orgmeta` service | SCO-79 |
| List sites (`GET /sites`) | Open (unauthenticated) — used by login picker | — | base |
| **Create / delete site** | **Master-site Lvl 5.** One-master rule. FK-safe delete. | `sites._require_master_admin(min_level=5)` | **SCO-84** |
| **Update / toggle-online site** | **Master-site Lvl 4+.** Master site cannot go offline. 60s cooldown. | `sites._require_master_admin(min_level=4)` | **SCO-84** |
| Field-visibility policies | Lvl 3+ | `policy` router | base |
| Password policies | Lvl 3+ | `policy` router | base |
| MFA reset for another user | Lvl 4+ same-site | `policy.mfa_reset` | SCO-46 |

---

**Version**: 1.2
**Status**: Ready for Phase 1 Implementation. Sites CRUD (SCO-84) and User purge (SCO-85) gates added 2026-05-20.
**Owner**: Development Team
