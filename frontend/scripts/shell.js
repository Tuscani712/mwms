/* ═══════════════════════════════════════════════════════════════════════════
   WMS Shell — Cross-page behaviors (clock, chat dock, branding load)
   Loaded on every module page.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── LIVE CLOCK ─────────────────────────────────────────────────────
  const timeEl = document.getElementById('clock-time');
  const dateEl = document.getElementById('clock-date');

  const pad = (n) => String(n).padStart(2, '0');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  function tickClock() {
    const now = new Date();
    if (timeEl) timeEl.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    if (dateEl) dateEl.textContent = `${months[now.getMonth()]} ${pad(now.getDate())} · ${now.getFullYear()}`;
  }
  tickClock();
  setInterval(tickClock, 1000);

  // ── CHAT DOCK TOGGLE ───────────────────────────────────────────────
  const dock = document.getElementById('chat-dock');
  const toggle = document.getElementById('chat-toggle');
  if (toggle && dock) {
    toggle.addEventListener('click', () => {
      dock.classList.toggle('chat-dock--collapsed');
      const arrow = toggle.querySelector('.chat-caret');
      if (arrow) arrow.textContent = dock.classList.contains('chat-dock--collapsed') ? '▴' : '▾';
    });
  }

  // ── COMMAND PALETTE STUB (⌘K / Ctrl+K) ─────────────────────────────
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      console.log('[WMS] Command palette: not yet wired.');
    }
  });

  // ── BRANDING LOAD ───────────────────────────────────────────────────
  // Client logo replaces the "Wms/" brand mark in the topbar.
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

  const storedName = localStorage.getItem('wms.clientName');
  if (storedName) {
    document.querySelectorAll('[data-bind="client-name"]').forEach(el => {
      el.textContent = storedName;
    });
  }

  // Prefer the actively logged-in site label (set at login); fall back to
  // admin-branded site name; final default for unauthenticated demo.
  const activeSiteLabel =
    localStorage.getItem('wms.activeSiteLabel') ||
    localStorage.getItem('wms.siteName') ||
    'WHS-001 · DAL';
  document.querySelectorAll('[data-bind="site-name"]').forEach(el => {
    el.textContent = activeSiteLabel;
  });

  // ── ACTIVE USER BIND ────────────────────────────────────────────────
  try {
    const userRaw = localStorage.getItem('wms.user');
    if (userRaw) {
      const u = JSON.parse(userRaw);
      const displayName = u.full_name || u.employee_code || 'Operator';
      document.querySelectorAll('[data-bind="user-name"]').forEach(el => {
        el.textContent = displayName;
      });
      document.querySelectorAll('[data-bind="user-initial"]').forEach(el => {
        el.textContent = displayName.trim().charAt(0).toUpperCase();
      });
    }
  } catch (_) { /* ignore */ }

  // ── SIGN-OUT (click user chip) ──────────────────────────────────────
  const userChip = document.getElementById('user-chip');
  if (userChip) {
    userChip.addEventListener('click', () => {
      if (confirm('Sign out and clock off?')) {
        localStorage.removeItem('wms.token');
        localStorage.removeItem('wms.user');
        localStorage.removeItem('wms.activeSiteLabel');
        window.location.href = 'login.html';
      }
    });
  }

})();
