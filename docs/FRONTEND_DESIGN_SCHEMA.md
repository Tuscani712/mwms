# WMS Frontend Design Schema
## Information Architecture + UI Structure

---

## NAVIGATION PRINCIPLE
**Max 3 clicks to any feature** from home page.  
**Chat always available** (sticky widget, accessible from any page).

---

## PAGE HIERARCHY & STRUCTURE

```
LOGIN
  └─ Enter credentials
  └─ 2FA (if enabled)
  
LANDING PAGE (Home)
  ├─ Announcements & Alerts
  ├─ Quick Stats Dashboard
  ├─ Quick Action Buttons
  └─ Navigation Menu (3 levels max)

─────────────────────────────────────────

LEVEL 1: MAIN NAVIGATION (Top Bar + Left Sidebar)
├─ 📊 Dashboard (Home)
├─ 📦 Receiving
├─ 🚚 Shipping
├─ 🏭 Production
├─ ✅ Quality (QA)
├─ 📈 Metrics & Reports
├─ ⚙️ Admin
└─ 👤 User Profile (Logout)

─────────────────────────────────────────

LEVEL 2: MODULE SUBMENU (When clicking module)
├─ Dashboard
│  ├─ Overview
│  ├─ Recent Activities
│  └─ Quick Links
│
├─ Receiving
│  ├─ Current Receipts (In Progress)
│  ├─ ASN Matching
│  ├─ QC & Inspection
│  ├─ Location Assignment
│  ├─ Receiving Reports
│  └─ Supplier Performance
│
├─ Shipping
│  ├─ Pending Orders
│  ├─ Picking Tasks
│  ├─ Pack & Stage
│  ├─ Shipping Reports
│  └─ Order Modification
│
├─ Production
│  ├─ Work Orders
│  ├─ Active Runs
│  ├─ Recipes/BOMs
│  ├─ Yield Tracking
│  ├─ Lot Genealogy (Query)
│  └─ Production Reports
│
├─ Quality (QA)
│  ├─ Item Holds
│  ├─ Hold Review
│  ├─ Release/Destroy
│  ├─ Supplier Defects
│  └─ QA Reports
│
├─ Metrics & Reports
│  ├─ Live Dashboard
│  ├─ Receiving KPIs
│  ├─ Shipping KPIs
│  ├─ Production KPIs
│  ├─ Supplier Performance
│  ├─ Lot Genealogy (Report)
│  ├─ Inventory Reports
│  └─ Custom Report Builder
│
├─ Admin (Lvl 4+)
│  ├─ User Management
│  ├─ Configuration
│  │  ├─ SKU Master Data
│  │  ├─ Locations & Zones
│  │  ├─ Recipes
│  │  ├─ Suppliers
│  │  └─ Threshold Settings
│  ├─ Audit Logs
│  └─ System Settings
│
└─ User Profile
   ├─ My Account
   ├─ Change Password
   ├─ Preferences
   └─ Logout

─────────────────────────────────────────

LEVEL 3: DETAIL PAGES (Sub-features)
Example Path: Reports → Shipping → View Report
  - Filter by date, location, user, etc.
  - Export to CSV/PDF
  - Back button or breadcrumb navigation
```

---

## CLICK DEPTH EXAMPLES (All ≤ 3 Clicks)

### Example 1: Access Shipping Report
- **Click 1**: Home → Metrics & Reports (left sidebar)
- **Click 2**: Shipping KPIs (submenu)
- **Click 3**: View Report (filter + export)
✅ **3 clicks total**

### Example 2: Start a Production Run
- **Click 1**: Home → Production (left sidebar)
- **Click 2**: Active Runs (submenu)
- **Click 3**: Start New Run (form)
✅ **3 clicks total**

### Example 3: Check QA Holds
- **Click 1**: Home → Quality (left sidebar)
- **Click 2**: Item Holds (submenu)
- **Click 3**: View Hold Details (action: Release/Destroy)
✅ **3 clicks total**

### Example 4: Review Supplier Performance
- **Click 1**: Home → Metrics & Reports (left sidebar)
- **Click 2**: Supplier Performance (submenu)
- **Click 3**: View Supplier Details (trend chart)
✅ **3 clicks total**

---

## LANDING PAGE (HOME) LAYOUT

