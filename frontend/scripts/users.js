/* ═══════════════════════════════════════════════════════════════════════════
   WMS · Admin · User Management page
   ═══════════════════════════════════════════════════════════════════════════ */

(async () => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    window.location.href = 'login.html';
    return;
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
    items.forEach((u) => {
      const tr = document.createElement('tr');
      tr.dataset.inactive = (!u.is_active).toString();
      tr.innerHTML = `
        <td><strong>${escapeHtml(u.employee_code)}</strong></td>
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
            ? `<button class="btn btn--xs" data-act="deactivate" data-id="${u.id}">Deactivate</button>`
            : `<button class="btn btn--xs" data-act="reactivate" data-id="${u.id}">Reactivate</button>`}
          <button class="btn btn--xs" data-act="purge" data-id="${u.id}" data-name="${escapeHtml(u.full_name)} (${escapeHtml(u.employee_code)})" style="color: var(--signal-crit); border-color: var(--signal-crit);">Delete</button>
        </div></td>`;
      tbody.appendChild(tr);
    });
  }

  // ── Modal (create / edit) ──────────────────────────────────────────
  // SCO-81: dropdown caches so we don't re-fetch on every modal open
  const orgmeta = { roles: null, departments: null, shifts: null };

  async function loadOrgmeta() {
    if (orgmeta.roles && orgmeta.departments && orgmeta.shifts) return;
    try {
      const [roles, depts, shifts] = await Promise.all([
        A.orgmeta.roles(),
        A.orgmeta.departments(),
        A.orgmeta.shifts(),
      ]);
      orgmeta.roles = roles.filter((r) => r.is_active);
      orgmeta.departments = depts.filter((d) => d.is_active);
      orgmeta.shifts = shifts.filter((s) => s.is_active);
    } catch (e) {
      console.warn('orgmeta fetch failed', e);
      orgmeta.roles = []; orgmeta.departments = []; orgmeta.shifts = [];
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
    $('#form-full_name').value = user?.full_name || '';
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
    const body = {
      full_name: $('#form-full_name').value.trim(),
      email: $('#form-email').value.trim(),
      permission_level: Number($('#form-permission_level').value),
      role_id: roleId ? Number(roleId) : null,
      department_id: deptId ? Number(deptId) : null,
      shift_id: shiftId ? Number(shiftId) : null,
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

  // ── Purge (hard-delete) modal — typed DELETE required ──────────────
  const purgeState = { id: null };
  const purgeBackdrop = $('#purge-backdrop');
  const purgeInput = $('#purge-confirm-input');
  const purgeBtn = $('#purge-confirm');
  const purgeErr = $('#purge-error');

  function openPurgeModal(id, name) {
    purgeState.id = id;
    $('#purge-target-name').textContent = name;
    purgeInput.value = '';
    purgeErr.style.display = 'none';
    purgeBtn.disabled = true;
    purgeBtn.style.opacity = '0.5';
    purgeBtn.style.cursor = 'not-allowed';
    purgeBackdrop.dataset.open = 'true';
    setTimeout(() => purgeInput.focus(), 30);
  }

  function closePurgeModal() {
    purgeBackdrop.dataset.open = 'false';
    purgeState.id = null;
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

  purgeBtn.addEventListener('click', async () => {
    if (purgeInput.value !== 'DELETE' || !purgeState.id) return;
    const id = purgeState.id;
    purgeBtn.disabled = true;
    purgeBtn.textContent = 'Deleting…';
    try {
      await A.request(`/admin/users/${id}/purge`, { method: 'POST', body: {} });
      toast('ok', 'User permanently deleted');
      closePurgeModal();
      loadList();
    } catch (err) {
      purgeErr.textContent = err.message;
      purgeErr.style.display = 'block';
      purgeBtn.disabled = false;
    } finally {
      purgeBtn.textContent = 'Delete forever';
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
