/* ═══════════════════════════════════════════════════════════════════════════
   Reports Page — live data wiring (SCO-52 MVP)
   Wires GET /api/v1/reports/{dashboard,inventory-aging,production,shipping}.
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    window.location.href = 'login.html';
    return;
  }

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const bind = (name, value) => $$(`[data-bind="${name}"]`).forEach((el) => { el.textContent = value; });
  const fmt = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
  };

  async function refresh() {
    const [dash, aging, prod, ship] = await Promise.all([
      WMS_API.request('/reports/dashboard').catch(() => null),
      WMS_API.request('/reports/inventory-aging').catch(() => null),
      WMS_API.request('/reports/production').catch(() => null),
      WMS_API.request('/reports/shipping').catch(() => null),
    ]);

    if (dash) {
      bind('kpi-open-orders', dash.open_orders);
      bind('kpi-open-wos', dash.open_work_orders);
      bind('kpi-receipts-today', dash.receipts_today);
      bind('kpi-qa-held', dash.qa_held_lots);
    }

    const agingTbody = $('[data-bind="aging-tbody"]');
    if (agingTbody && aging && aging.buckets) {
      agingTbody.innerHTML = aging.buckets.map((b) => `
        <tr>
          <td>${b.label}</td>
          <td class="num">${b.lot_count}</td>
          <td class="num">${b.total_qty}</td>
        </tr>
      `).join('') || '<tr data-empty><td colspan="3" class="empty-state">No lots in inventory.</td></tr>';
    }

    const prodTbody = $('[data-bind="prod-tbody"]');
    if (prodTbody && prod && prod.by_recipe) {
      if (!prod.by_recipe.length) {
        prodTbody.innerHTML = '<tr data-empty><td colspan="5" class="empty-state">No completed work orders yet.</td></tr>';
      } else {
        prodTbody.innerHTML = prod.by_recipe.map((r) => `
          <tr>
            <td class="mono">Recipe #${r.recipe_id}</td>
            <td class="mono">${r.sku_code || '—'}</td>
            <td class="num">${r.wo_count}</td>
            <td class="num">${r.target_total}</td>
            <td class="mono">${fmt(r.completed_at_last)}</td>
          </tr>
        `).join('');
      }
    }

    if (ship) {
      bind('kpi-shipments', ship.total_shipments);
      bind('kpi-ship-open', ship.open_orders);
    }
  }

  document.addEventListener('click', (e) => {
    if (e.target.closest('#btn-refresh')) refresh();
  });

  bind('site-name', WMS_API.getUser()?.site_id || '—');
  await refresh();
})();
