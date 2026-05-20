/* ═══════════════════════════════════════════════════════════════════════════
   Receiving Page — live data wiring
   ─────────────────────────────────────────────────────────────────────────
   Currently wired:
     • GET /api/v1/receiving/inbound → inbound queue table

   To wire (endpoints listed are NOT YET BUILT unless marked existing):
     • GET /receiving/kpis              → KPI tiles (units, avg time, variances, holds)
     • GET /receiving/docks             → status ticker dock states
     • GET /receiving/asn/{id}          → QC inspection panel rows
     • POST /receiving/qc/{line_id}     → per-line QC pass/hold update
     • POST /receiving/receipts          (existing) → Complete QC button
     • GET /receiving/putaway-suggestions/{id}  (existing) → Putaway aside
     • POST /receiving/putaway/assign   → Assign & print labels button
     • GET /receiving/search?q=         → Search input

   Auth: if not signed in, render "Sign in to load data" empty states.
   Never substitute mock data — the UI must reflect reality.
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  const tbody = document.querySelector('[data-bind="receiving-inbound-rows"]');
  const statusEl = document.querySelector('[data-bind="receiving-data-status"]');
  if (!tbody) return;

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
    return map[status] || `<span class="tag">${String(status || '').toUpperCase()}</span>`;
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
    tbody.innerHTML = emptyRow('Sign in to load inbound data');
    return;
  }

  try {
    setStatus('Loading inbound…', false);
    const asns = await WMS_API.receiving.inbound();
    if (!asns.length) {
      tbody.innerHTML = emptyRow('No inbound ASNs.');
      setStatus('Live · 0 inbound', true);
      return;
    }
    tbody.innerHTML = asns
      .map((a) => {
        const lineCount = a.lines.length;
        const totalExpected = a.lines.reduce((s, ln) => s + ln.expected_qty, 0);
        return `
          <tr data-asn-id="${a.id}">
            <td><span class="mono">${a.asn_code}</span></td>
            <td>${a.supplier}</td>
            <td>${a.dock_door || '<span class="muted">—</span>'}</td>
            <td>${statusTag(a.status)}</td>
            <td><span class="mono">${lineCount} lines · ${totalExpected} units</span></td>
            <td class="mono">${fmtTime(a.eta)}</td>
          </tr>
        `;
      })
      .join('');
    setStatus(`Live · ${asns.length} inbound`, true);
  } catch (err) {
    console.warn('[WMS Receiving] inbound fetch failed:', err.message);
    tbody.innerHTML = emptyRow('Backend unreachable.');
    setStatus('Backend unreachable', false);
  }
})();
