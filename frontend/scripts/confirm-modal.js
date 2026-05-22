/**
 * Reusable confirmation modal — replaces native confirm()/prompt()/alert().
 *
 * SCO-112. Created after browser-native confirm() popups triggered Chrome's
 * "Prevent additional dialogs" footgun, silently bricking subsequent
 * confirmations until the user hard-refreshed. See
 * memory/feedback_no_native_browser_popups.md for the rule.
 *
 * Four flavours:
 *   confirmModal.simple({title, body, confirmLabel, cancelLabel, danger})
 *     → Promise<boolean>
 *   confirmModal.typed({title, body, confirmWord, confirmLabel, cancelLabel})
 *     → Promise<boolean>  // user must type confirmWord to enable confirm
 *   confirmModal.form({title, body, fields, confirmLabel, cancelLabel})
 *     → Promise<Record<string,string>|null>  // null on cancel
 *     where fields = [{ name, label, value?, placeholder?, required?, type? }]
 *   confirmModal.alert({title, body, confirmLabel, danger})
 *     → Promise<void>  // single-button info dialog, replaces native alert()
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
      .cm-fields { display: flex; flex-direction: column; gap: var(--space-3, 16px); margin-bottom: var(--space-2, 12px); }
      .cm-field-label {
        display: block;
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        letter-spacing: var(--tracking-wide, 0.06em);
        text-transform: uppercase;
        color: var(--ink-tertiary, #888);
        margin-bottom: 6px;
      }
      .cm-field-label .cm-required { color: var(--signal-crit, #e35); margin-left: 4px; }
      .cm-field-input {
        width: 100%; box-sizing: border-box;
        padding: 8px 10px;
        background: var(--surface-2, rgba(255,255,255,0.04));
        border: 1px solid var(--rule-default, rgba(255,255,255,0.12));
        border-radius: 4px;
        color: var(--ink-primary, #fff);
        font-family: var(--font-mono, monospace);
        font-size: 14px;
      }
      .cm-field-input:focus { outline: none; border-color: var(--amber, #ff6b1a); box-shadow: 0 0 0 2px rgba(255,107,26,0.18); }
      .cm-field-input[aria-invalid="true"] { border-color: var(--signal-crit, #e35); }
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
        <div class="cm-fields" id="cm-fields" hidden></div>
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

  // Active mode: 'simple' | 'typed' | 'form'. Drives what close() resolves with.
  let activeMode = 'simple';
  let activeFields = null;

  function collectFormValues() {
    const fieldsEl = document.getElementById('cm-fields');
    const out = {};
    let firstInvalid = null;
    (activeFields || []).forEach((f) => {
      const el = fieldsEl.querySelector(`[name="${f.name}"]`);
      const v = (el && el.value != null) ? String(el.value).trim() : '';
      if (f.required && !v) {
        el.setAttribute('aria-invalid', 'true');
        if (!firstInvalid) firstInvalid = el;
      } else if (el) {
        el.removeAttribute('aria-invalid');
      }
      out[f.name] = v;
    });
    if (firstInvalid) {
      firstInvalid.focus();
      return null;
    }
    return out;
  }

  function close(result) {
    const root = document.getElementById('cm-backdrop');
    if (!root) return;
    // For form mode: result=true means "confirm pressed" → collect values; null if invalid (don't close).
    if (activeMode === 'form' && result === true) {
      const values = collectFormValues();
      if (values === null) return; // keep modal open on validation fail
      result = values;
    } else if (activeMode === 'form' && result === false) {
      result = null;
    }
    root.dataset.open = 'false';
    const r = activeResolver;
    activeResolver = null;
    activeMode = 'simple';
    activeFields = null;
    if (r) r(result);
  }

  function renderFields(fields) {
    const wrap = document.getElementById('cm-fields');
    wrap.innerHTML = '';
    fields.forEach((f, idx) => {
      const fieldId = `cm-field-${idx}`;
      const row = document.createElement('div');
      const labelHtml = `<label class="cm-field-label" for="${fieldId}">${escapeHtml(f.label || f.name)}${f.required ? '<span class="cm-required">*</span>' : ''}</label>`;
      if (f.type === 'select' && Array.isArray(f.options)) {
        // SCO-51: select support for picking SKUs / recipes in the form modal.
        const opts = f.options.map((o) =>
          `<option value="${escapeHtml(o.value)}"${String(o.value) === String(f.value ?? '') ? ' selected' : ''}>${escapeHtml(o.label)}</option>`,
        ).join('');
        row.innerHTML = `${labelHtml}<select class="cm-field-input" id="${fieldId}" name="${escapeHtml(f.name)}">${opts}</select>`;
      } else {
        row.innerHTML = `${labelHtml}<input class="cm-field-input" id="${fieldId}" name="${escapeHtml(f.name)}"
               type="${escapeHtml(f.type || 'text')}"
               value="${escapeHtml(f.value ?? '')}"
               placeholder="${escapeHtml(f.placeholder || '')}"
               autocomplete="off" />`;
      }
      wrap.appendChild(row);
    });
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function open({ title, body, confirmLabel, cancelLabel, danger, typed, confirmWord, form, fields, alertOnly }) {
    inject();
    return new Promise((resolve) => {
      // If a previous modal is somehow still open, resolve it as cancelled.
      if (activeResolver) {
        const r = activeResolver;
        activeResolver = null;
        r(activeMode === 'form' ? null : false);
      }
      activeResolver = resolve;
      activeMode = form ? 'form' : (typed ? 'typed' : 'simple');
      activeFields = form ? (fields || []) : null;

      const titleEl = document.getElementById('cm-title');
      titleEl.textContent = title || 'Confirm';
      titleEl.classList.toggle('cm-danger', !!danger);

      document.getElementById('cm-body').textContent = body || '';

      const typedWrap = document.getElementById('cm-typed-wrap');
      const fieldsWrap = document.getElementById('cm-fields');
      const typedLabel = document.getElementById('cm-typed-label');
      const typedInput = document.getElementById('cm-typed-input');
      const confirmBtn = document.getElementById('cm-confirm');

      if (form) {
        typedWrap.hidden = true;
        fieldsWrap.hidden = false;
        renderFields(activeFields);
        confirmBtn.disabled = false;
      } else if (typed && confirmWord) {
        typedWrap.hidden = false;
        fieldsWrap.hidden = true;
        typedLabel.innerHTML = `Type <strong>${escapeHtml(confirmWord)}</strong> to confirm`;
        typedInput.value = '';
        typedInput.placeholder = confirmWord;
        typedInput.dataset.expected = confirmWord;
        confirmBtn.disabled = true;
      } else {
        typedWrap.hidden = true;
        fieldsWrap.hidden = true;
        confirmBtn.disabled = false;
      }

      confirmBtn.textContent = confirmLabel || (danger ? 'Delete' : (form ? 'Save' : (alertOnly ? 'OK' : 'Confirm')));
      confirmBtn.classList.toggle('cm-btn--danger', !!danger);
      const cancelBtn = document.getElementById('cm-cancel');
      cancelBtn.textContent = cancelLabel || 'Cancel';
      cancelBtn.hidden = !!alertOnly;

      document.getElementById('cm-backdrop').dataset.open = 'true';
      // Focus: first form field for form mode, typed input for typed, confirm button for simple
      setTimeout(() => {
        if (form) {
          const first = fieldsWrap.querySelector('.cm-field-input');
          (first || confirmBtn).focus();
          if (first && first.value && typeof first.select === 'function') first.select();
        } else if (typed && confirmWord) {
          typedInput.focus();
        } else {
          confirmBtn.focus();
        }
      }, 0);
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
    form: ({ title, body, fields, confirmLabel, cancelLabel } = {}) =>
      open({ title, body, confirmLabel, cancelLabel, form: true, fields: fields || [] }),
    alert: ({ title, body, confirmLabel, danger } = {}) =>
      open({ title, body, confirmLabel, danger, alertOnly: true }).then(() => undefined),
  };

  // Eagerly inject cm-* styles at script load so consumers (e.g.
  // multi-line-modal.js) can rely on the classes existing before any
  // confirm-modal call happens. Was lazy-injected before; the lazy path
  // still works for confirmModal.* itself.
  inject();
})();
