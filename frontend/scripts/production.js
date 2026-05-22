/* ═══════════════════════════════════════════════════════════════════════════
   Production Page — live data wiring (SCO-51 MVP)
   Wires /api/v1/production/{recipes,work-orders,...}. All mock data lives in
   the backend — this script only renders.
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    window.location.href = 'login.html';
    return;
  }

  // ── Tiny helpers ────────────────────────────────────────────────────
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const bind = (name, value) => $$(`[data-bind="${name}"]`).forEach((el) => { el.textContent = value; });
  const fmtDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
  };
  const tag = (kind, text) => `<span class="tag tag--${kind}">${text}</span>`;

  // ── API wrappers (would normally live on WMS_API, but we keep them
  //    local here so api.js stays generic for now) ─────────────────────
  const API_BASE = WMS_API.BASE;
  async function api(path, opts = {}) {
    return WMS_API.request(path, opts);
  }
  const prodApi = {
    listRecipes: () => api('/production/recipes'),
    createRecipe: (body) => api('/production/recipes', { method: 'POST', body }),
    listWOs: () => api('/production/work-orders'),
    createWO: (body) => api('/production/work-orders', { method: 'POST', body }),
    preflight: (id) => api(`/production/work-orders/${id}/preflight`, { method: 'POST' }),
    start: (id) => api(`/production/work-orders/${id}/start`, { method: 'POST' }),
    complete: (id, body) => api(`/production/work-orders/${id}/complete`, { method: 'POST', body }),
    cancel: (id) => api(`/production/work-orders/${id}/cancel`, { method: 'POST', body: {} }),
    getRecipe: (id) => api(`/production/recipes/${id}`),
    getWO: (id) => api(`/production/work-orders/${id}`),
  };
  const skuApi = {
    list: () => api('/inventory/skus').catch(() => []),
  };

  // ── State ───────────────────────────────────────────────────────────
  let recipes = [];
  let workOrders = [];
  let skus = [];
  let activeFilter = 'all';

  // ── Render ──────────────────────────────────────────────────────────
  function renderKPIs() {
    bind('kpi-recipes', recipes.length);
    bind('kpi-recipes-sub', recipes.length ? `${recipes.length} active` : 'no recipes yet');
    bind('kpi-wos', workOrders.length);
    bind('kpi-wos-sub', workOrders.length ? `${workOrders.length} total` : 'no work orders yet');
    bind('kpi-running', workOrders.filter((w) => w.status === 'running').length);
    const today = new Date().toISOString().slice(0, 10);
    bind(
      'kpi-completed',
      workOrders.filter((w) => w.status === 'completed' && (w.completed_at || '').startsWith(today)).length,
    );
  }

  function statusTag(s) {
    switch (s) {
      case 'draft': return tag('info', 'Draft');
      case 'reserved': return tag('amber', 'Reserved');
      case 'running': return tag('warn', 'Running');
      case 'completed': return tag('ok', 'Completed');
      case 'cancelled': return tag('info', 'Cancelled');
      default: return tag('info', s);
    }
  }

  function renderRecipes() {
    const tbody = $('[data-bind="recipe-tbody"]');
    if (!tbody) return;
    if (!recipes.length) {
      tbody.innerHTML = '<tr data-empty><td colspan="6" class="empty-state">No recipes yet — create one to define a BOM.</td></tr>';
      return;
    }
    tbody.innerHTML = recipes.map((r) => `
      <tr>
        <td><div class="row-title">Recipe #${r.id}</div><div class="row-sub mono">${r.sku_code || ''}</div></td>
        <td class="mono">${r.sku_code || r.sku_id}</td>
        <td class="num">${(r.lines || []).length}</td>
        <td class="num">v${r.version}</td>
        <td class="mono">${fmtDate(r.created_at)}</td>
        <td class="col-action"><button class="btn btn--sm btn-arrow" data-recipe="${r.id}"><span>Open</span></button></td>
      </tr>
    `).join('');
  }

  function renderWOs() {
    const tbody = $('[data-bind="wo-tbody"]');
    if (!tbody) return;
    const filtered = workOrders.filter((w) => activeFilter === 'all' || w.status === activeFilter);
    if (!filtered.length) {
      tbody.innerHTML = '<tr data-empty><td colspan="7" class="empty-state">No work orders match this filter.</td></tr>';
      return;
    }
    tbody.innerHTML = filtered.map((w) => {
      const dot = w.status === 'completed' ? 'ok' : w.status === 'running' ? 'warn' : w.status === 'reserved' ? 'amber' : 'info';
      const recipe = recipes.find((r) => r.id === w.recipe_id);
      const recipeLabel = recipe ? `${recipe.sku_code || ''} · v${w.recipe_version_snapshot}` : `Recipe #${w.recipe_id}`;
      const actions = [];
      if (w.status === 'draft') actions.push(`<button class="btn btn--sm" data-act="preflight" data-wo="${w.id}">Preflight</button>`);
      if (w.status === 'reserved') actions.push(`<button class="btn btn--sm btn--primary" data-act="start" data-wo="${w.id}">Start</button>`);
      if (w.status === 'running') actions.push(`<button class="btn btn--sm btn--primary" data-act="complete" data-wo="${w.id}">Complete</button>`);
      if (['draft', 'reserved', 'running'].includes(w.status)) {
        actions.push(`<button class="btn btn--sm" data-act="cancel" data-wo="${w.id}">Cancel</button>`);
      }
      actions.push(`<button class="btn btn--sm" data-act="open-wo" data-wo="${w.id}">Open</button>`);
      return `
        <tr>
          <td class="col-status"><span class="dot dot--${dot}"></span></td>
          <td><div class="row-title">WO-${w.id}</div><div class="row-sub">${fmtDate(w.created_at)}</div></td>
          <td class="mono">${recipeLabel}</td>
          <td class="num">${w.target_qty}</td>
          <td>${statusTag(w.status)}</td>
          <td class="mono">${fmtDate(w.started_at)}</td>
          <td class="col-action" style="display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap;">${actions.join('')}</td>
        </tr>
      `;
    }).join('');
  }

  function renderAll() {
    renderKPIs();
    renderRecipes();
    renderWOs();
  }

  // ── Data load ───────────────────────────────────────────────────────
  async function refresh() {
    [recipes, workOrders] = await Promise.all([
      prodApi.listRecipes().catch(() => []),
      prodApi.listWOs().catch(() => []),
    ]);
    renderAll();
  }

  async function loadSKUs() {
    skus = await skuApi.list();
  }

  // ── Action handlers ─────────────────────────────────────────────────
  async function openCreateRecipe() {
    await loadSKUs();
    if (!skus.length) {
      alertModal('No SKUs available', 'Create at least one SKU in the inventory module before defining a recipe.');
      return;
    }
    // Step 1 — pick product SKU.
    const product = await confirmModal.form({
      title: 'Create recipe — step 1 of 2',
      body: 'Pick the product SKU this recipe produces.',
      fields: [{
        name: 'sku_id', label: 'Product SKU', type: 'select',
        options: skus.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.description}` })),
        required: true,
      }],
      confirmLabel: 'Next: ingredients',
    });
    if (!product) return;
    // Step 2 — at MVP, accept one ingredient line via form. A richer multi-line
    // editor would belong in a follow-up; structured fields here keep the
    // contract tight without dragging in a table component.
    const line = await confirmModal.form({
      title: 'Create recipe — step 2 of 2',
      body: 'Add the first ingredient line. (Additional lines can be appended via a future edit-recipe flow.)',
      fields: [
        { name: 'ingredient_sku_id', label: 'Ingredient SKU', type: 'select',
          options: skus.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.description}` })),
          required: true,
        },
        { name: 'qty_per_unit', label: 'Qty per output unit', type: 'number', value: '1', required: true },
        { name: 'uom', label: 'UoM', value: 'EA', required: true },
      ],
      confirmLabel: 'Create recipe',
    });
    if (!line) return;
    try {
      await prodApi.createRecipe({
        sku_id: Number(product.sku_id),
        lines: [{
          ingredient_sku_id: Number(line.ingredient_sku_id),
          qty_per_unit: Number(line.qty_per_unit),
          uom: line.uom,
        }],
      });
      await refresh();
    } catch (err) {
      alertModal('Create failed', err.message || 'Unknown error');
    }
  }

  async function openCreateWO() {
    if (!recipes.length) {
      alertModal('No recipes', 'Create a recipe first — a work order targets a specific recipe.');
      return;
    }
    const result = await confirmModal.form({
      title: 'Create work order',
      body: 'Pick a recipe and a target output quantity. The version is snapshotted at creation.',
      fields: [
        { name: 'recipe_id', label: 'Recipe', type: 'select',
          options: recipes.map((r) => ({ value: String(r.id), label: `Recipe #${r.id} · ${r.sku_code || ''} · v${r.version}` })),
          required: true,
        },
        { name: 'target_qty', label: 'Target quantity', type: 'number', value: '1', required: true },
      ],
      confirmLabel: 'Create',
    });
    if (!result) return;
    try {
      await prodApi.createWO({ recipe_id: Number(result.recipe_id), target_qty: Number(result.target_qty) });
      await refresh();
    } catch (err) {
      alertModal('Create failed', err.message || 'Unknown error');
    }
  }

  async function doPreflight(woId) {
    try {
      const r = await prodApi.preflight(woId);
      if (r.shortages && r.shortages.length) {
        const lines = r.shortages.map((s) => `  • ${s.ingredient_sku_code || s.ingredient_sku_id}: need ${s.required}, have ${s.available}, short ${s.short_by}`).join('\n');
        await alertModal('Shortage on preflight', `Work order stayed in draft.\n\n${lines}`);
      }
      await refresh();
    } catch (err) {
      alertModal('Preflight failed', err.message || 'Unknown error');
    }
  }

  async function doStart(woId) {
    try { await prodApi.start(woId); await refresh(); }
    catch (err) { alertModal('Start failed', err.message); }
  }

  async function doComplete(woId) {
    const r = await confirmModal.form({
      title: `Complete WO-${woId}`,
      body: 'Enter the actual produced quantity. A new child lot will be created and ingredient lots decremented.',
      fields: [
        { name: 'actual_qty', label: 'Actual qty', type: 'number', required: true },
        { name: 'output_lot_code', label: 'Output lot code (optional)', value: '' },
      ],
      confirmLabel: 'Complete WO',
    });
    if (!r) return;
    try {
      await prodApi.complete(woId, {
        actual_qty: Number(r.actual_qty),
        output_lot_code: r.output_lot_code || null,
      });
      await refresh();
    } catch (err) {
      alertModal('Complete failed', err.message);
    }
  }

  async function doCancel(woId) {
    const confirmed = await confirmModal.typed({
      title: `Cancel WO-${woId}?`,
      body: 'Reservations will be released. This cannot be undone.',
      confirmWord: 'CANCEL',
      confirmLabel: 'Cancel WO',
    });
    if (!confirmed) return;
    try { await prodApi.cancel(woId); await refresh(); }
    catch (err) { alertModal('Cancel failed', err.message); }
  }

  async function openWO(woId) {
    try {
      const wo = await prodApi.getWO(woId);
      const detailEyebrow = $('[data-bind="detail-eyebrow"]');
      const detailTitle = $('[data-bind="detail-title"]');
      const detailBody = $('[data-bind="detail-body"]');
      const section = $('#detail-section');
      if (detailEyebrow) detailEyebrow.textContent = `Work order · ${wo.status}`;
      if (detailTitle) detailTitle.textContent = `WO-${wo.id}`;
      if (detailBody) detailBody.textContent = JSON.stringify(wo, null, 2);
      if (section) section.hidden = false;
    } catch (err) {
      alertModal('Open failed', err.message);
    }
  }

  async function openRecipe(recipeId) {
    try {
      const r = await prodApi.getRecipe(recipeId);
      const detailEyebrow = $('[data-bind="detail-eyebrow"]');
      const detailTitle = $('[data-bind="detail-title"]');
      const detailBody = $('[data-bind="detail-body"]');
      const section = $('#detail-section');
      if (detailEyebrow) detailEyebrow.textContent = `Recipe · v${r.version}`;
      if (detailTitle) detailTitle.textContent = `Recipe #${r.id} · ${r.sku_code || ''}`;
      if (detailBody) detailBody.textContent = JSON.stringify(r, null, 2);
      if (section) section.hidden = false;
    } catch (err) {
      alertModal('Open failed', err.message);
    }
  }

  function alertModal(title, body) {
    return confirmModal.alert({ title, body });
  }

  // ── Event wiring ────────────────────────────────────────────────────
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-act], [data-recipe], [data-filter], #btn-new-wo, #btn-new-recipe, #detail-close');
    if (!t) return;
    if (t.id === 'btn-new-wo') return openCreateWO();
    if (t.id === 'btn-new-recipe') return openCreateRecipe();
    if (t.id === 'detail-close') { $('#detail-section').hidden = true; return; }
    if (t.dataset.filter) {
      activeFilter = t.dataset.filter;
      $$('.filter-chip').forEach((c) => c.dataset.active = String(c.dataset.filter === activeFilter));
      renderWOs();
      return;
    }
    if (t.dataset.recipe) return openRecipe(Number(t.dataset.recipe));
    const wo = Number(t.dataset.wo);
    switch (t.dataset.act) {
      case 'preflight': return doPreflight(wo);
      case 'start': return doStart(wo);
      case 'complete': return doComplete(wo);
      case 'cancel': return doCancel(wo);
      case 'open-wo': return openWO(wo);
    }
  });

  // ── Init ────────────────────────────────────────────────────────────
  bind('site-name', WMS_API.getUser()?.site_id || '—');
  await refresh();
})();
