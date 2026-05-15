/* ═══════════════════════════════════════════════════════════════════════════
   Shipping Page — live data wiring
   Fetches orders from /api/v1/shipping/orders and replaces the mock table body.
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
    return map[status] || `<span class="tag">${status.toUpperCase()}</span>`;
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

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    setStatus('Demo data · sign in for live', false);
    return;
  }

  try {
    setStatus('Loading orders…', false);
    const orders = await WMS_API.shipping.orders();
    if (!orders.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;padding:24px">No open orders.</td></tr>';
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
    console.warn('[WMS Shipping] Falling back to mock data:', err.message);
    setStatus('Backend unreachable · showing demo data', false);
  }
})();
