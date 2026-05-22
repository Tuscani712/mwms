/* ═══════════════════════════════════════════════════════════════════════════
   Shared toast utility — top-right, 10s default, stacks.

   API:
     WMS.toast.ok(msg)
     WMS.toast.err(msg)
     WMS.toast.info(msg, { actionLabel, onAction })
     WMS.toast.dismissAll()

   Action-bearing form: pass `actionLabel` + `onAction` to render a button
   inside the toast. Clicking it fires `onAction()` then dismisses. Used for
   the receiving "Undo" affordance after a check-in.

   Pure DOM + injected CSS; zero deps. Self-contained so any page that
   loads this script can call `WMS.toast.*` without HTML/CSS prep.
   ─────────────────────────────────────────────────────────────────────────── */

(() => {
  'use strict';

  const DEFAULT_DURATION_MS = 10_000;
  const CONTAINER_ID = 'wms-toast-container';
  const STYLE_ID = 'wms-toast-style';

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const css = `
      #${CONTAINER_ID} {
        position: fixed;
        top: 20px;
        right: 20px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        z-index: 9999;
        pointer-events: none;
        max-width: 420px;
      }
      .wms-toast {
        pointer-events: auto;
        display: grid;
        grid-template-columns: 1fr auto auto;
        gap: 10px;
        align-items: center;
        padding: 12px 14px;
        background-color: #0c0c10;
        background-color: var(--elevated, #0c0c10);
        border: 1px solid var(--rule-default, #2a2a30);
        border-left-width: 3px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.32);
        font-family: var(--font-mono, monospace);
        font-size: 12px;
        letter-spacing: 0.02em;
        color: var(--ink-primary, #e8e8eb);
        animation: wms-toast-in 180ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
      }
      .wms-toast--ok    { border-left-color: var(--signal-ok,   #4ade80); }
      .wms-toast--err   { border-left-color: var(--signal-crit, #ef4444); }
      .wms-toast--info  { border-left-color: var(--amber,       #FF6B1A); }
      .wms-toast-msg {
        line-height: 1.4;
        word-break: break-word;
      }
      .wms-toast-action {
        background: transparent;
        border: 1px solid var(--amber, #FF6B1A);
        color: var(--amber, #FF6B1A);
        padding: 4px 10px;
        font-family: inherit;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        cursor: pointer;
        transition: background 120ms ease;
      }
      .wms-toast-action:hover {
        background: rgba(255, 107, 26, 0.12);
      }
      .wms-toast-close {
        background: transparent;
        border: 0;
        color: var(--ink-tertiary, #888);
        font-size: 16px;
        line-height: 1;
        cursor: pointer;
        padding: 4px 6px;
      }
      .wms-toast-close:hover { color: var(--ink-primary, #fff); }
      .wms-toast.wms-toast--leaving {
        animation: wms-toast-out 160ms cubic-bezier(0.4, 0, 1, 1) both;
      }
      @keyframes wms-toast-in {
        from { opacity: 0; transform: translateX(20px); }
        to   { opacity: 1; transform: translateX(0); }
      }
      @keyframes wms-toast-out {
        from { opacity: 1; transform: translateX(0); }
        to   { opacity: 0; transform: translateX(20px); }
      }
    `;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = css;
    document.head.appendChild(style);
  }

  function getContainer() {
    let c = document.getElementById(CONTAINER_ID);
    if (!c) {
      c = document.createElement('div');
      c.id = CONTAINER_ID;
      c.setAttribute('role', 'status');
      c.setAttribute('aria-live', 'polite');
      document.body.appendChild(c);
    }
    return c;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function dismiss(toastEl) {
    if (!toastEl || toastEl.classList.contains('wms-toast--leaving')) return;
    toastEl.classList.add('wms-toast--leaving');
    setTimeout(() => toastEl.remove(), 180);
  }

  function show(kind, msg, opts = {}) {
    injectStyle();
    const container = getContainer();
    const duration = Number.isFinite(opts.duration) ? opts.duration : DEFAULT_DURATION_MS;

    const toastEl = document.createElement('div');
    toastEl.className = `wms-toast wms-toast--${kind}`;

    const actionHtml = (opts.actionLabel && typeof opts.onAction === 'function')
      ? `<button type="button" class="wms-toast-action" data-role="action">${escapeHtml(opts.actionLabel)}</button>`
      : '<span></span>';

    toastEl.innerHTML = `
      <div class="wms-toast-msg">${escapeHtml(msg)}</div>
      ${actionHtml}
      <button type="button" class="wms-toast-close" data-role="close" aria-label="Dismiss">×</button>
    `;

    container.appendChild(toastEl);

    let dismissTimer = setTimeout(() => dismiss(toastEl), duration);
    const cancelTimer = () => { if (dismissTimer) { clearTimeout(dismissTimer); dismissTimer = null; } };

    toastEl.addEventListener('mouseenter', cancelTimer);
    toastEl.addEventListener('mouseleave', () => {
      if (!dismissTimer) dismissTimer = setTimeout(() => dismiss(toastEl), 3000);
    });

    toastEl.querySelector('[data-role="close"]')?.addEventListener('click', () => {
      cancelTimer();
      dismiss(toastEl);
    });

    const actionBtn = toastEl.querySelector('[data-role="action"]');
    if (actionBtn) {
      actionBtn.addEventListener('click', () => {
        cancelTimer();
        try { opts.onAction(); } finally { dismiss(toastEl); }
      });
    }

    return toastEl;
  }

  function dismissAll() {
    document.querySelectorAll(`#${CONTAINER_ID} .wms-toast`).forEach(dismiss);
  }

  window.WMS = window.WMS || {};
  window.WMS.toast = {
    ok:   (msg, opts) => show('ok', msg, opts),
    err:  (msg, opts) => show('err', msg, opts),
    info: (msg, opts) => show('info', msg, opts),
    dismissAll,
  };
})();
