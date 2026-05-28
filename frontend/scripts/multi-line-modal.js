/* ═══════════════════════════════════════════════════════════════════════════
   Multi-line modal — header fields + dynamic list of repeating line rows.

   Used by ASN and Order creators where one transaction can carry several
   line items (one truckload, multiple SKUs). Built as a separate utility
   from confirm-modal.js because that one is single-instance flat-fields;
   bolting repeating-rows into it would muddy both APIs.

   API:
     WMS.multiLineModal({
       title:       'Create ASN',
       body:        'Header + line items in one shot.',
       headerFields:[ {name, label, required?, type?, placeholder?, value?, options?} ],
       lineFields:  [ {name, label, type?, value?, options?, placeholder?, required?} ],
       minLines:    1,
       maxLines:    20,
       addLineLabel:'Add line',
       confirmLabel:'Create',
     })
       → Promise< { header: {...}, lines: [{...}, ...] } | null >

   Reuses cm-* CSS classes from confirm-modal.js for visual consistency.
   Confirm-modal.js MUST be loaded before this script.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  const STYLE_ID = 'ml-modal-style';

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const css = `
      .ml-lines {
        display: flex;
        flex-direction: column;
        gap: var(--space-2, 8px);
        margin: var(--space-3, 16px) 0;
      }
      .ml-lines-head {
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--ink-tertiary, #888);
        padding-bottom: var(--space-2, 8px);
        border-bottom: 1px solid var(--rule-subtle, #2a2a30);
      }
      .ml-line {
        display: grid;
        grid-template-columns: 1fr 110px 36px;
        gap: var(--space-2, 8px);
        align-items: center;
      }
      .ml-line-remove {
        background: transparent;
        border: 1px solid var(--rule-default, #2a2a30);
        color: var(--ink-tertiary, #888);
        font-size: 16px;
        line-height: 1;
        padding: 6px 8px;
        cursor: pointer;
        transition: all 120ms ease;
      }
      .ml-line-remove:hover:not(:disabled) {
        color: var(--signal-crit, #ef4444);
        border-color: var(--signal-crit, #ef4444);
      }
      .ml-line-remove:disabled {
        opacity: 0.3;
        cursor: not-allowed;
      }
      .ml-add-line {
        align-self: flex-start;
        background: transparent;
        border: 1px dashed var(--rule-default, #2a2a30);
        color: var(--ink-secondary, #aaa);
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 8px 14px;
        cursor: pointer;
        transition: all 120ms ease;
        margin-top: var(--space-2, 8px);
      }
      .ml-add-line:hover:not(:disabled) {
        border-color: var(--amber, #FF6B1A);
        color: var(--amber, #FF6B1A);
      }
      .ml-add-line:disabled { opacity: 0.4; cursor: not-allowed; }
      .ml-modal { max-width: 680px !important; }
    `;
    const el = document.createElement('style');
    el.id = STYLE_ID;
    el.textContent = css;
    document.head.appendChild(el);
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function renderHeaderField(f, idx) {
    const fieldId = `ml-h-${idx}`;
    const label = `<label class="cm-field-label" for="${fieldId}">${escapeHtml(f.label || f.name)}${f.required ? '<span class="cm-required">*</span>' : ''}</label>`;
    if (f.type === 'select' && Array.isArray(f.options)) {
      const opts = f.options.map((o) =>
        `<option value="${escapeHtml(o.value)}"${String(o.value) === String(f.value ?? '') ? ' selected' : ''}>${escapeHtml(o.label)}</option>`,
      ).join('');
      return `<div>${label}<select class="cm-field-input" id="${fieldId}" name="${escapeHtml(f.name)}">${opts}</select></div>`;
    }
    return `<div>${label}<input class="cm-field-input" id="${fieldId}" name="${escapeHtml(f.name)}"
      type="${escapeHtml(f.type || 'text')}" value="${escapeHtml(f.value ?? '')}"
      placeholder="${escapeHtml(f.placeholder || '')}" autocomplete="off" /></div>`;
  }

  function renderLineRow(lineFields, lineIdx, canRemove, seedValues) {
    // Each line is a horizontal row: [fields...] [× remove]
    // For typical ASN: [SKU select] [qty input] [×]
    // For recipe (SCO-51 v2): [ingredient SKU select] [qty] [uom] [×]
    // seedValues is an optional { fieldName → value } map for preloading
    // existing rows on edit flows.
    const cells = lineFields.map((f, fIdx) => {
      const fieldId = `ml-l-${lineIdx}-${fIdx}`;
      const seeded = seedValues && Object.prototype.hasOwnProperty.call(seedValues, f.name)
        ? seedValues[f.name]
        : f.value;
      if (f.type === 'select' && Array.isArray(f.options)) {
        const opts = f.options.map((o) =>
          `<option value="${escapeHtml(o.value)}"${String(o.value) === String(seeded ?? '') ? ' selected' : ''}>${escapeHtml(o.label)}</option>`,
        ).join('');
        return `<select class="cm-field-input" id="${fieldId}" data-line-name="${escapeHtml(f.name)}">${opts}</select>`;
      }
      return `<input class="cm-field-input" id="${fieldId}" data-line-name="${escapeHtml(f.name)}"
        type="${escapeHtml(f.type || 'text')}" value="${escapeHtml(seeded ?? '')}"
        placeholder="${escapeHtml(f.placeholder || '')}" autocomplete="off" />`;
    }).join('');
    const removeBtn = `<button type="button" class="ml-line-remove" data-line-remove ${canRemove ? '' : 'disabled'} aria-label="Remove line">×</button>`;
    return `<div class="ml-line" data-line-row>${cells}${removeBtn}</div>`;
  }

  function multiLineModal({
    title = 'Create',
    body = '',
    headerFields = [],
    lineFields = [],
    minLines = 1,
    maxLines = 20,
    addLineLabel = 'Add line',
    confirmLabel = 'Create',
    cancelLabel = 'Cancel',
    // SCO-141: optional CSS grid-template-columns override for the line row.
    // The default `1fr 110px 36px` fits 2 fields (select + qty) + remove btn.
    // Consumers with N fields pass an explicit template, e.g. recipes use
    // `1fr 110px 80px 36px` for ingredient SKU + qty + UoM + ×.
    lineGridTemplate = null,
    // SCO-141: preload existing rows for edit flows. Array of
    // { fieldName → value } objects, one per row. When supplied, seeds the
    // modal with these rows instead of `minLines` empty ones. The user can
    // still add/remove rows up to maxLines.
    initialLines = null,
  } = {}) {
    // confirm-modal.js injects the cm-* base styles on its first call. Force
    // it by opening + immediately resolving an alert with no UI footprint —
    // safer than assuming load order.
    if (window.confirmModal && !document.getElementById('cm-backdrop')) {
      // Trigger inject() by referencing a method that calls it.
      // (Each call to open() invokes inject() internally; alert is the
      // lightest entry point but would display UI. Instead manually create
      // a hidden backdrop is not needed — cm styles get injected on the
      // first real confirm-modal call. We just need them at render time;
      // the dialog calls open() in normal flow anyway.)
    }
    injectStyle();

    return new Promise((resolve) => {
      const root = document.createElement('div');
      root.className = 'cm-backdrop';
      root.dataset.open = 'true';
      root.style.zIndex = '900';
      root.innerHTML = `
        <div class="cm-modal ml-modal" role="dialog" aria-modal="true" aria-labelledby="ml-title">
          <h2 id="ml-title">${escapeHtml(title)}</h2>
          ${body ? `<p>${escapeHtml(body)}</p>` : ''}
          <div class="cm-fields" id="ml-header-fields">
            ${headerFields.map(renderHeaderField).join('')}
          </div>
          <div class="ml-lines-head">Line items</div>
          <div class="ml-lines" id="ml-lines"></div>
          <button type="button" class="ml-add-line" id="ml-add-line">+ ${escapeHtml(addLineLabel)}</button>
          <div class="cm-footer" style="margin-top: var(--space-4, 20px);">
            <button type="button" class="cm-btn" id="ml-cancel">${escapeHtml(cancelLabel)}</button>
            <button type="button" class="cm-btn" id="ml-confirm">${escapeHtml(confirmLabel)}</button>
          </div>
        </div>
      `;
      document.body.appendChild(root);

      const linesEl = root.querySelector('#ml-lines');
      const addBtn = root.querySelector('#ml-add-line');
      const confirmBtn = root.querySelector('#ml-confirm');
      const cancelBtn = root.querySelector('#ml-cancel');

      function lineCount() { return linesEl.querySelectorAll('[data-line-row]').length; }

      function syncControls() {
        const count = lineCount();
        addBtn.disabled = count >= maxLines;
        linesEl.querySelectorAll('.ml-line-remove').forEach((btn) => {
          btn.disabled = count <= minLines;
        });
      }

      function addLine(seedValues) {
        if (lineCount() >= maxLines) return;
        const html = renderLineRow(lineFields, lineCount(), true, seedValues);
        linesEl.insertAdjacentHTML('beforeend', html);
        // Apply optional grid template to the newly added row. Setting it
        // on the row element (not the container) keeps per-modal CSS
        // scoping without polluting the global .ml-line rule.
        if (lineGridTemplate) {
          const rows = linesEl.querySelectorAll('[data-line-row]');
          const last = rows[rows.length - 1];
          if (last) last.style.gridTemplateColumns = lineGridTemplate;
        }
        syncControls();
      }

      // Seed initialLines if provided (edit flow), otherwise minLines empty rows.
      if (Array.isArray(initialLines) && initialLines.length > 0) {
        initialLines.forEach((seed) => addLine(seed));
      } else {
        for (let i = 0; i < minLines; i++) addLine();
      }

      addBtn.addEventListener('click', addLine);

      linesEl.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-line-remove]');
        if (!btn || btn.disabled) return;
        btn.closest('[data-line-row]')?.remove();
        syncControls();
      });

      function close(result) {
        root.remove();
        resolve(result);
      }

      cancelBtn.addEventListener('click', () => close(null));
      root.addEventListener('click', (e) => { if (e.target === root) close(null); });
      function onKey(e) {
        if (e.key === 'Escape') { document.removeEventListener('keydown', onKey); close(null); }
      }
      document.addEventListener('keydown', onKey);

      confirmBtn.addEventListener('click', () => {
        // Validate header fields.
        const headerOut = {};
        let firstInvalid = null;
        headerFields.forEach((f) => {
          const el = root.querySelector(`#ml-header-fields [name="${f.name}"]`);
          const v = (el && el.value != null) ? String(el.value).trim() : '';
          if (f.required && !v) {
            el?.setAttribute('aria-invalid', 'true');
            if (!firstInvalid) firstInvalid = el;
          } else {
            el?.removeAttribute('aria-invalid');
          }
          headerOut[f.name] = v;
        });
        // Validate line rows.
        const lineOuts = [];
        root.querySelectorAll('[data-line-row]').forEach((rowEl) => {
          const lineObj = {};
          lineFields.forEach((f) => {
            const el = rowEl.querySelector(`[data-line-name="${f.name}"]`);
            const v = (el && el.value != null) ? String(el.value).trim() : '';
            if (f.required !== false && !v) {
              el?.setAttribute('aria-invalid', 'true');
              if (!firstInvalid) firstInvalid = el;
            } else {
              el?.removeAttribute('aria-invalid');
            }
            lineObj[f.name] = v;
          });
          lineOuts.push(lineObj);
        });
        if (firstInvalid) { firstInvalid.focus(); return; }
        document.removeEventListener('keydown', onKey);
        close({ header: headerOut, lines: lineOuts });
      });

      setTimeout(() => {
        const firstInput = root.querySelector('.cm-field-input');
        if (firstInput) {
          firstInput.focus();
          if (firstInput.value && typeof firstInput.select === 'function') firstInput.select();
        }
      }, 0);
    });
  }

  window.WMS = window.WMS || {};
  window.WMS.multiLineModal = multiLineModal;
})();
