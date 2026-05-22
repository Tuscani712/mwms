/* ═══════════════════════════════════════════════════════════════════════════
   Receiving Page — live workflow wiring
   ─────────────────────────────────────────────────────────────────────────
   Wired in this pass:
     • GET /api/v1/receiving/inbound               → inbound queue table
     • POST /api/v1/receiving/check-in             → dock assignment / start receipt
     • POST /api/v1/receiving/receipts             → complete receipt + create lots
     • GET /api/v1/receiving/putaway-suggestions/:id → putaway aside

   Still deferred to follow-up backend work:
     • GET /receiving/kpis
     • GET /receiving/docks
     • GET /receiving/asn/{id}
     • POST /receiving/qc/{line_id}
     • POST /receiving/putaway/assign
     • GET /receiving/search?q=

   Strategy:
     • Use the inbound payload as the working ASN detail until a dedicated
       ASN-detail endpoint exists.
     • “Begin new receipt” performs check-in if needed, then turns the QC
       panel into an inline receipt editor.
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  const tbody = document.querySelector('[data-bind="receiving-inbound-rows"]');
  const statusEl = document.querySelector('[data-bind="receiving-data-status"]');
  const btnBeginReceipt = document.querySelector('[data-action="receipt-new"]');
  const btnCompleteQC = document.querySelector('[data-action="qc-complete"]');
  const qcRowsEl = document.querySelector('[data-bind="qc-rows"]');
  const qcLineCountEl = document.querySelector('[data-bind="qc-line-count"]');
  const qcProgressTagEl = document.querySelector('[data-bind="qc-progress-tag"]');
  const qcEyebrowEl = document.querySelector('[data-bind="qc-eyebrow"]');
  const putawayPrimaryCodeEl = document.querySelector('[data-bind="putaway-primary-code"]');
  const putawayPrimaryMetaEl = document.querySelector('[data-bind="putaway-primary-meta"]');
  const putawayPrimaryMeterEl = document.querySelector('[data-bind="putaway-primary-meter"]');
  const putawayOverflowCodeEl = document.querySelector('[data-bind="putaway-overflow-code"]');
  const putawayOverflowMetaEl = document.querySelector('[data-bind="putaway-overflow-meta"]');
  const putawayOverflowMeterEl = document.querySelector('[data-bind="putaway-overflow-meter"]');

  if (!tbody || !window.WMS_API) return;

  const state = {
    asns: [],
    selectedAsnId: null,
    activeReceiptAsnId: null,
    putawayLoadId: 0,
  };

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[char]));
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function statusTag(status) {
    const map = {
      scheduled: '<span class="tag">SCHEDULED</span>',
      arrived: '<span class="tag tag--warn">ARRIVED</span>',
      receiving: '<span class="tag tag--ok">RECEIVING</span>',
      received: '<span class="tag tag--ok">RECEIVED</span>',
    };
    return map[status] || `<span class="tag">${escapeHtml(String(status || '').toUpperCase())}</span>`;
  }

  function setStatus(text, isLive = false) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.dataset.live = isLive ? 'true' : 'false';
  }

  function emptyRow(text) {
    return `<tr><td colspan="6" class="muted" style="text-align:center;padding:24px;color:var(--ink-tertiary);font-family:var(--font-mono);font-size:var(--text-xs)">${escapeHtml(text)}</td></tr>`;
  }

  function selectedAsn() {
    return state.asns.find((asn) => asn.id === state.selectedAsnId) || null;
  }

  function activeReceiptAsn() {
    return state.asns.find((asn) => asn.id === state.activeReceiptAsnId) || null;
  }

  function setPutaway(primary = {}, overflow = {}) {
    if (putawayPrimaryCodeEl) putawayPrimaryCodeEl.textContent = primary.code || '—';
    if (putawayPrimaryMetaEl) putawayPrimaryMetaEl.textContent = primary.meta || '—';
    if (putawayPrimaryMeterEl) putawayPrimaryMeterEl.style.width = `${primary.meter || 0}%`;
    if (putawayOverflowCodeEl) putawayOverflowCodeEl.textContent = overflow.code || '—';
    if (putawayOverflowMetaEl) putawayOverflowMetaEl.textContent = overflow.meta || '—';
    if (putawayOverflowMeterEl) putawayOverflowMeterEl.style.width = `${overflow.meter || 0}%`;
  }

  function resetPutaway(message = 'Select an ASN to load suggestions') {
    setPutaway(
      { code: '—', meta: message, meter: 0 },
      { code: '—', meta: '—', meter: 0 },
    );
  }

  function updateActionState() {
    const selected = selectedAsn();
    if (btnBeginReceipt) btnBeginReceipt.disabled = !selected;

    const active = activeReceiptAsn();
    const editable = active && active.status === 'receiving';
    if (btnCompleteQC) btnCompleteQC.disabled = !editable;
  }

  function renderInbound() {
    if (!state.asns.length) {
      tbody.innerHTML = emptyRow('No inbound ASNs.');
      return;
    }

    tbody.innerHTML = state.asns
      .map((asn) => {
        const isSelected = asn.id === state.selectedAsnId;
        const lineCount = asn.lines.length;
        const totalExpected = asn.lines.reduce((sum, line) => sum + Number(line.expected_qty || 0), 0);
        const selectedStyle = isSelected
          ? 'background:rgba(255,107,26,0.08);box-shadow:inset 0 0 0 1px rgba(255,107,26,0.22);'
          : '';
        return `
          <tr data-asn-id="${asn.id}" aria-selected="${isSelected ? 'true' : 'false'}" style="cursor:pointer;${selectedStyle}">
            <td><span class="mono">${escapeHtml(asn.asn_code)}</span></td>
            <td>${escapeHtml(asn.supplier)}</td>
            <td>${asn.dock_door ? escapeHtml(asn.dock_door) : '<span class="muted">—</span>'}</td>
            <td>${statusTag(asn.status)}</td>
            <td><span class="mono">${lineCount} lines · ${totalExpected} units</span></td>
            <td class="mono">${fmtTime(asn.eta)}</td>
          </tr>
        `;
      })
      .join('');
  }

  function renderPreview(asn) {
    if (!qcRowsEl) return;
    if (!asn) {
      qcRowsEl.innerHTML = emptyRow('Select an ASN from the inbound queue to load line items');
      if (qcLineCountEl) qcLineCountEl.textContent = 'No active receipt';
      if (qcProgressTagEl) qcProgressTagEl.textContent = '—';
      if (qcEyebrowEl) qcEyebrowEl.textContent = 'Active Receipt';
      updateActionState();
      return;
    }

    if (qcLineCountEl) qcLineCountEl.textContent = `${asn.asn_code} · ${asn.lines.length} line${asn.lines.length === 1 ? '' : 's'}`;
    if (qcProgressTagEl) qcProgressTagEl.textContent = asn.status === 'receiving' ? 'READY' : asn.status.toUpperCase();
    if (qcEyebrowEl) qcEyebrowEl.textContent = `${asn.supplier} · receipt preview`;

    qcRowsEl.innerHTML = asn.lines
      .map((line) => `
        <tr>
          <td class="col-status"><span class="dot ${asn.status === 'receiving' ? 'dot--ok' : 'dot--amber'}"></span></td>
          <td class="mono">${escapeHtml(line.sku_code)}</td>
          <td>${escapeHtml(line.sku_description)}</td>
          <td class="num">${Number(line.expected_qty || 0)}</td>
          <td><span class="tag">AWAITING QC</span></td>
          <td><span class="mono" style="color:var(--ink-tertiary)">Click Begin new receipt</span></td>
        </tr>
      `)
      .join('');

    updateActionState();
  }

  function renderReceiptEditor(asn) {
    if (!qcRowsEl) return;
    if (!asn) {
      renderPreview(selectedAsn());
      return;
    }

    if (qcLineCountEl) qcLineCountEl.textContent = `${asn.asn_code} · ${asn.lines.length} line${asn.lines.length === 1 ? '' : 's'}`;
    if (qcProgressTagEl) qcProgressTagEl.textContent = 'RECEIVING';
    if (qcEyebrowEl) qcEyebrowEl.textContent = `${asn.supplier} · dock ${asn.dock_door || '—'}`;

    qcRowsEl.innerHTML = asn.lines
      .map((line) => {
        const expectedQty = Number(line.expected_qty || 0);
        // SCO-138: lines whose SKU was created with requires_qc=false
        // auto-pass — no decision to make. completeReceipt() reads
        // data-qc-auto="pass" off the row in that case.
        const requiresQc = line.requires_qc === true;
        const qcCell = requiresQc
          ? `<select class="input receipt-qc-select" style="min-width:160px;">
               <option value="pass">Accepted</option>
               <option value="hold">Hold for QA</option>
             </select>`
          : `<span class="tag" style="background:rgba(70,200,120,0.10);color:var(--signal-ok);border-color:var(--signal-ok);">
               AUTO-PASS · no QC required
             </span>`;
        const qcRequirementCell = requiresQc
          ? `<span class="tag" style="background:rgba(255,107,26,0.10);color:var(--amber);border-color:var(--amber);">REQUIRES QC</span>`
          : `<span class="mono" style="color:var(--ink-tertiary)">—</span>`;
        return `
          <tr data-asn-line-id="${line.id}" data-qc-auto="${requiresQc ? 'manual' : 'pass'}">
            <td class="col-status"><span class="dot dot--ok"></span></td>
            <td class="mono">${escapeHtml(line.sku_code)}</td>
            <td>${escapeHtml(line.sku_description)}</td>
            <td class="num">
              <label style="display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span class="mono" style="color:var(--ink-tertiary)">EXP ${expectedQty}</span>
                <input
                  class="input receipt-qty-input"
                  type="number"
                  min="0"
                  step="1"
                  value="${expectedQty}"
                  style="width:88px;text-align:right"
                />
              </label>
            </td>
            <td>${qcCell}</td>
            <td>${qcRequirementCell}</td>
          </tr>
        `;
      })
      .join('');

    updateActionState();
  }

  async function loadPutaway(asnId) {
    if (!asnId) {
      resetPutaway();
      return;
    }
    const loadId = ++state.putawayLoadId;
    setPutaway(
      { code: 'Loading…', meta: 'Fetching FIFO suggestion', meter: 0 },
      { code: 'Loading…', meta: 'Fetching overflow suggestion', meter: 0 },
    );
    try {
      const suggestions = await WMS_API.receiving.putaway(asnId);
      if (loadId !== state.putawayLoadId) return;
      if (!suggestions.length) {
        resetPutaway('No putaway suggestions returned');
        return;
      }

      const totalQty = suggestions.reduce((sum, row) => sum + Number(row.qty || 0), 0);
      const primary = suggestions[0];
      const overflow = suggestions[0];
      const primaryMeter = primary.primary_capacity_left > 0
        ? Math.min(100, Math.round((totalQty / primary.primary_capacity_left) * 100))
        : 100;
      const overflowMeter = overflow.overflow_capacity_left > 0
        ? Math.min(100, Math.round((totalQty / overflow.overflow_capacity_left) * 100))
        : 0;

      setPutaway(
        {
          code: primary.primary_location || '—',
          meta: `${suggestions.length} SKU line${suggestions.length === 1 ? '' : 's'} · ${totalQty} units · ${primary.rationale}`,
          meter: primaryMeter,
        },
        {
          code: overflow.overflow_location || '—',
          meta: `Capacity left ${Number(overflow.overflow_capacity_left || 0)} units`,
          meter: overflowMeter,
        },
      );
    } catch (err) {
      if (loadId !== state.putawayLoadId) return;
      resetPutaway('Putaway suggestions unavailable');
      console.warn('[WMS Receiving] putaway fetch failed:', err.message);
    }
  }

  function syncPanels() {
    const active = activeReceiptAsn();
    const selected = selectedAsn();
    if (active && active.status === 'receiving') {
      renderReceiptEditor(active);
    } else {
      renderPreview(selected);
    }
    updateActionState();
  }

  async function refreshInbound(preferredAsnId = state.selectedAsnId) {
    setStatus('Loading inbound…', false);
    const asns = await WMS_API.receiving.inbound();
    state.asns = Array.isArray(asns) ? asns : [];

    if (state.activeReceiptAsnId && !state.asns.some((asn) => asn.id === state.activeReceiptAsnId)) {
      state.activeReceiptAsnId = null;
    }

    if (preferredAsnId && state.asns.some((asn) => asn.id === preferredAsnId)) {
      state.selectedAsnId = preferredAsnId;
    } else {
      state.selectedAsnId = state.asns[0]?.id || null;
    }

    renderInbound();
    syncPanels();
    if (state.selectedAsnId) {
      void loadPutaway(state.selectedAsnId);
    } else {
      resetPutaway('No inbound ASN selected');
    }
    setStatus(`Live · ${state.asns.length} inbound`, true);
  }

  async function beginReceipt() {
    const asn = selectedAsn();
    if (!asn) {
      await window.confirmModal?.alert({ title: 'No ASN selected', body: 'Select an ASN from the inbound queue first.' });
      return;
    }
    if (asn.status === 'received') {
      await window.confirmModal?.alert({ title: 'Receipt already complete', body: `${asn.asn_code} is already marked received.` });
      return;
    }

    let active = asn;
    if (asn.status !== 'receiving') {
      const dock = await window.confirmModal?.form({
        title: 'Begin new receipt',
        body: `Assign a dock door for ${asn.asn_code} before QC begins.`,
        fields: [
          { name: 'dock_door', label: 'Dock door', required: true, placeholder: 'D1', value: asn.dock_door || '' },
        ],
        confirmLabel: 'Check in ASN',
      });
      if (!dock) return;
      try {
        active = await WMS_API.receiving.checkIn(asn.id, dock.dock_door.trim());
      } catch (err) {
        await window.confirmModal?.alert({ title: 'Check-in failed', body: err.message || 'Unknown error' });
        return;
      }
    }

    state.activeReceiptAsnId = active.id;
    await refreshInbound(active.id);
    state.activeReceiptAsnId = active.id;
    syncPanels();
  }

  async function completeReceipt() {
    const asn = activeReceiptAsn();
    if (!asn) return;

    const rows = Array.from(qcRowsEl.querySelectorAll('tr[data-asn-line-id]'));
    if (!rows.length) return;

    const lines = [];
    for (const row of rows) {
      const asnLineId = Number(row.dataset.asnLineId);
      const qtyInput = row.querySelector('.receipt-qty-input');
      const qcSelect = row.querySelector('.receipt-qc-select');
      const qty = Number(qtyInput?.value || NaN);
      if (!Number.isFinite(qty) || qty < 0 || !Number.isInteger(qty)) {
        qtyInput?.focus();
        await window.confirmModal?.alert({
          title: 'Invalid quantity',
          body: 'Every receipt line needs a whole-number quantity of 0 or greater.',
        });
        return;
      }
      lines.push({
        asn_line_id: asnLineId,
        qty_received: qty,
        qc_passed: (qcSelect?.value || 'pass') === 'pass',
      });
    }

    const totals = lines.reduce((sum, line) => sum + line.qty_received, 0);
    const notes = await window.confirmModal?.form({
      title: 'Complete QC',
      body: `Confirm receipt for ${asn.asn_code}. ${lines.length} line${lines.length === 1 ? '' : 's'} · ${totals} total units. Variance notes are optional.`,
      fields: [
        { name: 'variance_notes', label: 'Variance / QC notes', placeholder: 'Short 5 on pallet 2, one damaged case…' },
      ],
      confirmLabel: 'Create receipt',
    });
    if (!notes) return;

    try {
      const receipt = await WMS_API.receiving.createReceipt({
        asn_id: asn.id,
        lines,
        variance_notes: notes.variance_notes?.trim() || null,
      });
      state.activeReceiptAsnId = null;
      await refreshInbound(state.selectedAsnId);
      await window.confirmModal?.alert({
        title: 'Receipt created',
        body: `${asn.asn_code} received successfully. Created ${receipt.lot_ids.length} lot${receipt.lot_ids.length === 1 ? '' : 's'} with total variance ${receipt.total_variance}.`,
      });
    } catch (err) {
      await window.confirmModal?.alert({ title: 'Receipt failed', body: err.message || 'Unknown error' });
    }
  }

  tbody.addEventListener('click', (event) => {
    const row = event.target.closest('tr[data-asn-id]');
    if (!row) return;
    const asnId = Number(row.dataset.asnId);
    if (!Number.isFinite(asnId)) return;
    state.selectedAsnId = asnId;
    renderInbound();
    if (state.activeReceiptAsnId !== asnId) syncPanels();
    void loadPutaway(asnId);
  });

  btnBeginReceipt?.addEventListener('click', () => {
    void beginReceipt();
  });

  btnCompleteQC?.addEventListener('click', () => {
    void completeReceipt();
  });

  if (!WMS_API.isAuthed()) {
    setStatus('Signed out · sign in to load data', false);
    tbody.innerHTML = emptyRow('Sign in to load inbound data');
    renderPreview(null);
    resetPutaway('Sign in to load suggestions');
    updateActionState();
    return;
  }

  try {
    await refreshInbound();
  } catch (err) {
    console.warn('[WMS Receiving] inbound fetch failed:', err.message);
    tbody.innerHTML = emptyRow('Backend unreachable.');
    renderPreview(null);
    resetPutaway('Backend unreachable');
    setStatus('Backend unreachable', false);
    updateActionState();
  }
})();
