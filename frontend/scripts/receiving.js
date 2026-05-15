/* ═══════════════════════════════════════════════════════════════════════════
   Receiving Page — live data wiring
   Fetches ASNs from /api/v1/receiving/inbound and replaces the mock table body.
   If unauthed or API unreachable, the page falls back to the static mock content.
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
    return map[status] || `<span class="tag">${status.toUpperCase()}</span>`;
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
    setStatus('Loading inbound…', false);
    const asns = await WMS_API.receiving.inbound();
    if (!asns.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;padding:24px">No inbound ASNs.</td></tr>';
      setStatus(`Live · 0 inbound`, true);
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
    console.warn('[WMS Receiving] Falling back to mock data:', err.message);
    setStatus('Backend unreachable · showing demo data', false);
  }
})();
