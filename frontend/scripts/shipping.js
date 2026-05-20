/* ═══════════════════════════════════════════════════════════════════════════
   Shipping Page — live data wiring
   ─────────────────────────────────────────────────────────────────────────
   Currently wired:
     • GET /api/v1/shipping/orders → pick queue table

   To wire (endpoints listed are NOT YET BUILT unless marked existing):
     • GET /shipping/kpis                          → KPI tiles
     • GET /shipping/floor-summary                 → status ticker totals
     • GET /shipping/consolidation/{order}/{line}  (existing) → consolidation panel
     • POST /shipping/picks                        (existing) → Confirm pick button
     • POST /shipping/picks/next                   → Start next pick page-action
     • POST /shipping/truck-load                   (existing) → Build a load page-action
     • GET /shipping/truck/{shipment_id}           → Truck-load aside
     • GET /shipping/packing-slip/{order_id}       (existing) → packing slip PDF
     • GET /shipping/orders/search?q=              → Search input

   Auth: if not signed in, render "Sign in to load data" empty states.
   Never substitute mock data — the UI must reflect reality.
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  const tbody = document.querySelector('[data-bind="shipping-orders-rows"]');
  const statusEl = document.querySelector('[data-bind="shipping-data-status"]');
  if (!tbody) return;

  function fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString([], { month: 'short', day: '2-digit' });
  }

  function statusTag(status) {
    const map = {
      open: '<span class="tag">OPEN</span>',
      picking: '<span class="tag tag--warn">PICKING</span>',
      picked: '<span class="tag tag--ok">PICKED</span>',
      loaded: '<span class="tag tag--ok">LOADED</span>',
      shipped: '<span class="tag tag--ok">SHIPPED</span>',
    };
    return map[status] || `<span class="tag">${String(status || '').toUpperCase()}</span>`;
  }

  function priorityTag(p) {
    return p === 'rush'
      ? '<span class="tag tag--crit">RUSH</span>'
      : '<span class="tag">NORMAL</span>';
  }

  function setStatus(text, isLive = false) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.dataset.live = isLive ? 'true' : 'false';
  }

  function emptyRow(text) {
    return `<tr><td colspan="6" class="muted" style="text-align:center;padding:24px;color:var(--ink-tertiary);font-family:var(--font-mono);font-size:var(--text-xs)">${text}</td></tr>`;
  }

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    setStatus('Signed out · sign in to load data', false);
    tbody.innerHTML = emptyRow('Sign in to load order data');
    return;
  }

  try {
    setStatus('Loading orders…', false);
    const orders = await WMS_API.shipping.orders();
    if (!orders.length) {
      tbody.innerHTML = emptyRow('No open orders.');
      setStatus('Live · 0 orders', true);
      return;
    }
    tbody.innerHTML = orders
      .map((o) => {
        const lineCount = o.lines.length;
        const totalQty = o.lines.reduce((s, ln) => s + ln.qty_ordered, 0);
        return `
          <tr data-order-id="${o.id}">
            <td><span class="mono">${o.order_code}</span></td>
            <td>${o.customer}</td>
            <td>${priorityTag(o.priority)}</td>
            <td>${statusTag(o.status)}</td>
            <td><span class="mono">${lineCount} lines · ${totalQty} units</span></td>
            <td class="mono">${fmtDate(o.ship_by)}</td>
          </tr>
        `;
      })
      .join('');
    setStatus(`Live · ${orders.length} orders`, true);
  } catch (err) {
    console.warn('[WMS Shipping] orders fetch failed:', err.message);
    tbody.innerHTML = emptyRow('Backend unreachable.');
    setStatus('Backend unreachable', false);
  }
})();
