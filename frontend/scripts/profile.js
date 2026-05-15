/* ═══════════════════════════════════════════════════════════════════════════
   WMS Profile Page — read identity + edit settings + approval workflow
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    // Bounce unauthenticated visitors back to login
    window.location.href = 'login.html';
    return;
  }

  const $$ = (sel, root = document) => root.querySelectorAll(sel);
  const $ = (sel, root = document) => root.querySelector(sel);

  function setBind(name, value) {
    $$('[data-bind="' + name + '"]').forEach((el) => {
      if (el.tagName === 'INPUT') el.value = value || '';
      else el.textContent = value || '—';
    });
  }

  function setBanner(field, kind, text) {
    const b = document.getElementById(`${field}-banner`);
    if (!b) return;
    if (!text) { b.style.display = 'none'; b.textContent = ''; return; }
    b.style.display = 'block';
    b.className = 'field-banner field-banner--' + (kind === 'ok' ? 'ok' : 'err');
    b.textContent = (kind === 'ok' ? '✓ ' : '✗ ') + text;
  }

  function applyPolicy(profile) {
    const policy = profile.field_policy || {};
    const pending = new Set(profile.pending_requests || []);
    const pendingCountEl = $('[data-bind="pending-count"]');
    if (pendingCountEl) pendingCountEl.textContent = String(pending.size);

    Object.keys(policy).forEach((field) => {
      const row = document.getElementById('row-' + field);
      if (!row) return;
      const p = policy[field];

      if (!p.visible) { row.style.display = 'none'; return; }
      row.style.display = '';

      const metaEl = $('[data-bind="' + field + '-policy"]', row);
      if (metaEl) {
        if (!p.editable) metaEl.textContent = 'Locked by policy — contact your supervisor';
        else if (field === 'display_name' || field === 'display_picture') metaEl.textContent = 'Requires Level 3+ or supervisor approval';
        else metaEl.textContent = '';
      }

      const editBtn = $('[data-action="edit"][data-target="' + field + '"]', row);
      if (editBtn) editBtn.disabled = !p.editable;

      row.dataset.disabled = (!p.editable).toString();
      row.dataset.pending = pending.has(field).toString();
    });
  }

  function renderProfile(profile) {
    setBind('full-name', profile.full_name);
    setBind('employee-code', profile.employee_code);
    setBind('site-id', profile.site_id);
    setBind('department', profile.department || 'Unassigned');
    setBind('role-label', profile.role);
    setBind('shift', profile.shift || 'Unassigned');
    setBind('level-label', profile.permission_level);
    setBind('email', profile.email);
    setBind('display-name', profile.display_name || '(using real name)');
    setBind('display-picture-url', profile.display_picture_url || '(no avatar uploaded)');
    setBind('theme', profile.theme);
    setBind('user-name', profile.full_name);
    setBind('user-initial', (profile.full_name || '?').trim().charAt(0).toUpperCase());

    const status = $('[data-bind="settings-status"]');
    if (status) {
      const policy = profile.field_policy || {};
      const editable = Object.values(policy).filter((p) => p.editable).length;
      const visible = Object.values(policy).filter((p) => p.visible).length;
      status.textContent = `${editable} editable · ${visible} visible`;
    }

    applyPolicy(profile);
  }

  // ── Wire interactive form rows ───────────────────────────────────────
  function openForm(field) {
    $$('.inline-form').forEach((f) => (f.dataset.open = 'false'));
    const form = document.getElementById('form-' + field);
    if (form) form.dataset.open = 'true';
    setBanner(field, null, null);
  }

  function closeForm(field) {
    const form = document.getElementById('form-' + field);
    if (form) form.dataset.open = 'false';
  }

  async function saveField(field) {
    setBanner(field, null, null);
    try {
      if (field === 'email') {
        const v = document.getElementById('email-input').value.trim();
        await WMS_API.request('/profile/email', { method: 'PUT', body: { email: v } });
        setBanner('email', 'ok', 'Email updated');
      } else if (field === 'password') {
        const current = document.getElementById('password-current').value;
        const next = document.getElementById('password-new').value;
        await WMS_API.request('/profile/password', { method: 'PUT', body: { current_password: current, new_password: next } });
        setBanner('password', 'ok', 'Password updated');
        document.getElementById('password-current').value = '';
        document.getElementById('password-new').value = '';
      } else if (field === 'display_name') {
        const v = document.getElementById('display-name-input').value.trim();
        await WMS_API.request('/profile/display-name-request', { method: 'POST', body: { requested_value: v } });
        setBanner('display_name', 'ok', 'Request submitted — awaiting approval');
      } else if (field === 'display_picture') {
        const v = document.getElementById('display-picture-input').value.trim();
        await WMS_API.request('/profile/display-picture-request', { method: 'POST', body: { requested_value: v } });
        setBanner('display_picture', 'ok', 'Upload request submitted — awaiting approval');
      }
      setTimeout(loadProfile, 700);
    } catch (err) {
      setBanner(field, 'err', err.message);
    }
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const field = btn.dataset.target;
    if (action === 'edit') openForm(field);
    else if (action === 'cancel') closeForm(field);
    else if (action === 'save') saveField(field);
  });

  // ── Logout (page-level button + topbar chip stays inert here) ────────
  $('#logout-btn')?.addEventListener('click', () => {
    if (confirm('Sign out and clock off?')) {
      localStorage.removeItem('wms.token');
      localStorage.removeItem('wms.user');
      localStorage.removeItem('wms.activeSiteLabel');
      window.location.href = 'login.html';
    }
  });

  // The shared shell.js wires the topbar chip to confirm + logout.
  // On this page, override it to just stay (we're already on the profile).
  const chip = document.getElementById('user-chip');
  if (chip) {
    chip.replaceWith(chip.cloneNode(true));
  }

  // ── Bootstrap ────────────────────────────────────────────────────────
  async function loadProfile() {
    try {
      const data = await WMS_API.request('/profile');
      renderProfile(data);
    } catch (err) {
      const status = $('[data-bind="settings-status"]');
      if (status) status.textContent = 'Failed to load profile: ' + err.message;
      console.error('[Profile]', err);
    }
  }
  await loadProfile();

})();

