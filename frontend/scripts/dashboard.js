/* ═══════════════════════════════════════════════════════════════════════════
   WMS Dashboard — Lightweight interactions
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── BRANDING LOAD (same as shell.js — runs here since dashboard doesn't load shell.js)
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
  const storedSite = localStorage.getItem('wms.siteName');
  if (storedSite) {
    document.querySelectorAll('[data-bind="site-name"]').forEach(el => {
      el.textContent = storedSite;
    });
  }

  // ── LIVE CLOCK ─────────────────────────────────────────────────────
  const timeEl = document.getElementById('clock-time');
  const dateEl = document.getElementById('clock-date');
  const heroDateEl = document.getElementById('hero-date');
  const kpiRefreshEl = document.getElementById('kpi-refresh');

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

  // ── KPI REFRESH INDICATOR (cosmetic, every 5 min for real metrics) ─
  let refreshSeconds = 0;
  setInterval(() => {
    refreshSeconds += 1;
    if (!kpiRefreshEl) return;
    if (refreshSeconds < 60) {
      kpiRefreshEl.textContent = `${refreshSeconds}s ago`;
    } else {
      kpiRefreshEl.textContent = `${Math.floor(refreshSeconds / 60)}m ${refreshSeconds % 60}s ago`;
    }
  }, 1000);

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

  // ── COMMAND PALETTE STUB (⌘K / Ctrl+K) ─────────────────────────────
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      console.log('[WMS] Command palette: not yet wired. Coming next sprint.');
      // Future: open command palette overlay.
    }
  });

  // ── KPI NUMERIC ANIMATION (count-up on first paint) ────────────────
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

  document.querySelectorAll('.kpi-value').forEach(animateNumber);

})();
