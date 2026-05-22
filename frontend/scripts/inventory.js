/* ═══════════════════════════════════════════════════════════════════════════
   Inventory Page — live data wiring (SCO-49)
   ─────────────────────────────────────────────────────────────────────────
   Wires:
     · GET /inventory/kpis             → 4 KPI tiles + status ticker counts
     · GET /inventory/skus?q=…         → SKU typeahead dropdown
                                          (sessionStorage-cached, 5-minute TTL)
     · GET /inventory/lots?q=…         → lot results table
     · GET /inventory/below-safety-stock → safety-breach panel

   The hero search drives BOTH the SKU typeahead and the lot table. Selecting
   a suggestion narrows the lot table to that SKU.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  if (!window.WMS_API) return;

  const SKU_CACHE_KEY = 'wms.inventory.skus.v1';
  const SKU_CACHE_TTL_MS = 5 * 60 * 1000;

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const bind = (name) => document.querySelector(`[data-bind="${name}"]`);

  const fmt = (n) => Number(n || 0).toLocaleString();

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // ── SKU cache (sessionStorage, 5-minute TTL, per-site) ─────────────────
  // We cache the full SKU list once per session and run the typeahead filter
  // client-side. /inventory/skus?q=… is still wired as a fallback for when
  // the cache is cold or invalidated.
  const skuCache = {
    read() {
      try {
        const raw = sessionStorage.getItem(SKU_CACHE_KEY);
        if (!raw) return null;
        const { ts, site, items } = JSON.parse(raw);
        if (!Array.isArray(items)) return null;
        if (Date.now() - ts > SKU_CACHE_TTL_MS) return null;
        return { site, items };
      } catch (_) {
        return null;
      }
    },
    write(items, site) {
      try {
        sessionStorage.setItem(
          SKU_CACHE_KEY,
          JSON.stringify({ ts: Date.now(), site, items }),
        );
      } catch (_) { /* quota or private mode — silently ignore */ }
    },
    invalidate() {
      try { sessionStorage.removeItem(SKU_CACHE_KEY); } catch (_) {}
    },
  };
  // Expose so creators.js can invalidate after a new SKU is created.
  window.WMS_SKU_CACHE = skuCache;

  async function loadSKUs(forceRefresh = false) {
    if (!forceRefresh) {
      const cached = skuCache.read();
      if (cached) return cached.items;
    }
    const items = await WMS_API.inventory.skus({});
    skuCache.write(items, null);
    return items;
  }

  // Light fuzzy match: case-insensitive substring on code OR description.
  // Ranks code-prefix matches above description-substring matches.
  function filterSKUs(items, query) {
    const q = query.trim().toLowerCase();
    if (!q) return items.slice(0, 12);
    const codePrefix = [];
    const codeContains = [];
    const descContains = [];
    for (const sku of items) {
      const code = sku.code.toLowerCase();
      const desc = (sku.description || '').toLowerCase();
      if (code.startsWith(q)) codePrefix.push(sku);
      else if (code.includes(q)) codeContains.push(sku);
      else if (desc.includes(q)) descContains.push(sku);
    }
    return [...codePrefix, ...codeContains, ...descContains].slice(0, 12);
  }

  // ── KPI tiles + ticker hydration ───────────────────────────────────────
  async function renderKPIs() {
    let kpis;
    try {
      kpis = await WMS_API.inventory.kpis();
    } catch (e) {
      console.warn('[Inventory] KPI fetch failed:', e.message);
      return;
    }
    const set = (name, value) => { const el = bind(name); if (el) el.textContent = value; };

    set('kpi-total-on-hand', `${fmt(kpis.total_on_hand)} `);
    set('kpi-total-on-hand-meta', `across ${fmt(kpis.sku_count)} SKUs`);
    set('kpi-available', `${fmt(kpis.available)} `);
    set('kpi-qa-hold', `${fmt(kpis.qa_hold_qty)} `);
    set('kpi-qa-hold-meta', `${fmt(kpis.qa_hold_lots)} lots · NOT shippable`);
    set('kpi-safety-breach', `${fmt(kpis.skus_below_safety)} `);

    // KPI values include a trailing <span class="kpi-unit"> — replace fully via innerHTML.
    const setHtml = (name, qty, unit) => {
      const el = bind(name);
      if (el) el.innerHTML = `${fmt(qty)}<span class="kpi-unit">${unit}</span>`;
    };
    setHtml('kpi-total-on-hand', kpis.total_on_hand, 'UNITS');
    setHtml('kpi-available', kpis.available, 'UNITS');
    setHtml('kpi-qa-hold', kpis.qa_hold_qty, 'UNITS');
    setHtml('kpi-safety-breach', kpis.skus_below_safety, 'SKUs');

    // Status ticker counts.
    set('ticker-total-skus', fmt(kpis.sku_count));
    set('ticker-qa-hold', `${fmt(kpis.qa_hold_lots)} LOTS`);
    set('ticker-safety-breach', fmt(kpis.skus_below_safety));
    set('ticker-sku-count', fmt(kpis.sku_count));
  }

  // ── Safety-stock breach panel ──────────────────────────────────────────
  async function renderSafetyBreach() {
    const panel = bind('safety-panel');
    if (!panel) return;
    let rows;
    try {
      rows = await WMS_API.inventory.belowSafetyStock();
    } catch (e) {
      console.warn('[Inventory] safety-stock fetch failed:', e.message);
      return;
    }
    const foot = panel.querySelector('.panel-foot');
    panel.querySelectorAll('.alert').forEach((el) => el.remove());

    if (!rows.length) {
      const node = document.createElement('div');
      node.className = 'alert';
      node.innerHTML = `
        <span class="dot dot--ok"></span>
        <div>
          <div class="alert-title">All SKUs above safety stock</div>
          <div class="alert-sub">No breaches at this site</div>
        </div>
      `;
      panel.insertBefore(node, foot);
      return;
    }
    for (const row of rows) {
      const node = document.createElement('div');
      node.className = 'alert';
      node.innerHTML = `
        <span class="dot dot--warn"></span>
        <div>
          <div class="alert-title">${escapeHtml(row.sku_code)} · ${escapeHtml(row.description)}</div>
          <div class="alert-sub">${fmt(row.available)} on-hand · reorder point ${fmt(row.reorder_point)} · safety ${fmt(row.safety_stock)}</div>
        </div>
        <span class="alert-source">SS</span>
      `;
      panel.insertBefore(node, foot);
    }
  }

  // ── Lot search results table ───────────────────────────────────────────
  let lotSeq = 0;
  async function runLotSearch({ q = '', skuCode = null } = {}) {
    const tbody = bind('lot-rows');
    const meta = bind('lots-meta');
    if (!tbody) return;
    const seq = ++lotSeq;
    if (meta) meta.textContent = 'Loading…';
    const params = { limit: 25 };
    if (q) params.q = q;
    if (skuCode) params.sku_code = skuCode;
    try {
      const result = await WMS_API.inventory.lots(params);
      if (seq !== lotSeq) return;
      if (!result.items.length) {
        tbody.innerHTML = `
          <tr><td colspan="6" class="empty-state">No lots match.</td></tr>
        `;
        if (meta) meta.textContent = '0 lots';
        return;
      }
      tbody.innerHTML = result.items.map((lot) => {
        const dotKind = lot.qa_hold ? 'dot--warn'
          : lot.expiring_soon ? 'dot--amber'
          : 'dot--ok';
        const note = lot.qa_hold ? 'QA HOLD'
          : lot.expiring_soon ? `Expires ${lot.expires_at}`
          : lot.sku_description;
        return `
          <tr>
            <td class="col-status"><span class="dot ${dotKind}"></span></td>
            <td class="mono">${escapeHtml(lot.lot_code)}</td>
            <td>${fmt(lot.quantity)} · ${escapeHtml(lot.location_code || '—')}</td>
            <td>${escapeHtml(note)}</td>
            <td class="num">${escapeHtml(lot.aging_bucket || '—')}</td>
            <td class="col-action"><span class="mono" style="color:var(--ink-tertiary)">${escapeHtml(lot.sku_code)}</span></td>
          </tr>
        `;
      }).join('');
      if (meta) {
        const filter = skuCode ? ` · filter: ${skuCode}` : (q ? ` · q: ${q}` : '');
        meta.textContent = `${result.items.length} of ${result.total} lots${filter}`;
      }
    } catch (e) {
      if (seq !== lotSeq) return;
      console.warn('[Inventory] lot search failed:', e.message);
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Search failed.</td></tr>`;
      if (meta) meta.textContent = '—';
    }
  }

  // ── SKU typeahead dropdown ─────────────────────────────────────────────
  const input = $('#inventory-search');
  const suggest = $('#sku-suggest');
  let allSKUs = [];
  let currentMatches = [];
  let highlightIndex = -1;

  function closeSuggest() {
    if (!suggest) return;
    suggest.removeAttribute('data-open');
    suggest.innerHTML = '';
    highlightIndex = -1;
  }

  function renderSuggest(matches) {
    if (!suggest) return;
    currentMatches = matches;
    highlightIndex = matches.length ? 0 : -1;
    if (!matches.length) {
      suggest.innerHTML = '<div class="sku-suggest-empty">No SKU matches.</div>';
    } else {
      suggest.innerHTML = matches.map((sku, i) => `
        <div class="sku-suggest-row" role="option" data-index="${i}" data-code="${escapeHtml(sku.code)}" aria-selected="${i === 0 ? 'true' : 'false'}">
          <span class="sku-code">${escapeHtml(sku.code)}</span>
          <span class="sku-desc">${escapeHtml(sku.description)}</span>
          <span class="sku-meta">${fmt(sku.on_hand_qty)} ${escapeHtml(sku.uom)}</span>
        </div>
      `).join('');
    }
    suggest.setAttribute('data-open', 'true');
  }

  function updateHighlight(delta) {
    if (!currentMatches.length) return;
    highlightIndex = (highlightIndex + delta + currentMatches.length) % currentMatches.length;
    suggest.querySelectorAll('.sku-suggest-row').forEach((row, i) => {
      row.setAttribute('aria-selected', i === highlightIndex ? 'true' : 'false');
      if (i === highlightIndex) row.scrollIntoView({ block: 'nearest' });
    });
  }

  function pickSuggestion(sku) {
    if (!sku) return;
    if (input) input.value = sku.code;
    closeSuggest();
    runLotSearch({ skuCode: sku.code });
  }

  if (input) {
    let t;
    input.addEventListener('input', (e) => {
      const value = e.target.value;
      clearTimeout(t);
      t = setTimeout(async () => {
        if (!allSKUs.length) {
          try { allSKUs = await loadSKUs(); }
          catch (err) { console.warn('[Inventory] SKU load failed:', err.message); }
        }
        if (value.trim()) {
          renderSuggest(filterSKUs(allSKUs, value));
        } else {
          closeSuggest();
        }
        runLotSearch({ q: value.trim() });
      }, 120);
    });

    input.addEventListener('keydown', (e) => {
      if (!suggest || suggest.getAttribute('data-open') !== 'true') {
        if (e.key === 'Escape') { input.value = ''; runLotSearch({}); }
        return;
      }
      if (e.key === 'ArrowDown') { e.preventDefault(); updateHighlight(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); updateHighlight(-1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        if (highlightIndex >= 0) pickSuggestion(currentMatches[highlightIndex]);
      } else if (e.key === 'Escape') {
        closeSuggest();
      }
    });

    input.addEventListener('blur', () => {
      // Delay so click handlers on suggestion rows fire first.
      setTimeout(closeSuggest, 120);
    });
  }

  if (suggest) {
    suggest.addEventListener('mousedown', (e) => {
      const row = e.target.closest('.sku-suggest-row');
      if (!row) return;
      const idx = Number(row.dataset.index);
      pickSuggestion(currentMatches[idx]);
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────────
  if (!WMS_API.isAuthed()) {
    // Signed-out: leave empty states in place. Ticker / KPI tiles already show em-dashes.
    const meta = bind('lots-meta');
    if (meta) meta.textContent = 'Sign in to load data';
    return;
  }

  (async () => {
    // Warm the SKU cache in the background — typeahead becomes instant after this.
    loadSKUs().then((items) => { allSKUs = items; }).catch(() => {});
    await Promise.all([renderKPIs(), renderSafetyBreach(), runLotSearch({})]);
  })();
})();