```
┌─────────────────────────────────────────────────────┐
│  WMS Logo    🔔 Notifications    👤 John Doe ⬇️    │  ← Top Bar
├─────────────────────────────────────────────────────┤
│                                                       │
│  Welcome back, John! 👋                             │  ← Personalized greeting
│                                                       │
│  ┌─────────────────────────────────────────────┐    │
│  │ 📢 ANNOUNCEMENTS & ALERTS                   │    │
│  │ ────────────────────────────────────────── │    │
│  │ • Warehouse closure tomorrow (5/16) 3-5pm │    │
│  │ • 3 items in QA hold > 14 days (alert)    │    │
│  │ • Supplier X defect rate trending up      │    │
│  │ • Daily lot genealogy report ready (view) │    │
│  └─────────────────────────────────────────────┘    │
│                                                       │
│  ┌──────────────────────────────────────────────┐   │
│  │ 📊 QUICK STATS (Real-time Dashboard)        │   │
│  │ ───────────────────────────────────────────  │   │
│  │ Items Received Today: 2,450 lbs             │   │
│  │ Orders Shipped Today: 18 (95% on-time)      │   │
│  │ Items in Production: 4 active runs          │   │
│  │ Items on QA Hold: 3 (oldest: 8 days)        │   │
│  │ Inventory Accuracy: 99.2%                   │   │
│  │ Average Pick Time: 12 min/order             │   │
│  └──────────────────────────────────────────────┘   │
│                                                       │
│  ┌────────────────────────┬──────────────────────┐   │
│  │ ⚡ QUICK ACTIONS       │ 📋 MY TASKS          │   │
│  │ ─────────────────────  │ ──────────────────   │   │
│  │ [Receive Inventory]    │ • Approve ASN (2)    │   │
│  │ [Start Production]     │ • QA Hold Review (3) │   │
│  │ [Pick Order]           │ • Inventory Adjust   │   │
│  │ [Review QA Hold]       │   (1)                │   │
│  │ [View Reports]         │ • Shift Closeout     │   │
│  │                        │   (9 items)          │   │
│  └────────────────────────┴──────────────────────┘   │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ 🔍 SEARCH / LOOKUP                             │  │
│ │ Search SKU, Lot#, Location: _______________    │  │
│ │ [Search] [QR Code Scan]                       │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
└─────────────────────────────────────────────────────┘

PERSISTENT ELEMENTS (Every Page):
├─ Left Sidebar (collapsible): Navigation menu
├─ Top Bar: Logo, notifications, user dropdown
├─ Bottom Right: 💬 Chat Widget (sticky, expandable)
└─ Breadcrumb: Current page path (for navigation)
```

---

## LOGIN FLOW

The login page is split into two halves: a brand panel (left) with client logo, facility name, and a live system status strip; and a credential form (right). Operators authenticate against the **selected site's** user directory.

```
┌────────────────────────────────┬──────────────────────────────┐
│ Wms/  Warehouse Ops · Est 2026 │                              │
│                                │   ── Sign In · Console 01    │
│                                │                              │
│         ┌──────────┐           │   Welcome back.              │
│         │   LOGO   │           │                              │
│         │ (client) │           │   ● Signing in to · WHS-001  │
│         └──────────┘           │                              │
│         Your Facility          │   Operator ID or Email       │
│                                │   [op-1004 | name@whs.io]    │
│                                │                              │
│                                │   PIN or Password            │
│                                │   [••••••••]                 │
│                                │                              │
│ ── STATUS STRIP ──────────────│   ☐ Keep me signed in        │
│ Site · [WHS-001 · DAL ▾]      │                              │
│ Build · v0.1.0                 │   [ SIGN IN & CLOCK ON → ]   │
│ Status · Online                │                              │
│ Uptime · 42d · 18h 23m 47s    │   ─── or ───                 │
│ ● Ping · 64 ms                 │   [ SIGN IN WITH SSO ]       │
└────────────────────────────────┴──────────────────────────────┘
```

### Site Selector (click "Site · WHS-001 · DAL ▾")

Opens a popover dropdown showing all sites in the directory with **live ping per site**.

```
┌────────────────────────────────────────────────┐
│ SELECT SITE                          5 sites   │
├────────────────────────────────────────────────┤
│ ● MCS · CORP                  [MASTER]  12ms  │
│   Master Control · Corporate                   │
│   v0.1.0 · uptime 64d 4h                       │
├────────────────────────────────────────────────┤
│ ● WHS-001 · DAL              ← active   64ms  │  ← amber bar
│   Dallas Distribution                          │
│   v0.1.0 · uptime 42d 18h                      │
├────────────────────────────────────────────────┤
│ ● WHS-002 · HOU                         89ms  │
│   Houston Plant                                │
│   v0.1.0 · uptime 12d 7h                       │
├────────────────────────────────────────────────┤
│ ● WHS-003 · LAX                        187ms  │  ← red pill (>150ms)
│   Los Angeles Cold Storage                     │
│   v0.0.9 · uptime 3h                           │
├────────────────────────────────────────────────┤
│ ◐ WHS-004 · NYC                      OFFLINE  │
│   New York Reverse Logistics                   │
│   v0.0.8 · OFFLINE                             │
├────────────────────────────────────────────────┤
│ Each site has its own users & data    ✱ Master │
└────────────────────────────────────────────────┘
```

