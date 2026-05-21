/**
 * Reusable confirmation modal — replaces native confirm()/prompt()/alert().
 *
 * SCO-112. Created after browser-native confirm() popups triggered Chrome's
 * "Prevent additional dialogs" footgun, silently bricking subsequent
 * confirmations until the user hard-refreshed. See
 * memory/feedback_no_native_browser_popups.md for the rule.
 *
 * Two flavours:
 *   confirmModal.simple({title, body, confirmLabel, cancelLabel, danger})
 *     → Promise<boolean>
 *   confirmModal.typed({title, body, confirmWord, confirmLabel, cancelLabel})
 *     → Promise<boolean>  // user must type confirmWord to enable confirm
 *
 * Self-injecting DOM + CSS on first call. Uses a `cm-*` class prefix so it
 * never collides with the inline modal styles in users.html. Drop the
 * `<script src="scripts/confirm-modal.js"></script>` tag into any page that
 * needs it — no CSS or HTML changes required on the consuming page.
 */
(function () {
  'use strict';

  let injected = false;
  let activeResolver = null; // resolver fn for the currently-open modal

  function inject() {
    if (injected) return;
    injected = true;

    const style = document.createElement('style');
    style.textContent = `
      .cm-backdrop {
        position: fixed; inset: 0;
        background: var(--scrim, rgba(0,0,0,0.82));
        backdrop-filter: blur(2px);
        display: none; align-items: center; justify-content: center;
        z-index: var(--z-modal, 100);
      }
      .cm-backdrop[data-open="true"] { display: flex; }
      .cm-modal {
        background: var(--modal-surface, var(--elevated, #1A1A20));
        border: 1px solid var(--modal-border, var(--rule-default, rgba(255,255,255,0.12)));
        border-radius: 6px;
        padding: var(--space-5, 24px);
        max-width: 520px; width: calc(100% - 48px);
        box-shadow: 0 24px 64px rgba(0,0,0,0.5);
      }
      .cm-modal h2 {
        margin: 0 0 var(--space-3, 16px);
        font-family: var(--font-serif, serif);
        font-size: 20px;
        color: var(--ink-primary, #fff);
      }
      .cm-modal h2.cm-danger { color: var(--signal-crit, #e35); }
      .cm-modal p {
        color: var(--ink-secondary, #bbb);
        font-size: 13px; line-height: 1.55;
        margin: 0 0 var(--space-4, 20px);
      }
      .cm-typed-label {
        display: block;
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        letter-spacing: var(--tracking-wide, 0.06em);
        text-transform: uppercase;
        color: var(--ink-tertiary, #888);
        margin-bottom: 6px;
      }
      .cm-typed-label strong { color: var(--signal-crit, #e35); }
      .cm-typed-input {
        width: 100%; box-sizing: border-box;
        padding: 8px 10px;
        background: var(--surface-2, rgba(255,255,255,0.04));
        border: 1px solid var(--signal-crit, #e35);
        border-radius: 4px;
        color: var(--ink-primary, #fff);
        font-family: var(--font-mono, monospace);
        font-size: 14px;
        letter-spacing: 0.1em;
      }
      .cm-typed-input:focus { outline: none; border-color: var(--signal-crit, #e35); box-shadow: 0 0 0 2px rgba(238,51,85,0.25); }
      .cm-footer {
        display: flex; justify-content: flex-end; gap: var(--space-2, 12px);
        margin-top: var(--space-4, 20px);
      }
      .cm-btn {
        padding: 8px 16px;
        border: 1px solid var(--rule-default, rgba(255,255,255,0.12));
        background: transparent;
        color: var(--ink-primary, #fff);
        border-radius: 4px;
        font-family: var(--font-mono, monospace);
        font-size: 12px;
        cursor: pointer;
      }
      .cm-btn:hover { background: var(--surface-2, rgba(255,255,255,0.04)); }
      .cm-btn--danger {
        background: var(--signal-crit, #e35);
        border-color: var(--signal-crit, #e35);
        color: #fff;
      }
      .cm-btn--danger:hover { filter: brightness(1.1); }
      .cm-btn[disabled] { opacity: 0.4; cursor: not-allowed; }
    `;
    document.head.appendChild(style);

    const root = document.createElement('div');
    root.className = 'cm-backdrop';
    root.id = 'cm-backdrop';
    root.innerHTML = `
      <div class="cm-modal" role="dialog" aria-modal="true" aria-labelledby="cm-title">
        <h2 id="cm-title"></h2>
        <p id="cm-body"></p>
        <div id="cm-typed-wrap" hidden>
          <label class="cm-typed-label" id="cm-typed-label"></label>
          <input class="cm-typed-input" id="cm-typed-input" type="text" autocomplete="off" />
        </div>
        <div class="cm-footer">
          <button type="button" class="cm-btn" id="cm-cancel">Cancel</button>
          <button type="button" class="cm-btn" id="cm-confirm">Confirm</button>
        </div>
      </div>
    `;
    document.body.appendChild(root);

    root.addEventListener('click', (e) => {
      if (e.target === root) close(false);
    });
    document.getElementById('cm-cancel').addEventListener('click', () => close(false));
    document.getElementById('cm-confirm').addEventListener('click', () => close(true));
    document.addEventListener('keydown', (e) => {
      if (root.dataset.open !== 'true') return;
      if (e.key === 'Escape') close(false);
      if (e.key === 'Enter' && !document.getElementById('cm-confirm').disabled) close(true);
    });

    // Typed-mode input drives the confirm button's disabled state
    document.getElementById('cm-typed-input').addEventListener('input', (e) => {
      const expected = e.target.dataset.expected || '';
      document.getElementById('cm-confirm').disabled = (e.target.value !== expected);
    });
  }

  function close(result) {
    const root = document.getElementById('cm-backdrop');
    if (!root) return;
    root.dataset.open = 'false';
    const r = activeResolver;
    activeResolver = null;
    if (r) r(result);
  }

  function open({ title, body, confirmLabel, cancelLabel, danger, typed, confirmWord }) {
    inject();
    return new Promise((resolve) => {
      // If a previous modal is somehow still open, resolve it as cancelled.
      if (activeResolver) {
        const r = activeResolver;
        activeResolver = null;
        r(false);
      }
      activeResolver = resolve;

      const titleEl = document.getElementById('cm-title');
      titleEl.textContent = title || 'Confirm';
      titleEl.classList.toggle('cm-danger', !!danger);

      document.getElementById('cm-body').textContent = body || '';

      const wrap = document.getElementById('cm-typed-wrap');
      const labelEl = document.getElementById('cm-typed-label');
      const input = document.getElementById('cm-typed-input');
      const confirmBtn = document.getElementById('cm-confirm');

      if (typed && confirmWord) {
        wrap.hidden = false;
        labelEl.innerHTML = `Type <strong>${confirmWord}</strong> to confirm`;
        input.value = '';
        input.placeholder = confirmWord;
        input.dataset.expected = confirmWord;
        confirmBtn.disabled = true;
      } else {
        wrap.hidden = true;
        confirmBtn.disabled = false;
      }

      confirmBtn.textContent = confirmLabel || (danger ? 'Delete' : 'Confirm');
      confirmBtn.classList.toggle('cm-btn--danger', !!danger);
      document.getElementById('cm-cancel').textContent = cancelLabel || 'Cancel';

      document.getElementById('cm-backdrop').dataset.open = 'true';
      // Focus: input for typed, confirm button for simple (so Enter works)
      setTimeout(() => (typed && confirmWord ? input.focus() : confirmBtn.focus()), 0);
    });
  }

  window.confirmModal = {
    simple: ({ title, body, confirmLabel, cancelLabel, danger } = {}) =>
      open({ title, body, confirmLabel, cancelLabel, danger, typed: false }),
    typed: ({ title, body, confirmWord, confirmLabel, cancelLabel } = {}) =>
      open({
        title, body, confirmLabel, cancelLabel,
        danger: true, typed: true, confirmWord: confirmWord || 'DELETE',
      }),
  };
})();
