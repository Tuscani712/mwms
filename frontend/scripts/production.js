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
    // SCO-51 v2: returns 501 today — frontend handles gracefully.
    editRecipe: (id, body) => api(`/production/recipes/${id}`, { method: 'PUT', body }),
    listWOs: () => api('/production/work-orders'),
    createWO: (body) => api('/production/work-orders', { method: 'POST', body }),
    preflight: (id) => api(`/production/work-orders/${id}/preflight`, { method: 'POST' }),
    start: (id) => api(`/production/work-orders/${id}/start`, { method: 'POST' }),
    complete: (id, body) => api(`/production/work-orders/${id}/complete`, { method: 'POST', body }),
    cancel: (id) => api(`/production/work-orders/${id}/cancel`, { method: 'POST', body: {} }),
    getRecipe: (id) => api(`/production/recipes/${id}`),
    getWO: (id) => api(`/production/work-orders/${id}`),
  };
  // SCO-51 v2: variance audit feed. Endpoint not yet wired — .catch falls
  // through to empty state. When /admin/audit lands, swap the path here.
  const auditApi = {
    varianceEvents: () => api('/admin/audit?action=production.yield_variance_high&limit=10').catch(() => null),
  };

  // Yield variance threshold matches the registry default
  // (production.yield_variance_threshold = 0.01). When the settings store
  // backend lands, fetch this from /admin/settings instead of hardcoding.
  const YIELD_VARIANCE_THRESHOLD = 0.01;
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

  // SCO-51 v2: group recipes by SKU and render the version history as chips.
  // The latest version is highlighted; older versions stay clickable so an
  // operator can inspect what a running WO was started against (via its
  // recipe_version_snapshot). Today all recipes are v1, so each group shows
  // a single chip; the grouping logic costs nothing now and avoids a UI
  // rewrite the moment edit_recipe (version-bump-on-edit) lands.
  function renderRecipes() {
    const tbody = $('[data-bind="recipe-tbody"]');
    if (!tbody) return;
    if (!recipes.length) {
      tbody.innerHTML = '<tr data-empty><td colspan="6" class="empty-state">No recipes yet — create one to define a BOM.</td></tr>';
      return;
    }
    // Group by sku_id, sort versions descending so latest is first.
    const groups = new Map();
    for (const r of recipes) {
      const arr = groups.get(r.sku_id) || [];
      arr.push(r);
      groups.set(r.sku_id, arr);
    }
    for (const arr of groups.values()) {
      arr.sort((a, b) => b.version - a.version);
    }
    const rows = [];
    for (const [, arr] of groups) {
      const latest = arr[0];
      const versionChips = arr.map((r) => {
        const cls = r.id === latest.id ? 'tag tag--amber' : 'tag tag--info';
        return `<button class="${cls}" data-recipe="${r.id}" title="Open v${r.version} (created ${fmtDate(r.created_at)})" style="cursor:pointer;border:none;">v${r.version}</button>`;
      }).join(' ');
      rows.push(`
        <tr>
          <td>
            <div class="row-title">${latest.sku_code || ''}</div>
            <div class="row-sub mono">Recipe #${latest.id} · latest</div>
          </td>
          <td class="mono">${latest.sku_code || latest.sku_id}</td>
          <td class="num">${(latest.lines || []).length}</td>
          <td class="num" style="white-space:nowrap;">${versionChips}</td>
          <td class="mono">${fmtDate(latest.created_at)}</td>
          <td class="col-action" style="display:flex;gap:6px;justify-content:flex-end;">
            <button class="btn btn--sm" data-act="edit-recipe" data-recipe="${latest.id}">Edit</button>
            <button class="btn btn--sm btn-arrow" data-recipe="${latest.id}"><span>Open</span></button>
          </td>
        </tr>
      `);
    }
    tbody.innerHTML = rows.join('');
  }

  // SCO-51 v2: variance audit feed renderer. Reads from /admin/audit which
  // isn't wired yet — auditApi.varianceEvents() returns null on 404 and we
  // render the empty state. When the endpoint lands, this renders the list.
  async function renderVarianceFeed() {
    const list = $('#variance-list');
    const empty = $('#variance-empty');
    const meta = $('#variance-meta');
    if (!list || !empty) return;
    const events = await auditApi.varianceEvents();
    if (!events || !events.items || events.items.length === 0) {
      list.innerHTML = '';
      empty.style.display = '';
      if (meta) meta.textContent = events ? '0 events · last 24h' : 'backend wiring pending';
      return;
    }
    empty.style.display = 'none';
    if (meta) meta.textContent = `${events.items.length} events · last ${events.window_label || '24h'}`;
    list.innerHTML = events.items.map((e) => {
      const d = e.detail_json || {};
      const variance = typeof d.variance === 'number' ? (d.variance * 100).toFixed(1) : '?';
      const direction = d.direction || (d.actual_qty > d.target_qty ? 'over' : 'under');
      return `
        <li class="alert">
          <span class="dot dot--warn"></span>
          <div>
            <div class="alert-title">WO-${d.work_order_id ?? '?'} · ${variance}% ${direction}</div>
            <div class="alert-sub">target ${d.target_qty ?? '?'} → actual ${d.actual_qty ?? '?'}${d.child_lot_code ? ` · ${d.child_lot_code}` : ''}</div>
          </div>
          <span class="alert-time">${fmtDate(e.created_at || e.ts)}</span>
        </li>
      `;
    }).join('');
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
    // Variance feed fires its own async fetch; safe to fire-and-forget.
    renderVarianceFeed();
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

  // SCO-51 v2: preflight result handler now distinguishes quantity
  // shortages from BOM conversion-impossible errors. Both arrive in the
  // same `shortages[]` array per the backend contract (see preflight
  // TODO in services/production.py) — conversion failures carry
  // `error_kind: 'conversion_impossible'` plus `from_uom`/`to_uom`/`reason`.
  async function doPreflight(woId) {
    try {
      const r = await prodApi.preflight(woId);
      if (r.shortages && r.shortages.length) {
        const lines = r.shortages.map((s) => {
          if (s.error_kind === 'conversion_impossible') {
            return `  ⚠ ${s.sku_code || s.ingredient_sku_code || '?'}: cannot convert ${s.from_uom} → ${s.to_uom} (${s.reason || 'no conversion path'})`;
          }
          return `  • ${s.ingredient_sku_code || s.ingredient_sku_id}: need ${s.required}, have ${s.available}, short ${s.short_by}`;
        }).join('\n');
        const hasConversion = r.shortages.some((s) => s.error_kind === 'conversion_impossible');
        const title = hasConversion ? 'Preflight blocked — review issues' : 'Shortage on preflight';
        await alertModal(title, `Work order stayed in draft.\n\n${lines}`);
      }
      await refresh();
    } catch (err) {
      alertModal('Preflight failed', err.message || 'Unknown error');
    }
  }

  // SCO-51 v2: open the "Edit recipe" flow. Calls PUT /recipes/{id}.
  // The backend returns 501 today (api/v1/production.py:edit_recipe is a
  // dormant stub); the catch surfaces a clear toast rather than a generic
  // error. When the endpoint lands, this code does not change.
  async function openEditRecipe(recipeId) {
    const current = recipes.find((r) => r.id === recipeId);
    if (!current) {
      alertModal('Recipe not found', 'Refresh the page and try again.');
      return;
    }
    await loadSKUs();
    // MVP edit form: same single-line shape as create. A richer multi-line
    // editor is a follow-up, but the contract on the wire is already the
    // same {sku_id, lines: [...]} payload, so the backend wire-up doesn't
    // wait on the UI getting fancier.
    const existing = (current.lines && current.lines[0]) || { ingredient_sku_id: '', qty_per_unit: 1, uom: 'EA' };
    const result = await confirmModal.form({
      title: `Edit recipe #${current.id} (v${current.version})`,
      body: `Editing creates a new version (v${current.version + 1}). The current version stays queryable; running work orders keep their snapshot.`,
      fields: [
        { name: 'ingredient_sku_id', label: 'Ingredient SKU', type: 'select',
          options: skus.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.description}` })),
          value: String(existing.ingredient_sku_id || ''),
          required: true,
        },
        { name: 'qty_per_unit', label: 'Qty per output unit', type: 'number', value: String(existing.qty_per_unit || 1), required: true },
        { name: 'uom', label: 'UoM', value: existing.uom || 'EA', required: true },
      ],
      confirmLabel: `Create v${current.version + 1}`,
    });
    if (!result) return;
    try {
      await prodApi.editRecipe(recipeId, {
        sku_id: current.sku_id,
        lines: [{
          ingredient_sku_id: Number(result.ingredient_sku_id),
          qty_per_unit: Number(result.qty_per_unit),
          uom: result.uom,
        }],
      });
      await refresh();
    } catch (err) {
      // Backend returns 501 today; surface a clear "wiring pending" message
      // rather than a generic API error so the user knows it's expected.
      const msg = /501/.test(err.message || '')
        ? 'Recipe version-bump is not yet implemented on the backend (SCO-51 v2). The UI is ready; the endpoint stub is in api/v1/production.py:edit_recipe.'
        : (err.message || 'Unknown error');
      alertModal('Edit recipe (not yet wired)', msg);
    }
  }

  async function doStart(woId) {
    try { await prodApi.start(woId); await refresh(); }
    catch (err) { alertModal('Start failed', err.message); }
  }

  // SCO-51 v2: complete-WO flow now includes client-side yield variance
  // check. The server-side audit emission is still TODO in
  // services/production.py:complete_work_order; this UI warning is
  // informational only and never blocks (operator can confirm an
  // intentional variance). Threshold mirrors the registry default
  // (production.yield_variance_threshold = 0.01). When the settings
  // store backend lands, swap to a /admin/settings fetch on page load.
  async function doComplete(woId) {
    const wo = workOrders.find((w) => w.id === woId);
    const targetQty = wo ? wo.target_qty : null;
    const bodyLines = [
      'Enter the actual produced quantity. A new child lot will be created and ingredient lots decremented.',
    ];
    if (targetQty != null) bodyLines.push(`Target qty: ${targetQty}.`);
    const r = await confirmModal.form({
      title: `Complete WO-${woId}`,
      body: bodyLines.join('\n\n'),
      fields: [
        { name: 'actual_qty', label: 'Actual qty', type: 'number', required: true },
        { name: 'output_lot_code', label: 'Output lot code (optional)', value: '' },
      ],
      confirmLabel: 'Complete WO',
    });
    if (!r) return;
    const actualQty = Number(r.actual_qty);
    // Client-side variance gate. Pure UX — server enforces nothing here.
    if (targetQty != null && targetQty > 0) {
      const variance = Math.abs(actualQty - targetQty) / targetQty;
      if (variance > YIELD_VARIANCE_THRESHOLD) {
        const direction = actualQty > targetQty ? 'over' : 'under';
        const pct = (variance * 100).toFixed(2);
        const threshold = (YIELD_VARIANCE_THRESHOLD * 100).toFixed(2);
        const confirmed = await confirmModal.simple({
          title: `Yield variance · ${pct}% ${direction}`,
          body:
            `Actual ${actualQty} vs target ${targetQty} differs by ${pct}% — ` +
            `above the ${threshold}% threshold.\n\n` +
            `An audit event (production.yield_variance_high) will be recorded ` +
            `once the backend variance hook is wired (SCO-51 v2). ` +
            `Confirm to complete the work order anyway.`,
          confirmLabel: 'Yes, complete with variance',
          cancelLabel: 'Back',
          danger: true,
        });
        if (!confirmed) return;
      }
    }
    try {
      await prodApi.complete(woId, {
        actual_qty: actualQty,
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
    // [data-act] covers edit-recipe, preflight, start, complete, cancel,
    // open-wo. [data-recipe] without data-act opens the recipe drawer.
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
    // SCO-51 v2: edit-recipe button shares the data-recipe attribute with
    // the open-recipe chip, so dispatch on data-act first.
    if (t.dataset.act === 'edit-recipe') return openEditRecipe(Number(t.dataset.recipe));
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