### Site Selector Behavior

- **Click site row**: All status strip values (Build, Status, Uptime, Ping) repoint to that site; form posts to that site's auth endpoint on submit.
- **Master Site (MCS)**: Marked with an amber `[MASTER]` badge; selecting it routes to corporate-admin login.
- **Offline site**: Greyed out, pill reads `OFFLINE`, ping check shows red crit color. Clicking still selects but login button shows clear error: "Site is currently unreachable."
- **Persistence**: Selected site stored in `localStorage.wms.activeSiteId` so operators land on their usual site on next visit.

### Status Strip — Single Horizontal Row

Replaces the old 2x2 data grid. All values are mono font, hairline-divided, live-updated:

```
Site · [WHS-001 · DAL ▾] | Build · v0.1.0 | Status · Online | Uptime · 42d · 18h 23m 47s | ● Ping · 64 ms
```

### Ping Pill — Color Thresholds

| Latency | Tier | Color | Visual |
|---------|------|-------|--------|
| ≤ 74 ms | OK | Green `#4ADE80` | green halo glow |
| 75-149 ms | Warn | Yellow `#FBBF24` | yellow halo glow |
| ≥ 150 ms | Critical | Red `#EF4444` | red halo + blink animation |
| Network fail | Dead | Gray | reads "OFFLINE" |

### Client Logo Replaces Brand Mark

When the client uploads a logo via Admin → Branding, it replaces the default "Wms/" mark in the top-left of every page:

- **Top-left of every module page topbar**: Logo image (32px tall, max 160px wide, with subtle amber drop-shadow)
- **Top-left of login marquee-header**: Logo image (36px tall, max 180px wide)
- **Center stage of login page**: Same logo, larger (240px square)

The "Warehouse Ops · Est. 2026" tagline remains as a secondary identifier next to the logo. If no logo is uploaded, the default "Wms/" wordmark is shown.

This makes the WMS feel like the *client's* tool, not a generic vendor product — full personalization with a single asset.

### Welcome Flow (post-login)

```
┌────────────────────────────────┐
│ Welcome back, John! 🎉         │
│                                │
│ Site: WHS-001 · DAL            │
│ Last login: 5/15 2:30pm        │
│ Your title: Supervisor         │
│ Your shift: 6am-2pm            │
│                                │
│ [Go to Dashboard]              │
└────────────────────────────────┘
```

---

## LOGOUT FLOW

```
Top Bar: 👤 John Doe ⬇️
    ↓ (Click)
    
Dropdown Menu:
├─ My Account
├─ Change Password
├─ Preferences
├─ ─────────────
└─ Logout

    ↓ (Click Logout)
    
Confirmation:
┌────────────────────────────┐
│ Logout Confirmation?       │
│                            │
│ You have unsaved changes   │
│ in Pick Task #456.         │
│                            │
│ [Continue Anyway] [Cancel] │
└────────────────────────────┘

    ↓ (Confirm)
    
Session ended
Return to Login Page
```

---

## PERSISTENT CHAT WIDGET

```
CLOSED STATE (Bottom Right Corner):
┌─────────────┐
│ 💬          │  ← Click to open
│ MESSAGES 3  │
│ (red badge) │
└─────────────┘

OPEN STATE:
┌────────────────────────┐
│ Team Chat      [−] [×] │  ← Minimize / Close
├────────────────────────┤
│ General  Shipping Shift │  ← Tab navigation
├────────────────────────┤
│ John: Hey, received new│
│ supplier lot B?        │
│                        │
│ Sarah: Yes, in QC hold │
│ pending inspection     │
│                        │
│ [_______________] [→] │  ← Message input
└────────────────────────┘

Features:
- Tab-based groups (Department, Shift, Location, Team)
- Unread message badge (shows count)
- Message notifications (popup toast)
- Pin important messages
- Search chat history
- Available from ANY page
```

---

## RESPONSIVE DESIGN BREAKPOINTS

