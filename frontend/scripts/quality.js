/* ═══════════════════════════════════════════════════════════════════════════
   Quality Page — live data wiring (SCO-50 MVP)
   Wires /api/v1/quality/holds — list, open, decide.
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    window.location.href = 'login.html';
    return;
  }

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const bind = (name, value) => $$(`[data-bind="${name}"]`).forEach((el) => { el.textContent = value; });
  const tag = (kind, text) => `<span class="tag tag--${kind}">${text}</span>`;

  const qApi = {
    list: (statusFilter = 'open') =>
      WMS_API.request(`/quality/holds?status_filter=${encodeURIComponent(statusFilter)}`),
    open: (body) => WMS_API.request('/quality/holds', { method: 'POST', body }),
    decide: (id, decision) => WMS_API.request(`/quality/holds/${id}/decide`, { method: 'POST', body: { decision } }),
  };
  const lotApi = {
    list: () => WMS_API.request('/inventory/lots').then((r) => r.lots || []).catch(() => []),
  };

  let holds = [];
  let activeFilter = 'open';

  function daysHeld(iso) {
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return 0;
    return Math.floor((Date.now() - t) / (1000 * 60 * 60 * 24));
  }

  function ageBucket(days) {
    if (days <= 14) return '0-14';
    if (days <= 21) return '15-21';
    if (days <= 30) return '22-30';
    return '31';
  }

  function renderKPIs() {
    const open = holds.filter((h) => h.status === 'open');
    const buckets = { '0-14': 0, '15-21': 0, '22-30': 0, '31': 0 };
    open.forEach((h) => { buckets[ageBucket(daysHeld(h.opened_at))]++; });
    bind('age-0-14', buckets['0-14']);
    bind('age-15-21', buckets['15-21']);
    bind('age-22-30', buckets['22-30']);
    bind('age-31', buckets['31']);
  }

  function severityTag(s) {
    if (s === 'high') return tag('crit', 'High');
    if (s === 'low') return tag('ok', 'Low');
    return tag('warn', 'Medium');
  }

  function statusTag(s) {
    return s === 'resolved' ? tag('ok', 'Resolved') : tag('warn', 'Open');
  }

  function renderTable() {
    const tbody = $('[data-bind="hold-tbody"]');
    if (!tbody) return;
    if (!holds.length) {
      tbody.innerHTML = '<tr data-empty><td colspan="8" class="empty-state">No holds match this filter.</td></tr>';
      return;
    }
    tbody.innerHTML = holds.map((h) => {
      const days = daysHeld(h.opened_at);
      const dot = h.status === 'resolved' ? 'ok' : days > 21 ? 'crit' : 'warn';
      const actions = h.status === 'open'
        ? `<button class="btn btn--sm btn-arrow" data-act="decide" data-hold="${h.id}"><span>Decide</span></button>`
        : '<span class="row-sub mono">—</span>';
      return `
        <tr>
          <td class="col-status"><span class="dot dot--${dot}"></span></td>
          <td><div class="row-title">${h.lot_code || `Lot #${h.lot_id}`}</div></td>
          <td class="mono">${h.sku_code || ''}</td>
          <td>${h.reason}</td>
          <td>${severityTag(h.severity)}</td>
          <td class="num">${days}d</td>
          <td>${statusTag(h.status)}</td>
          <td class="col-action">${actions}</td>
        </tr>
      `;
    }).join('');
  }

  async function refresh() {
    try { holds = await qApi.list(activeFilter); }
    catch (e) { holds = []; }
    renderKPIs();
    renderTable();
  }

  async function openHold() {
    const lots = await lotApi.list();
    if (!lots.length) {
      return confirmModal.alert({
        title: 'No lots',
        body: 'There are no lots in this site to place on hold.',
      });
    }
    const result = await confirmModal.form({
      title: 'Open QC hold',
      body: 'Pick a lot, describe the defect, set severity.',
      fields: [
        { name: 'lot_id', label: 'Lot', type: 'select',
          options: lots.map((l) => ({ value: String(l.id), label: `${l.lot_code} · ${l.sku_code || ''} · qty ${l.quantity}` })),
          required: true,
        },
        { name: 'reason', label: 'Reason', value: '', required: true, placeholder: 'e.g. visual defect on outer carton' },
        { name: 'severity', label: 'Severity', type: 'select',
          options: [
            { value: 'low', label: 'Low' },
            { value: 'medium', label: 'Medium' },
            { value: 'high', label: 'High' },
          ],
          value: 'medium',
        },
      ],
      confirmLabel: 'Open hold',
    });
    if (!result) return;
    try {
      await qApi.open({
        lot_id: Number(result.lot_id),
        reason: result.reason,
        severity: result.severity || 'medium',
      });
      await refresh();
    } catch (e) {
      confirmModal.alert({ title: 'Open failed', body: e.message || 'Unknown error' });
    }
  }

  async function decideHold(holdId) {
    const hold = holds.find((h) => h.id === holdId);
    const result = await confirmModal.form({
      title: `Decide hold #${holdId}`,
      body: `Resolve the hold on ${hold?.lot_code || 'this lot'}. Release returns the lot to available; destroy zeroes its quantity; rework clears the hold (recipe link is TODO in MVP).`,
      fields: [
        { name: 'decision', label: 'Decision', type: 'select',
          options: [
            { value: 'release', label: 'Release' },
            { value: 'rework', label: 'Rework' },
            { value: 'destroy', label: 'Destroy' },
          ],
          required: true,
        },
      ],
      confirmLabel: 'Apply decision',
    });
    if (!result) return;
    try {
      await qApi.decide(holdId, result.decision);
      await refresh();
    } catch (e) {
      confirmModal.alert({ title: 'Decision failed', body: e.message || 'Unknown error' });
    }
  }

  // Wire a "Open hold" button if the page-actions row has one; otherwise
  // expose via a floating button injected on first load.
  function ensureOpenHoldButton() {
    const actions = document.querySelector('.page-actions');
    if (actions && !document.getElementById('btn-open-hold')) {
      const btn = document.createElement('button');
      btn.id = 'btn-open-hold';
      btn.className = 'btn btn--primary btn-arrow';
      btn.innerHTML = '<span>Open hold</span>';
      actions.prepend(btn);
    }
  }

  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-act], [data-filter], #btn-open-hold');
    if (!t) return;
    if (t.id === 'btn-open-hold') return openHold();
    if (t.dataset.filter) {
      activeFilter = t.dataset.filter;
      $$('.filter-chip').forEach((c) => c.dataset.active = String(c.dataset.filter === activeFilter));
      refresh();
      return;
    }
    if (t.dataset.act === 'decide') return decideHold(Number(t.dataset.hold));
  });

  ensureOpenHoldButton();
  bind('site-name', WMS_API.getUser()?.site_id || '—');
  await refresh();
})();
