/* ═══════════════════════════════════════════════════════════════════════════
   WMS Dashboard — Lightweight interactions
   ─────────────────────────────────────────────────────────────────────────
   Currently wired:
     • Branding + user identity from localStorage / /auth/me
     • Live clock + hero date
     • Chat dock toggle (UI only — chat backend not yet built)
     • ⌘K command palette stub (logs only)

   To wire (endpoints listed are NOT YET BUILT):
     • GET /api/v1/dashboard/ticker   → status-ticker items
     • GET /api/v1/dashboard/summary  → hero lede (alert counts + throughput)
     • GET /api/v1/dashboard/shift    → operational briefing panel
     • GET /api/v1/dashboard/kpis     → 4 KPI tiles (units, orders, yield, holds)
                                        — becomes /reports/dashboard once SCO-52 lands
     • GET /api/v1/dashboard/alerts   → alerts feed
     • GET /api/v1/health             → footer build + API latency
     • GET /api/v1/chat/{site}/messages (WS) → chat dock

   When wiring fetches: respect a 5-min cache TTL on KPI/summary endpoints,
   reuse the in-process cache pattern from wms/services/inventory.py, and
   bind into the existing data-bind="kpi-*" / data-bind="alerts-*" /
   data-bind="briefing-*" slugs in index.html.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── BRANDING + USER IDENTITY (runs here since dashboard doesn't load shell.js) ──
  const storedLogo = localStorage.getItem('wms.clientLogo');
  if (storedLogo) {
    document.querySelectorAll('[data-bind="brand-logo"]').forEach(img => {
      img.src = storedLogo;
      img.hidden = false;
    });
    document.querySelectorAll('[data-bind="brand-mark"]').forEach(el => {
      el.style.display = 'none';
    });
  }
  const activeSiteLabel =
    localStorage.getItem('wms.activeSiteLabel') ||
    localStorage.getItem('wms.siteName');
  if (activeSiteLabel) {
    document.querySelectorAll('[data-bind="site-name"]').forEach(el => {
      el.textContent = activeSiteLabel;
    });
  }

  try {
    const userRaw = localStorage.getItem('wms.user');
    if (userRaw) {
      const u = JSON.parse(userRaw);
      const displayName = u.full_name || u.employee_code || 'Operator';
      const firstName = (u.full_name || '').split(' ')[0] || displayName;
      document.querySelectorAll('[data-bind="user-name"]').forEach(el => {
        el.textContent = displayName;
      });
      document.querySelectorAll('[data-bind="user-initial"]').forEach(el => {
        el.textContent = displayName.trim().charAt(0).toUpperCase();
      });
      // Hero greeting picks up the first name with a trailing period for the
      // editorial cadence ("Welcome back, Sarah.")
      document.querySelectorAll('[data-bind="user-first-name"]').forEach(el => {
        el.textContent = `${firstName}.`;
      });
    }
  } catch (_) { /* ignore */ }

  // User chip → profile (logout lives there).
  const userChip = document.getElementById('user-chip');
  if (userChip) {
    userChip.addEventListener('click', () => {
      window.location.href = 'profile.html';
    });
    userChip.title = 'View profile';
  }

  // ── LIVE CLOCK ─────────────────────────────────────────────────────
  const timeEl = document.getElementById('clock-time');
  const dateEl = document.getElementById('clock-date');
  const heroDateEl = document.getElementById('hero-date');

  const pad = (n) => String(n).padStart(2, '0');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

  function tick() {
    const now = new Date();
    if (timeEl) {
      timeEl.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    }
    if (dateEl) {
      dateEl.textContent = `${months[now.getMonth()]} ${pad(now.getDate())} · ${now.getFullYear()}`;
    }
    if (heroDateEl) {
      heroDateEl.textContent = `${days[now.getDay()]}, ${months[now.getMonth()]} ${now.getDate()}`;
    }
  }
  tick();
  setInterval(tick, 1000);

  // ── KPI REFRESH INDICATOR
  //    Disabled until /dashboard/kpis is wired — showing a ticking "X s ago"
  //    counter while no fetch is happening would be a lying UI.
  //    When the fetch lands, reset `lastRefreshAt = Date.now()` on each
  //    successful response and re-enable the tick below.
  // const kpiRefreshEl = document.getElementById('kpi-refresh');
  // let lastRefreshAt = null;
  // setInterval(() => {
  //   if (!kpiRefreshEl || lastRefreshAt === null) return;
  //   const s = Math.floor((Date.now() - lastRefreshAt) / 1000);
  //   kpiRefreshEl.textContent = s < 60 ? `${s}s ago` : `${Math.floor(s/60)}m ${s%60}s ago`;
  // }, 1000);

  // ── CHAT DOCK TOGGLE ───────────────────────────────────────────────
  const dock = document.getElementById('chat-dock');
  const toggle = document.getElementById('chat-toggle');
  if (toggle && dock) {
    toggle.addEventListener('click', () => {
      dock.classList.toggle('chat-dock--collapsed');
      const arrow = toggle.querySelector('.mono');
      if (arrow) {
        arrow.textContent = dock.classList.contains('chat-dock--collapsed') ? '▴' : '▾';
      }
    });
  }

  // ── COMMAND PALETTE STUB (⌘K / Ctrl+K)
  //    WIRING: future feature. When implemented, open a full-page overlay
  //    that searches across SKUs (/inventory/lots?q=), lots, orders
  //    (/shipping/orders), ASNs (/receiving/inbound), and users. Until then,
  //    swallow the shortcut to prevent the browser default.
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
    }
  });

  // ── KPI NUMERIC ANIMATION (count-up helper)
  //    Kept as a utility for when /dashboard/kpis lands. Will be invoked
  //    by the fetch handler after each successful response, NOT on initial
  //    paint (placeholders are `—`, not numbers).
  //    Usage post-wiring:
  //      document.querySelectorAll('.kpi-value[data-numeric]').forEach(animateNumber);
  // eslint-disable-next-line no-unused-vars
  function animateNumber(el) {
    const raw = el.textContent.trim();
    const match = raw.match(/^([\d,]+\.?\d*)(.*)$/);
    if (!match) return;
    const target = parseFloat(match[1].replace(/,/g, ''));
    const suffix = el.querySelector('.kpi-unit')?.outerHTML || '';
    const isFloat = match[1].includes('.');
    const duration = 900;
    const start = performance.now();
    const easeOut = (t) => 1 - Math.pow(1 - t, 3);

    const step = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const v = target * easeOut(t);
      const text = isFloat ? v.toFixed(1) : Math.floor(v).toLocaleString();
      el.innerHTML = text + suffix;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // Intentionally NOT calling animateNumber on initial paint — values are
  // placeholders. Wire it up when /dashboard/kpis is implemented.

})();