```
DESKTOP (≥1200px)
├─ Left Sidebar: Always visible (collapsible)
├─ Top Navigation: Full menu
├─ Main Content: Full width
└─ Chat Widget: Fixed bottom-right

TABLET (768px - 1199px)
├─ Left Sidebar: Collapsible (hamburger menu)
├─ Top Navigation: Abbreviated
├─ Main Content: Full width
└─ Chat Widget: Fixed bottom-right (smaller)

MOBILE (< 768px)
├─ Left Sidebar: Drawer menu (hamburger)
├─ Top Navigation: Minimal (logo + user)
├─ Main Content: Full width, stacked
└─ Chat Widget: Bottom sheet (swipe up)
```

---

## NAVIGATION COMPONENT DETAILS

### Left Sidebar (Main Navigation)

```
┌─────────────────────┐
│ 🏭 WMS SYSTEM       │  ← Logo/Brand
├─────────────────────┤
│ 🏠 Home             │  ← Always visible
├─────────────────────┤
│ 📦 Receiving        │
│   ├─ In Progress    │
│   ├─ ASN Matching   │
│   ├─ QC & Inspect   │
│   ├─ Locations      │
│   └─ Reports        │
│                     │
│ 🚚 Shipping         │
│   ├─ Pending Orders │
│   ├─ Picking Tasks  │
│   ├─ Pack & Stage   │
│   └─ Reports        │
│                     │
│ 🏭 Production       │
│   ├─ Work Orders    │
│   ├─ Active Runs    │
│   ├─ Recipes        │
│   ├─ Genealogy      │
│   └─ Reports        │
│                     │
│ ✅ Quality          │
│   ├─ Item Holds     │
│   ├─ Review Holds   │
│   ├─ Release/Dest.  │
│   └─ Reports        │
│                     │
│ 📈 Metrics & Rpts   │
│   ├─ Dashboard      │
│   ├─ Receiving KPI  │
│   ├─ Shipping KPI   │
│   ├─ Production KPI │
│   ├─ Supplier Perf  │
│   ├─ Genealogy Rep  │
│   ├─ Inventory Rep  │
│   └─ Custom Report  │
│                     │
│ ⚙️ Admin (Lvl 4+)   │
│   ├─ User Mgmt      │
│   ├─ Config         │
│   ├─ Audit Logs     │
│   └─ Settings       │
│                     │
├─────────────────────┤
│ 👤 John Doe        │  ← User Profile (Hover shows dropdown)
│ Shift: 6am-2pm     │
│ Lvl 3 / Shipping   │
└─────────────────────┘
```

### Breadcrumb Navigation

```
Home > Shipping > Picking Tasks > Task #456 > Pick Details

Allows quick navigation back to parent pages.
Current page always highlighted.
```

---

## DASHBOARD (HOME PAGE) - DETAILED LAYOUT

### Top Section: Announcements (Dynamic Feed)

```
┌───────────────────────────────────────────┐
│ 📢 ANNOUNCEMENTS & ALERTS                 │  ← Auto-refresh
├───────────────────────────────────────────┤
│ [🔴 URGENT] 3 items on QA hold > 14 days │
│   └─ Requires management action            │
│                                            │
│ [🟡 WARNING] Supplier X defect rate: 8%  │
│   └─ Trending up, review recommended      │
│                                            │
│ [🟢 INFO] Daily lot genealogy report      │
│   └─ Ready for review [View Report]       │
│                                            │
│ [🔵 INFO] Warehouse maintenance tonight   │
│   └─ 10pm-midnight, limited dock access   │
└───────────────────────────────────────────┘
```

### Middle Section: Quick Stats (Real-Time)

```
Last Refreshed: 2 minutes ago   [🔄 Refresh Now]

┌─────────────────┬──────────────────┬──────────────────┐
│ Received Today  │ Shipped Today    │ In Production    │
│ 2,450 lbs      │ 18 orders        │ 4 active runs    │
│ (↑ 12% vs avg) │ (95% on-time)     │ (Avg 2.5 hrs)    │
└─────────────────┴──────────────────┴──────────────────┘

┌─────────────────┬──────────────────┬──────────────────┐
│ QA Hold Count   │ Inventory Acc.   │ Pick Time Avg    │
│ 3 items        │ 99.2%            │ 12 min/order     │
│ (oldest: 8 days)│ (↑ 0.5% this mo)│ (↓ 1 min vs mo) │
└─────────────────┴──────────────────┴──────────────────┘
```

### Bottom Section: Quick Actions + Tasks

