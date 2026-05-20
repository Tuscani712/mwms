/* ═══════════════════════════════════════════════════════════════════════════
   Inventory Page — live data wiring (SCO-49)
   Replaces the mock KPI tiles + tables with real /api/v1/inventory data.
   Falls back to existing markup if unauthed.
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) return;

  const searchInput = document.querySelector('.hero-search-input');
  const safetyPanel = document.querySelector('.page-row .panel');
  const kpiRow = document.querySelector('.kpi-row');
  const recentTbody = document.querySelector('.data-table tbody');

  function fmt(n) {
    return Number(n || 0).toLocaleString();
  }

  async function renderKPIs() {
    if (!kpiRow) return;
    try {
      const k = await WMS_API.inventory.kpis();
      const tiles = kpiRow.querySelectorAll('.kpi .kpi-value');
      if (tiles[0]) tiles[0].innerHTML = `${fmt(k.total_on_hand)}<span class="kpi-unit">UNITS</span>`;
      if (tiles[1]) tiles[1].innerHTML = `${fmt(k.available)}<span class="kpi-unit">UNITS</span>`;
      if (tiles[2]) {
        tiles[2].innerHTML =
          `${fmt(k.qa_hold_qty)}<span class="kpi-unit">UNITS</span>`;
        const meta = tiles[2].parentElement.querySelector('.kpi-meta');
        if (meta) meta.textContent = `${k.qa_hold_lots} lots · NOT shippable`;
      }
      if (tiles[3]) {
        tiles[3].innerHTML =
          `${fmt(k.skus_below_safety)}<span class="kpi-unit">SKUs</span>`;
        const meta = tiles[3].parentElement.querySelector('.kpi-meta');
        if (meta) meta.textContent = 'Below safety stock';
        const label = tiles[3].parentElement.querySelector('.kpi-label');
        if (label) label.innerHTML = '<span class="dot dot--warn"></span> Safety breach';
      }
    } catch (e) {
      console.warn('Inventory KPI fetch failed:', e.message);
    }
  }

  async function renderSafetyBreach() {
    if (!safetyPanel) return;
    try {
      const rows = await WMS_API.inventory.belowSafetyStock();
      // Remove existing alert rows in this panel
      safetyPanel.querySelectorAll('.alert').forEach((el) => el.remove());
      const foot = safetyPanel.querySelector('.panel-foot');
      if (!rows.length) {
        const empty = document.createElement('div');
        empty.className = 'alert';
        empty.innerHTML =
          '<span class="dot dot--ok"></span><div><div class="alert-title">All SKUs above safety stock</div><div class="alert-sub">No breaches at this site</div></div>';
        safetyPanel.insertBefore(empty, foot);
        return;
      }
      for (const row of rows) {
        const node = document.createElement('div');
        node.className = 'alert';
        node.innerHTML = `
          <span class="dot dot--warn"></span>
          <div>
            <div class="alert-title">${row.sku_code} · ${row.description}</div>
            <div class="alert-sub">${fmt(row.available)} on-hand · reorder point ${fmt(row.reorder_point)} · safety ${fmt(row.safety_stock)}</div>
          </div>
          <span class="alert-time">SS</span>
        `;
        safetyPanel.insertBefore(node, foot);
      }
    } catch (e) {
      console.warn('Safety-stock fetch failed:', e.message);
    }
  }

  async function runSearch(query) {
    if (!recentTbody) return;
    const params = { limit: 25 };
    if (query) params.q = query;
    try {
      const result = await WMS_API.inventory.lots(params);
      recentTbody.innerHTML = '';
      if (!result.items.length) {
        const tr = document.createElement('tr');
        tr.innerHTML =
          '<td class="col-status"></td><td colspan="5" style="color: var(--ink-tertiary);">No lots match.</td>';
        recentTbody.appendChild(tr);
        return;
      }
      for (const lot of result.items) {
        const tr = document.createElement('tr');
        const dotKind = lot.qa_hold
          ? 'dot--warn'
          : lot.expiring_soon
          ? 'dot--amber'
          : 'dot--ok';
        const note = lot.qa_hold
          ? 'QA HOLD'
          : lot.expiring_soon
          ? `Expires ${lot.expires_at}`
          : lot.sku_description;
        tr.innerHTML = `
          <td class="col-status"><span class="dot ${dotKind}"></span></td>
          <td class="mono">${lot.lot_code}</td>
          <td>${fmt(lot.quantity)} · ${lot.location_code || '—'}</td>
          <td>${note}</td>
          <td class="num">${lot.aging_bucket}</td>
          <td class="col-action"><a href="#" class="btn btn--sm btn-arrow"><span>Open</span></a></td>
        `;
        recentTbody.appendChild(tr);
      }
    } catch (e) {
      console.warn('Inventory search failed:', e.message);
    }
  }

  // Initial population
  renderKPIs();
  renderSafetyBreach();
  runSearch('');

  // Live search on input (debounced)
  if (searchInput) {
    let t;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(t);
      t = setTimeout(() => runSearch(e.target.value.trim()), 200);
    });
  }
})();
