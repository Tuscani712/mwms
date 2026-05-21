/* ═══════════════════════════════════════════════════════════════════════════
   WMS · Admin · User Management page
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    window.location.href = 'login.html';
    return;
  }

  // ── Caller identity (for self-delete guard, SCO-88 follow-up) ───────
  // We need the caller's numeric user id to disable their row in the
  // table. The cached wms.user from setSession() doesn't carry an id
  // (TokenResponse never exposed one), so hit /auth/me — the canonical
  // source. Fetched once at module init, before the first list render,
  // so by the time renderTable runs the id is already in hand. Cached
  // on window so a soft re-init reuses it.
  let callerId = window.__wmsCallerId ?? null;
  if (callerId == null) {
    try {
      const me = await WMS_API.me();
      callerId = me?.id ?? null;
      window.__wmsCallerId = callerId;
    } catch (e) {
      // If /auth/me fails the page-load redirect to login.html will fire
      // soon anyway; leaving callerId null just means the guard no-ops.
      console.warn('caller-id lookup failed:', e?.message || e);
    }
  }

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // ── State ──────────────────────────────────────────────────────────
  const state = {
    page: 0,
    limit: 25,
    total: 0,
    filters: { q: '', role: '', level: '', include_inactive: false },
    tiers: {},
    rolesSeen: new Set(),
    editing: null, // user object being edited, or null for create
    // SCO-91/92: selection persists across pagination by user id (not row idx).
    // The Map carries display labels too so the bulk-confirm modal can show
    // something useful even after the rows have scrolled out of view.
    selected: new Map(), // id -> "Full Name (CODE)"
    // Index of users currently rendered, used to drive master-checkbox state
    // and to apply "select all visible" without re-fetching.
    pageRows: [], // list of {id, label} for current rendered page
  };

  // ── Toast ──────────────────────────────────────────────────────────
  function toast(kind, text, ms = 2400) {
    const el = $('#toast');
    el.className = 'toast toast--' + (kind === 'err' ? 'err' : 'ok');
    el.textContent = (kind === 'err' ? '✗ ' : '✓ ') + text;
    el.dataset.open = 'true';
    setTimeout(() => { el.dataset.open = 'false'; }, ms);
  }

  // ── API ────────────────────────────────────────────────────────────
  const A = WMS_API;

  function buildQuery() {
    const f = state.filters;
    const p = new URLSearchParams();
    p.set('limit', state.limit);
    p.set('offset', state.page * state.limit);
    if (f.q) p.set('q', f.q);
    if (f.role) p.set('role', f.role);
    if (f.level) { p.set('level_min', f.level); p.set('level_max', f.level); }
    if (f.include_inactive) p.set('include_inactive', 'true');
    return p.toString();
  }

  async function loadTiers() {
    state.tiers = await A.request('/admin/users/tiers/labels');
    const levelFilter = $('#filter-level');
    const levelForm = $('#form-permission_level');
    Object.keys(state.tiers)
      .map(Number).sort((a, b) => b - a)
      .forEach((lvl) => {
        const label = `Lvl ${lvl} · ${state.tiers[lvl]}`;
        levelFilter.appendChild(new Option(label, lvl));
        levelForm.appendChild(new Option(label, lvl));
      });
  }

  async function loadList() {
    try {
      const data = await A.request('/admin/users?' + buildQuery());
      state.total = data.total;
      renderTable(data.items);
      $('#ticker-total').textContent = data.total;
      $('#ticker-filtered').textContent = data.items.length;
      $('#page-count').textContent = data.items.length;
      $('#page-total').textContent = data.total;
      $('#page-info').textContent = `Page ${state.page + 1} of ${Math.max(1, Math.ceil(data.total / state.limit))}`;
      $('#page-prev').disabled = state.page === 0;
      $('#page-next').disabled = (state.page + 1) * state.limit >= data.total;
      $('#empty-state').style.display = data.items.length === 0 ? '' : 'none';
      data.items.forEach((u) => state.rolesSeen.add(u.role));
      refreshRoleFilter();
    } catch (e) {
      if (e.message.includes('403') || e.message === 'Unauthorized') {
        renderUnauthorized();
      } else {
        toast('err', e.message);
      }
    }
  }

  function renderUnauthorized() {
    $('#users-tbody').innerHTML = '';
    $('#empty-state').style.display = '';
    $('#empty-state').innerHTML =
      'Your account does not have permission to manage users.<br>Contact a Level 3+ supervisor.';
    $('#btn-new-user').disabled = true;
  }

  function refreshRoleFilter() {
    const sel = $('#filter-role');
    const current = sel.value;
    const have = new Set(Array.from(sel.options).map((o) => o.value));
    Array.from(state.rolesSeen).sort().forEach((r) => {
      if (!have.has(r)) sel.appendChild(new Option(r, r));
    });
    sel.value = current;
  }

  // ── Render ─────────────────────────────────────────────────────────
  function tierPill(level) {
    const label = state.tiers[level] || `Lvl ${level}`;
    return `<span class="pill pill--tier-${level}">L${level} · ${label}</span>`;
  }

  function statusPill(u) {
    return u.is_active
      ? `<span class="pill" style="border-color:var(--signal-ok);color:var(--signal-ok)">Active</span>`
      : `<span class="pill pill--inactive">Inactive</span>`;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }

  function renderTable(items) {
    const tbody = $('#users-tbody');
    tbody.innerHTML = '';
    state.pageRows = items.map((u) => ({
      id: u.id,
      label: `${u.full_name} (${u.employee_code})`,
    }));
    items.forEach((u) => {
      const tr = document.createElement('tr');
      tr.dataset.inactive = (!u.is_active).toString();
      const isSelf = callerId != null && u.id === callerId;
      // Self-row: drop from selection if it somehow snuck in via a stale
      // cookie, disable the row checkbox, and disable the per-row Delete.
      // The server still refuses, but the click never reaches it.
      if (isSelf) state.selected.delete(u.id);
      const checked = state.selected.has(u.id) ? 'checked' : '';
      const cbAttrs = isSelf
        ? 'disabled title="You cannot select your own account"'
        : '';
      const deleteBtn = isSelf
        ? `<button class="btn btn--xs" disabled title="You cannot delete your own account" style="color: var(--ink-tertiary); border-color: var(--ink-tertiary); cursor: not-allowed; opacity: 0.55;">Delete</button>`
        : `<button class="btn btn--xs" data-act="purge" data-id="${u.id}" data-name="${escapeHtml(u.full_name)} (${escapeHtml(u.employee_code)})" style="color: var(--signal-crit); border-color: var(--signal-crit);">Delete</button>`;
      tr.innerHTML = `
        <td><input type="checkbox" class="row-select" data-id="${u.id}" data-label="${escapeHtml(u.full_name)} (${escapeHtml(u.employee_code)})" ${checked} ${cbAttrs} /></td>
        <td><strong>${escapeHtml(u.employee_code)}</strong>${isSelf ? ' <span style="font-family:var(--font-mono);font-size:9px;color:var(--ink-tertiary);text-transform:uppercase;letter-spacing:var(--tracking-wide);">· you</span>' : ''}</td>
        <td>${escapeHtml(u.full_name)}<div style="color:var(--ink-tertiary);font-size:10px">${escapeHtml(u.email)}</div></td>
        <td>${tierPill(u.permission_level)}</td>
        <td>${escapeHtml(u.role)}</td>
        <td>${escapeHtml(u.department || '—')}</td>
        <td>${escapeHtml(u.shift || '—')}</td>
        <td>${u.supervisor_id ?? '—'}</td>
        <td>${statusPill(u)}</td>
        <td><div class="row-actions">
          <button class="btn btn--xs" data-act="edit" data-id="${u.id}">Edit</button>
          ${u.is_active
            ? (isSelf
                ? `<button class="btn btn--xs" disabled title="You cannot deactivate your own account" style="color: var(--ink-tertiary); border-color: var(--ink-tertiary); cursor: not-allowed; opacity: 0.55;">Deactivate</button>`
                : `<button class="btn btn--xs" data-act="deactivate" data-id="${u.id}">Deactivate</button>`)
            : `<button class="btn btn--xs" data-act="reactivate" data-id="${u.id}">Reactivate</button>`}
          ${deleteBtn}
        </div></td>`;
      tbody.appendChild(tr);
    });
    refreshSelectionUI();
  }

  // ── Multi-select state (SCO-91/92) ──────────────────────────────────
  // Updates the master checkbox indeterminate/checked state, the count
  // chip, and the toolbar visibility from the current selection set.
  function refreshSelectionUI() {
    const master = $('#select-all');
    // Exclude the caller's own row from "selectable" counts so master goes
    // fully-checked when every *non-self* row is ticked.
    const selectable = state.pageRows.filter((r) => callerId == null || r.id !== callerId);
    const selectedOnPage = selectable.filter((r) => state.selected.has(r.id)).length;
    if (selectable.length === 0) {
      master.checked = false; master.indeterminate = false;
      master.disabled = true;
    } else {
      master.disabled = false;
      if (selectedOnPage === 0) {
        master.checked = false; master.indeterminate = false;
      } else if (selectedOnPage === selectable.length) {
        master.checked = true; master.indeterminate = false;
      } else {
        master.checked = false; master.indeterminate = true;
      }
    }
    const n = state.selected.size;
    $('#bulk-count').textContent = n;
    $('#bulk-toolbar').hidden = n === 0;
  }

  // ── Modal (create / edit) ──────────────────────────────────────────
  // SCO-81: dropdown caches so we don't re-fetch on every modal open
  const orgmeta = { roles: null, departments: null, shifts: null, titles: null };

  async function loadOrgmeta() {
    if (orgmeta.roles && orgmeta.departments && orgmeta.shifts && orgmeta.titles) return;
    try {
      const [roles, depts, shifts, titles] = await Promise.all([
        A.orgmeta.roles(),
        A.orgmeta.departments(),
        A.orgmeta.shifts(),
        A.orgmeta.titles(),
      ]);
      // SCO-97: roles sorted by default_permission_level DESC, tie-break by name.
      // Highest tier (admin/L5) at top so the dropdown matches the org chart.
      orgmeta.roles = roles
        .filter((r) => r.is_active)
        .sort((a, b) => (b.default_permission_level - a.default_permission_level)
                       || a.name.localeCompare(b.name));
      orgmeta.departments = depts.filter((d) => d.is_active);
      orgmeta.shifts = shifts.filter((s) => s.is_active);
      orgmeta.titles = titles.filter((t) => t.is_active);
    } catch (e) {
      console.warn('orgmeta fetch failed', e);
      orgmeta.roles = []; orgmeta.departments = []; orgmeta.shifts = []; orgmeta.titles = [];
    }
  }

  function fillSelect(selEl, items, fmt, currentId) {
    const head = selEl.querySelector('option[value=""]') ||
                 (() => { const o = new Option('— Select —', ''); selEl.insertBefore(o, selEl.firstChild); return o; })();
    selEl.innerHTML = '';
    selEl.appendChild(head);
    items.forEach((it) => {
      const opt = new Option(fmt(it), it.id);
      if (currentId && Number(currentId) === it.id) opt.selected = true;
      selEl.appendChild(opt);
    });
  }

  async function openModal(user) {
    state.editing = user;
    $('#modal-title').textContent = user ? `Edit · ${user.employee_code}` : 'New user';
    $('#form-user-id').value = user?.id || '';
    $('#form-employee_code').value = user?.employee_code || '';
    $('#form-employee_code').disabled = !!user;  // code immutable post-create
    // SCO-96: full_name split → First / Last. Split on the FIRST space so
    // multi-word last names ("De La Cruz") survive prefill. New users get
    // both blank; on save we re-concatenate with a single space.
    const fn = (user?.full_name || '').trim();
    const spaceIdx = fn.indexOf(' ');
    $('#form-first_name').value = spaceIdx === -1 ? fn : fn.slice(0, spaceIdx);
    $('#form-last_name').value  = spaceIdx === -1 ? '' : fn.slice(spaceIdx + 1).trim();
    $('#form-email').value = user?.email || '';

    await loadOrgmeta();
    fillSelect(
      $('#form-role_id'),
      orgmeta.roles,
      (r) => `${r.name} (default L${r.default_permission_level})${r.site_id ? '' : ' · global'}`,
      user?.role_id,
    );
    fillSelect($('#form-department_id'), orgmeta.departments, (d) => d.name, user?.department_id);
    fillSelect($('#form-shift_id'), orgmeta.shifts,
      (s) => `${s.name} · ${(s.start_time || '').slice(0,5)}–${(s.end_time || '').slice(0,5)}`,
      user?.shift_id);
    // SCO-104: Title curated dropdown + Custom Title toggle. If the user
    // already has a custom_title, default the toggle to "custom" mode so the
    // admin sees what's currently set; otherwise show the dropdown.
    fillSelect($('#form-title_id'), orgmeta.titles,
      (t) => `${t.name}${t.site_id ? '' : ' · global'}`, user?.title_id);
    const customToggle = $('#form-title-custom-toggle');
    const customInput  = $('#form-custom_title');
    const titleSelect  = $('#form-title_id');
    const hasCustom = !!(user?.custom_title);
    customToggle.checked = hasCustom;
    customInput.value = user?.custom_title || '';
    customInput.hidden = !hasCustom;
    titleSelect.hidden = hasCustom;

    $('#form-permission_level').value = user?.permission_level || 1;
    $('#form-password').value = '';
    $('#form-password-row').style.display = user ? 'none' : '';
    $('#form-password').required = !user;
    populateSupervisors(user);
    $('#modal-backdrop').dataset.open = 'true';
  }

  // SCO-81: when role changes, auto-fill permission_level from the role's
  // default. The user can still manually override afterwards (interim
  // leadership) — change handler doesn't re-fire on permission_level edits.
  document.addEventListener('change', (e) => {
    if (e.target && e.target.id === 'form-role_id') {
      const roleId = Number(e.target.value);
      if (!roleId || !orgmeta.roles) return;
      const role = orgmeta.roles.find((r) => r.id === roleId);
      if (role) $('#form-permission_level').value = role.default_permission_level;
    }
    // SCO-104: swap between curated dropdown and free-text input. Mutual
    // exclusion is enforced at the UI; the inactive control is hidden AND
    // its value cleared at submit time so the backend gets a clean payload.
    if (e.target && e.target.id === 'form-title-custom-toggle') {
      const useCustom = e.target.checked;
      $('#form-title_id').hidden = useCustom;
      $('#form-custom_title').hidden = !useCustom;
      if (useCustom) $('#form-title_id').value = '';
      else $('#form-custom_title').value = '';
    }
  });

  function closeModal() {
    $('#modal-backdrop').dataset.open = 'false';
    state.editing = null;
  }

  async function populateSupervisors(user) {
    const sel = $('#form-supervisor_id');
    sel.innerHTML = '<option value="">— None —</option>';
    try {
      // Fetch potential supervisors: anyone at a higher tier than the target.
      const targetLevel = Number($('#form-permission_level').value) || 1;
      const data = await A.request(`/admin/users?level_min=${targetLevel + 1}&limit=200`);
      data.items.forEach((s) => {
        if (user && s.id === user.id) return; // can't supervise self
        const o = new Option(`${s.employee_code} · ${s.full_name} (L${s.permission_level})`, s.id);
        if (user && user.supervisor_id === s.id) o.selected = true;
        sel.appendChild(o);
      });
    } catch {
      // Non-fatal; user can still save without supervisor.
    }
  }

  // Re-fetch supervisor list whenever target's level changes (the eligibility set shifts)
  $('#form-permission_level').addEventListener('change', () => populateSupervisors(state.editing));

  $('#user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = state.editing;
    // SCO-81: dropdowns now drive the FK ids; legacy string fields are no
    // longer collected from the form. The backend backfills strings from
    // the linked entities (SCO-80).
    const roleId = $('#form-role_id').value;
    const deptId = $('#form-department_id').value;
    const shiftId = $('#form-shift_id').value;
    const useCustomTitle = $('#form-title-custom-toggle').checked;
    const titleId = $('#form-title_id').value;
    const customTitle = $('#form-custom_title').value.trim();
    const firstName = $('#form-first_name').value.trim();
    const lastName  = $('#form-last_name').value.trim();
    const body = {
      // SCO-96: backend still takes a single `full_name` column.
      full_name: `${firstName} ${lastName}`.trim().replace(/\s+/g, ' '),
      email: $('#form-email').value.trim(),
      permission_level: Number($('#form-permission_level').value),
      role_id: roleId ? Number(roleId) : null,
      department_id: deptId ? Number(deptId) : null,
      shift_id: shiftId ? Number(shiftId) : null,
      // SCO-104: send exactly one of (title_id, custom_title); other is null.
      title_id: useCustomTitle ? null : (titleId ? Number(titleId) : null),
      custom_title: useCustomTitle ? (customTitle || null) : null,
    };
    const supId = $('#form-supervisor_id').value;
    const supervisorId = supId ? Number(supId) : null;

    try {
      let saved;
      if (u) {
        saved = await A.request(`/admin/users/${u.id}`, { method: 'PUT', body });
      } else {
        const createBody = { ...body,
          employee_code: $('#form-employee_code').value.trim(),
          password: $('#form-password').value };
        saved = await A.request('/admin/users', { method: 'POST', body: createBody });
      }
      // Only call the supervisor endpoint if the value actually changed
      if ((u?.supervisor_id ?? null) !== supervisorId) {
        await A.request(`/admin/users/${saved.id}/supervisor`,
          { method: 'PUT', body: { supervisor_id: supervisorId } });
      }
      toast('ok', u ? 'User updated' : 'User created');
      closeModal();
      loadList();
    } catch (err) {
      toast('err', err.message);
    }
  });

  // ── Row actions ────────────────────────────────────────────────────
  $('#users-tbody').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const act = btn.dataset.act;
    try {
      if (act === 'edit') {
        const user = await A.request(`/admin/users/${id}`);
        openModal(user);
      } else if (act === 'deactivate') {
        if (!confirm('Deactivate this user? Their history is preserved.')) return;
        await A.request(`/admin/users/${id}`, { method: 'DELETE' });
        toast('ok', 'User deactivated');
        loadList();
      } else if (act === 'reactivate') {
        await A.request(`/admin/users/${id}/reactivate`, { method: 'POST', body: {} });
        toast('ok', 'User reactivated');
        loadList();
      } else if (act === 'purge') {
        openPurgeModal(id, btn.dataset.name || `user #${id}`);
      }
    } catch (err) {
      toast('err', err.message);
    }
  });

  // ── Row checkbox + master-select (SCO-91) ──────────────────────────
  $('#users-tbody').addEventListener('change', (e) => {
    const cb = e.target.closest('input.row-select');
    if (!cb) return;
    const id = Number(cb.dataset.id);
    if (cb.checked) state.selected.set(id, cb.dataset.label || `#${id}`);
    else state.selected.delete(id);
    refreshSelectionUI();
  });

  $('#select-all').addEventListener('change', (e) => {
    const checked = e.target.checked;
    state.pageRows.forEach((r) => {
      // Never include the caller in a "select all" sweep — backend would
      // 207 with cannot_delete_self, but easier to never offer the option.
      if (callerId != null && r.id === callerId) return;
      if (checked) state.selected.set(r.id, r.label);
      else state.selected.delete(r.id);
    });
    // Re-tick the visible row checkboxes; selection lives in state.selected.
    // The self-row's checkbox is rendered disabled, so .checked stays false.
    $$('#users-tbody input.row-select').forEach((cb) => {
      if (cb.disabled) return;
      cb.checked = checked;
    });
    refreshSelectionUI();
  });

  $('#bulk-clear').addEventListener('click', () => {
    state.selected.clear();
    $$('#users-tbody input.row-select').forEach((cb) => { cb.checked = false; });
    refreshSelectionUI();
  });

  $('#bulk-delete').addEventListener('click', () => {
    if (state.selected.size === 0) return;
    openBulkPurgeModal();
  });

  // ── Purge (hard-delete) modal — typed DELETE required ──────────────
  // Dual-mode: single-target (existing per-row "Delete" button) or bulk
  // (the toolbar "Delete selected" button). `purgeState.mode` switches
  // the confirm handler between POST /{id}/purge and POST /bulk-purge.
  const purgeState = { mode: 'single', id: null, ids: [] };
  const purgeBackdrop = $('#purge-backdrop');
  const purgeInput = $('#purge-confirm-input');
  const purgeBtn = $('#purge-confirm');
  const purgeErr = $('#purge-error');
  const purgeTitle = $('#purge-modal-title');
  const purgeBody = $('#purge-modal-body');
  const purgeBodyDefault = purgeBody.innerHTML; // preserve single-mode copy
  const bulkFailedPanel = $('#bulk-failed-panel');
  const bulkFailedList = $('#bulk-failed-list');

  function openPurgeModal(id, name) {
    purgeState.mode = 'single';
    purgeState.id = id;
    purgeState.ids = [];
    purgeTitle.textContent = 'Permanently delete user?';
    purgeBody.innerHTML = purgeBodyDefault;
    $('#purge-target-name').textContent = name;
    bulkFailedPanel.hidden = true;
    bulkFailedList.innerHTML = '';
    purgeInput.value = '';
    purgeErr.style.display = 'none';
    purgeBtn.textContent = 'Delete forever';
    purgeBtn.disabled = true;
    purgeBtn.style.opacity = '0.5';
    purgeBtn.style.cursor = 'not-allowed';
    purgeBackdrop.dataset.open = 'true';
    setTimeout(() => purgeInput.focus(), 30);
  }

  function openBulkPurgeModal() {
    const ids = Array.from(state.selected.keys());
    purgeState.mode = 'bulk';
    purgeState.id = null;
    purgeState.ids = ids;
    purgeTitle.textContent = `Permanently delete ${ids.length} users?`;
    // Show up to 8 labels then a "+N more" tail, so the modal stays bounded
    // even if the user has selected 200.
    const labels = Array.from(state.selected.values());
    const shown = labels.slice(0, 8).map((l) => `<li>${escapeHtml(l)}</li>`).join('');
    const more = labels.length > 8 ? `<li style="color:var(--ink-tertiary)">+ ${labels.length - 8} more</li>` : '';
    purgeBody.innerHTML = `
      This will <strong style="color: var(--ink-primary);">irreversibly remove</strong> the following users from the system.
      Their audit history is preserved (anonymized), but the user records themselves are gone.
      Per-row safety rails (last-admin protection, hierarchy, active subordinates) are still enforced by the server.
      <ul style="margin: var(--space-3) 0 0; padding-left: 18px; font-family: var(--font-mono); font-size: 12px; color: var(--ink-secondary); line-height: 1.6; max-height: 180px; overflow-y: auto;">${shown}${more}</ul>`;
    bulkFailedPanel.hidden = true;
    bulkFailedList.innerHTML = '';
    purgeInput.value = '';
    purgeErr.style.display = 'none';
    purgeBtn.textContent = `Delete ${ids.length} forever`;
    purgeBtn.disabled = true;
    purgeBtn.style.opacity = '0.5';
    purgeBtn.style.cursor = 'not-allowed';
    purgeBackdrop.dataset.open = 'true';
    setTimeout(() => purgeInput.focus(), 30);
  }

  function closePurgeModal() {
    purgeBackdrop.dataset.open = 'false';
    purgeState.id = null;
    purgeState.ids = [];
    purgeInput.value = '';
  }

  purgeInput.addEventListener('input', () => {
    const armed = purgeInput.value === 'DELETE';
    purgeBtn.disabled = !armed;
    purgeBtn.style.opacity = armed ? '1' : '0.5';
    purgeBtn.style.cursor = armed ? 'pointer' : 'not-allowed';
    purgeErr.style.display = 'none';
  });

  $('#purge-cancel').addEventListener('click', closePurgeModal);
  purgeBackdrop.addEventListener('click', (e) => {
    if (e.target.id === 'purge-backdrop') closePurgeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && purgeBackdrop.dataset.open === 'true') closePurgeModal();
  });

  // Friendly labels for backend failure reasons in bulk responses.
  const BULK_REASONS = {
    not_found: 'User no longer exists',
    cannot_delete_self: 'You cannot delete yourself',
    hierarchy_violation: 'Target outranks (or matches) your level',
    last_admin_protection: 'Last Level-5 admin — promote another first',
    has_subordinates: 'Has active subordinates — reassign them first',
    conflict: 'Conflict (see audit log)',
  };

  purgeBtn.addEventListener('click', async () => {
    if (purgeInput.value !== 'DELETE') return;
    purgeBtn.disabled = true;
    const originalLabel = purgeBtn.textContent;
    purgeBtn.textContent = 'Deleting…';
    try {
      if (purgeState.mode === 'single') {
        if (!purgeState.id) return;
        await A.request(`/admin/users/${purgeState.id}/purge`, { method: 'POST', body: {} });
        toast('ok', 'User permanently deleted');
        closePurgeModal();
        loadList();
      } else {
        const ids = purgeState.ids;
        if (!ids.length) return;
        const resp = await A.request('/admin/users/bulk-purge', {
          method: 'POST', body: { user_ids: ids },
        });
        const ok = resp.purged.length;
        const fail = resp.failed.length;
        // Drop succeeded ids from selection so a repeat click only retries failures.
        resp.purged.forEach((id) => state.selected.delete(id));
        if (fail === 0) {
          toast('ok', `${ok}/${resp.requested} users permanently deleted`);
          closePurgeModal();
        } else {
          // Keep the modal open so the user can read the per-row reasons.
          // The label-to-id map lets us show names instead of opaque ids.
          const labelFor = (id) => state.selected.get(id) || `#${id}`;
          bulkFailedList.innerHTML = resp.failed
            .map((f) => `<li><strong>${escapeHtml(labelFor(f.user_id))}</strong> · ${BULK_REASONS[f.reason] || f.reason}</li>`)
            .join('');
          bulkFailedPanel.hidden = false;
          purgeErr.textContent = `${ok}/${resp.requested} deleted, ${fail} failed`;
          purgeErr.style.display = 'block';
          purgeInput.value = '';
          purgeBtn.textContent = `Retry ${state.selected.size} remaining`;
        }
        loadList();
        refreshSelectionUI();
      }
    } catch (err) {
      purgeErr.textContent = err.message;
      purgeErr.style.display = 'block';
      purgeBtn.disabled = false;
      purgeBtn.textContent = originalLabel;
    }
  });

  // ── Toolbar wiring ────────────────────────────────────────────────
  let searchDebounce;
  $('#filter-search').addEventListener('input', (e) => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      state.filters.q = e.target.value.trim();
      state.page = 0;
      loadList();
    }, 250);
  });
  $('#filter-role').addEventListener('change', (e) => {
    state.filters.role = e.target.value;
    state.page = 0;
    loadList();
  });
  $('#filter-level').addEventListener('change', (e) => {
    state.filters.level = e.target.value;
    state.page = 0;
    loadList();
  });
  $('#filter-inactive').addEventListener('change', (e) => {
    state.filters.include_inactive = e.target.checked;
    state.page = 0;
    loadList();
  });
  $('#page-prev').addEventListener('click', () => { if (state.page > 0) { state.page--; loadList(); } });
  $('#page-next').addEventListener('click', () => {
    if ((state.page + 1) * state.limit < state.total) { state.page++; loadList(); }
  });
  $('#btn-new-user').addEventListener('click', () => openModal(null));
  $('#modal-cancel').addEventListener('click', closeModal);
  $('#modal-backdrop').addEventListener('click', (e) => {
    if (e.target.id === 'modal-backdrop') closeModal();
  });

  // ── Boot ───────────────────────────────────────────────────────────
  await loadTiers();
  await loadList();
})();