```
┌────────────────────────┬──────────────────────┐
│ ⚡ QUICK ACTIONS       │ 📋 ASSIGNED TASKS    │
├────────────────────────┼──────────────────────┤
│ [Receive Inventory]    │ [2] Approve ASN      │
│ [Start Production]     │ [3] QA Hold Review   │
│ [Pick Order]           │ [1] Inventory Adjust │
│ [Review QA Hold]       │ [9] Shift Closeout   │
│ [View Reports]         │                      │
│ [Search Inventory]     │ [View All Tasks]     │
└────────────────────────┴──────────────────────┘
```

---

## COLOR & UX SCHEME

```
Primary Colors:
├─ Brand Blue: #0066CC (buttons, links, active states)
├─ Alert Red: #CC0000 (urgent, errors, deletions)
├─ Warning Yellow: #FFB700 (cautions, age alerts)
├─ Success Green: #00B050 (approved, completed)
└─ Neutral Gray: #666666 (disabled, secondary text)

Status Indicators:
├─ 🔴 Critical/Urgent (>14 day hold, variance >5%)
├─ 🟡 Warning (low stock, defect rate up)
├─ 🟢 Healthy (on-track, normal operations)
└─ 🔵 Info (announcements, reminders)

Typography:
├─ H1: 28px, Bold (page titles)
├─ H2: 24px, Bold (section headers)
├─ H3: 18px, Bold (subsection headers)
├─ Body: 14px, Regular (content)
└─ Labels: 12px, Bold (form labels)
```

---

## MODULE DETAIL PAGES

### Example: Receiving Module

```
Breadcrumb: Home > Receiving > In Progress

┌─────────────────────────────────────────────────┐
│ RECEIVING - IN PROGRESS                         │
├─────────────────────────────────────────────────┤
│ [Filters: Supplier, Date Range, Status]         │
│ [Export to CSV]  [Print]  [Refresh]             │
├─────────────────────────────────────────────────┤
│ REC-051526-001 | Supplier A | 1,500 lbs        │
│ Status: QC In Progress | Door 1 | John (Lvl 1) │
│ [View Details] [Approve ASN] [Edit] [Complete] │
│                                                  │
│ REC-051526-002 | Supplier B | 500 lbs          │
│ Status: Damage Noted | Door 2 | Alert: Damage  │
│ [View Details] [Approve] [Reject] [Hold for QA]│
│                                                  │
│ REC-051426-045 | Supplier C | 200 lbs          │
│ Status: Location Assignment | John              │
│ [View Details] [Auto-Assign Loc] [Manual Assign]│
│                                                  │
└─────────────────────────────────────────────────┘
```

### Example: Shipping Module

```
Breadcrumb: Home > Shipping > Picking Tasks

┌─────────────────────────────────────────────────┐
│ PICKING TASKS                                   │
├─────────────────────────────────────────────────┤
│ [Filters: Priority, Status, Assigned User]      │
│ [Export] [Print] [Refresh]                      │
├─────────────────────────────────────────────────┤
│ PICK-051526-001 | Order #5012 | 150 units      │
│ Priority: Rush | Assigned: John | Start Now    │
│ [Pick Now] [Reassign] [View Details]           │
│                                                  │
│ PICK-051526-002 | Order #5013 | 75 units       │
│ Priority: Normal | Assigned: Sarah | In Progress│
│ Pick Progress: 45/75 units ████░░░░ 60%        │
│ [Continue Pick] [Pause] [View Details]         │
│                                                  │
│ PICK-051526-003 | Order #5014 | 200 units      │
│ Priority: Normal | Assigned: Mike | Pending    │
│ [Pick Now] [Reassign] [View Details]           │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## ACCESSIBILITY REQUIREMENTS

- ✅ WCAG 2.1 AA compliance (color contrast, keyboard navigation)
- ✅ Responsive design (mobile, tablet, desktop)
- ✅ Screen reader support (semantic HTML)
- ✅ Form labels + error messages
- ✅ Keyboard shortcuts for power users (Shift+K for chat, Shift+S for search)
- ✅ Dark mode support (optional Phase 2)

---

## FUTURE ENHANCEMENTS (Phase 2)

- [ ] Mobile app (iOS/Android)
- [ ] Dark mode toggle
- [ ] Customizable dashboard widgets
- [ ] Advanced search + filters
- [ ] Real-time notifications (WebSocket alerts)
- [ ] AR scanning (mobile app)
- [ ] Voice commands (future)
- [ ] Keyboard shortcuts panel (? key)

---

**Version**: 1.0  
**Last Updated**: 2026-05-15  
**Status**: Ready for UI/UX Design Team
