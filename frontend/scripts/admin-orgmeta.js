/* ═══════════════════════════════════════════════════════════════════════════
   Admin · Org Metadata — Roles / Departments / Shifts CRUD (SCO-81)
   ─────────────────────────────────────────────────────────────────────────
   Drives /admin/roles, /admin/departments, /admin/shifts curation. The lists
   here populate the pickers in users.html user-create form.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';
  if (!window.WMS_API || !WMS_API.isAuthed()) return;

  const $ = (s) => document.querySelector(s);
  const toastEl = $('#toast');

  function toast(kind, msg) {
    toastEl.textContent = msg;
    toastEl.style.borderColor = kind === 'err' ? 'var(--signal-crit)' : 'var(--signal-ok)';
    toastEl.style.color = kind === 'err' ? 'var(--signal-crit)' : 'var(--signal-ok)';
    toastEl.style.background = kind === 'err' ? 'rgba(239,68,68,0.08)' : 'rgba(74,222,128,0.08)';
    toastEl.style.display = 'block';
    setTimeout(() => { toastEl.style.display = 'none'; }, 2500);
  }

  function fmtTime(t) {
    return (t || '').slice(0, 5);
  }

  // ── ROLES ─────────────────────────────────────────────────────────────

  async function renderRoles() {
    try {
      const roles = await WMS_API.orgmeta.roles();
      const list = $('#roles-list');
      list.innerHTML = '';
      const globals = roles.filter((r) => r.site_id === null);
      const siteSpecific = roles.filter((r) => r.site_id !== null);
      $('#roles-meta').textContent =
        `${globals.length} global · ${siteSpecific.length} site-specific`;
      if (!roles.length) {
        list.innerHTML = '<li class="om-empty">No roles defined.</li>';
        return;
      }
      for (const r of roles) {
        const li = document.createElement('li');
        const scope = r.site_id ? `site ${r.site_id}` : 'global';
        li.innerHTML = `
          <span>
            <strong>${r.name}</strong>
            <span style="color:var(--ink-tertiary);margin-left:6px">L${r.default_permission_level} · ${scope}</span>
            ${r.is_active ? '' : '<span style="color:var(--signal-crit);margin-left:6px">(disabled)</span>'}
          </span>
          ${r.is_active ? `<button class="btn btn--xs" data-act="role-disable" data-id="${r.id}">Disable</button>` : ''}
        `;
        list.appendChild(li);
      }
    } catch (e) {
      toast('err', `Roles: ${e.message}`);
    }
  }

  $('#role-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const scope = $('#role-scope').value;
    const payload = {
      name: $('#role-name').value.trim(),
      default_permission_level: Number($('#role-level').value),
      site_id: scope === 'global' ? null : undefined,  // undefined → server picks caller's site
    };
    try {
      await WMS_API.orgmeta.createRole(payload);
      toast('ok', `Role "${payload.name}" added`);
      $('#role-name').value = '';
      renderRoles();
    } catch (err) {
      toast('err', err.message);
    }
  });

  $('#roles-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act="role-disable"]');
    if (!btn) return;
    if (!confirm('Disable this role?')) return;
    try {
      await WMS_API.orgmeta.deactivateRole(Number(btn.dataset.id));
      toast('ok', 'Role disabled');
      renderRoles();
    } catch (err) {
      toast('err', err.message);
    }
  });

  // ── DEPARTMENTS ───────────────────────────────────────────────────────

  async function renderDepts() {
    try {
      const depts = await WMS_API.orgmeta.departments();
      const list = $('#depts-list');
      list.innerHTML = '';
      if (!depts.length) {
        list.innerHTML = '<li class="om-empty">No departments defined.</li>';
        return;
      }
      for (const d of depts) {
        const li = document.createElement('li');
        li.innerHTML = `
          <span><strong>${d.name}</strong>${d.is_active ? '' : ' <span style="color:var(--signal-crit)">(disabled)</span>'}</span>
          ${d.is_active ? `<button class="btn btn--xs" data-act="dept-disable" data-id="${d.id}">Disable</button>` : ''}
        `;
        list.appendChild(li);
      }
    } catch (e) {
      toast('err', `Depts: ${e.message}`);
    }
  }

  $('#dept-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('#dept-name').value.trim();
    try {
      await WMS_API.orgmeta.createDepartment({ name });
      toast('ok', `Department "${name}" added`);
      $('#dept-name').value = '';
      renderDepts();
    } catch (err) {
      toast('err', err.message);
    }
  });

  $('#depts-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act="dept-disable"]');
    if (!btn) return;
    if (!confirm('Disable this department?')) return;
    try {
      await WMS_API.orgmeta.deactivateDepartment(Number(btn.dataset.id));
      renderDepts();
    } catch (err) {
      toast('err', err.message);
    }
  });

  // ── SHIFTS ────────────────────────────────────────────────────────────

  async function renderShifts() {
    try {
      const shifts = await WMS_API.orgmeta.shifts();
      const list = $('#shifts-list');
      list.innerHTML = '';
      if (!shifts.length) {
        list.innerHTML = '<li class="om-empty">No shifts defined.</li>';
        return;
      }
      for (const s of shifts) {
        const li = document.createElement('li');
        li.innerHTML = `
          <span>
            <strong>${s.name}</strong>
            <span style="color:var(--ink-tertiary);margin-left:6px">${fmtTime(s.start_time)}–${fmtTime(s.end_time)}</span>
            ${s.is_active ? '' : '<span style="color:var(--signal-crit);margin-left:6px">(disabled)</span>'}
          </span>
          ${s.is_active ? `<button class="btn btn--xs" data-act="shift-disable" data-id="${s.id}">Disable</button>` : ''}
        `;
        list.appendChild(li);
      }
    } catch (e) {
      toast('err', `Shifts: ${e.message}`);
    }
  }

  $('#shift-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      name: $('#shift-name').value.trim(),
      start_time: $('#shift-start').value + ':00',
      end_time: $('#shift-end').value + ':00',
    };
    try {
      await WMS_API.orgmeta.createShift(payload);
      toast('ok', `Shift "${payload.name}" added`);
      $('#shift-name').value = '';
      $('#shift-start').value = '';
      $('#shift-end').value = '';
      renderShifts();
    } catch (err) {
      toast('err', err.message);
    }
  });

  $('#shifts-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act="shift-disable"]');
    if (!btn) return;
    if (!confirm('Disable this shift?')) return;
    try {
      await WMS_API.orgmeta.deactivateShift(Number(btn.dataset.id));
      renderShifts();
    } catch (err) {
      toast('err', err.message);
    }
  });

  // ── Boot ──────────────────────────────────────────────────────────────
  renderRoles();
  renderDepts();
  renderShifts();
})();
