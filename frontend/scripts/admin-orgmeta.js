/* ═══════════════════════════════════════════════════════════════════════════
   Admin · Org Metadata — Roles / Titles / Departments / Shifts CRUD
   ─────────────────────────────────────────────────────────────────────────
   Drives /admin/{roles,titles,departments,shifts} curation. The lists here
   populate the pickers in users.html user-create form.

   SCO-100: Titles card added.
   SCO-107/109: hard-delete (/purge) buttons added to every row, alongside the
   existing soft-disable. The server returns 409 + ref_count when in use; we
   surface that as a toast so the admin knows whether to disable instead.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';
  if (!window.WMS_API || !WMS_API.isAuthed()) return;

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const toastEl = $('#toast');

  // SCO-115: caller identity + site picker state. callerIsMCS gates the
  // page-wide "Viewing site" filter and the per-form Target-site rows.
  // siteState.target = current site for both list-reads and form-writes.
  // For non-MCS callers it locks to their own site; MCS can switch freely.
  let callerSiteId = null;
  let callerIsMCS = false;
  let allSites = [];
  const siteState = { target: null };

  function toast(kind, msg) {
    toastEl.textContent = msg;
    toastEl.style.borderColor = kind === 'err' ? 'var(--signal-crit)' : 'var(--signal-ok)';
    toastEl.style.color = kind === 'err' ? 'var(--signal-crit)' : 'var(--signal-ok)';
    toastEl.style.background = kind === 'err' ? 'rgba(239,68,68,0.08)' : 'rgba(74,222,128,0.08)';
    toastEl.style.display = 'block';
    setTimeout(() => { toastEl.style.display = 'none'; }, 3000);
  }

  function fmtTime(t) { return (t || '').slice(0, 5); }

  /**
   * Friendly error surface for /purge calls. Server returns 409 with a
   * structured detail body {detail, ref_count, entity} when the entity is in
   * use. WMS_API throws an Error with that body stringified — we parse it back
   * out so the toast reads "Title 'Supervisor' is in use by 3 users; disable
   * instead" rather than a raw JSON blob.
   */
  function purgeErrorMessage(err, entityName) {
    const msg = err && err.message ? err.message : '';
    const m = msg.match(/ref_count['"\s:]+(\d+)/);
    if (m) {
      const n = Number(m[1]);
      return `"${entityName}" is in use by ${n} user${n === 1 ? '' : 's'}; disable instead`;
    }
    return msg || 'Delete failed';
  }

  // SCO-112: typed-DELETE in-app modal. Native confirm()/prompt() are banned
  // in this codebase — Chrome's "block additional dialogs" footgun silently
  // breaks subsequent ops. See feedback_no_native_browser_popups.md.
  function confirmHardDelete(label) {
    return confirmModal.typed({
      title: `Permanently delete "${label}"?`,
      body: 'This cannot be undone. If any user references it, the server will refuse.',
      confirmWord: 'DELETE',
      confirmLabel: 'Delete forever',
    });
  }

  // ── ROLES ─────────────────────────────────────────────────────────────

  async function renderRoles() {
    try {
      // MCS: scope list to selected target site. Non-MCS: server defaults to
      // own site + globals (no params needed).
      const params = callerIsMCS ? { site_id: siteState.target } : {};
      const roles = await WMS_API.orgmeta.roles(params);
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
          <span class="om-actions">
            ${r.is_active ? `<button class="btn btn--xs" data-act="role-disable" data-id="${r.id}" data-name="${r.name}">Disable</button>` : ''}
            <button class="btn btn--xs btn--danger" data-act="role-purge" data-id="${r.id}" data-name="${r.name}" title="Hard delete (refuses if in use)">Delete</button>
          </span>
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
      site_id: siteIdForCreate({ scope }),
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
    const disableBtn = e.target.closest('[data-act="role-disable"]');
    const purgeBtn = e.target.closest('[data-act="role-purge"]');
    if (disableBtn) {
      if (!(await confirmModal.simple({
        title: 'Disable this role?',
        body: 'Existing users keep the role, but it disappears from the dropdown. Reactivate any time.',
        confirmLabel: 'Disable',
      }))) return;
      try {
        await WMS_API.orgmeta.deactivateRole(Number(disableBtn.dataset.id));
        toast('ok', 'Role disabled');
        renderRoles();
      } catch (err) { toast('err', err.message); }
    } else if (purgeBtn) {
      const name = purgeBtn.dataset.name;
      if (!(await confirmHardDelete(name))) return;
      try {
        await WMS_API.orgmeta.purgeRole(Number(purgeBtn.dataset.id));
        toast('ok', `Role "${name}" deleted`);
        renderRoles();
      } catch (err) { toast('err', purgeErrorMessage(err, name)); }
    }
  });

  // ── TITLES (SCO-100) ──────────────────────────────────────────────────

  async function renderTitles() {
    try {
      const params = callerIsMCS ? { site_id: siteState.target } : {};
      const titles = await WMS_API.orgmeta.titles(params);
      const list = $('#titles-list');
      list.innerHTML = '';
      const globals = titles.filter((t) => t.site_id === null);
      const siteSpecific = titles.filter((t) => t.site_id !== null);
      $('#titles-meta').textContent =
        `${globals.length} global · ${siteSpecific.length} site-specific`;
      if (!titles.length) {
        list.innerHTML = '<li class="om-empty">No titles defined.</li>';
        return;
      }
      // Active first, deactivated below.
      titles.sort((a, b) => (b.is_active - a.is_active) || a.name.localeCompare(b.name));
      for (const t of titles) {
        const li = document.createElement('li');
        const scope = t.site_id ? `site ${t.site_id}` : 'global';
        li.innerHTML = `
          <span>
            <strong>${t.name}</strong>
            <span style="color:var(--ink-tertiary);margin-left:6px">${scope}</span>
            ${t.is_active ? '' : '<span style="color:var(--signal-crit);margin-left:6px">(disabled)</span>'}
          </span>
          <span class="om-actions">
            ${t.is_active ? `<button class="btn btn--xs" data-act="title-disable" data-id="${t.id}" data-name="${t.name}">Disable</button>` : ''}
            <button class="btn btn--xs btn--danger" data-act="title-purge" data-id="${t.id}" data-name="${t.name}" title="Hard delete (refuses if in use)">Delete</button>
          </span>
        `;
        list.appendChild(li);
      }
    } catch (e) {
      toast('err', `Titles: ${e.message}`);
    }
  }

  $('#title-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const scope = $('#title-scope').value;
    const payload = {
      name: $('#title-name').value.trim(),
      site_id: siteIdForCreate({ scope }),
    };
    try {
      await WMS_API.orgmeta.createTitle(payload);
      toast('ok', `Title "${payload.name}" added`);
      $('#title-name').value = '';
      renderTitles();
    } catch (err) {
      toast('err', err.message);
    }
  });

  $('#titles-list').addEventListener('click', async (e) => {
    const disableBtn = e.target.closest('[data-act="title-disable"]');
    const purgeBtn = e.target.closest('[data-act="title-purge"]');
    if (disableBtn) {
      if (!(await confirmModal.simple({
        title: 'Disable this title?',
        body: 'Existing users keep the title, but it disappears from the dropdown. Reactivate any time.',
        confirmLabel: 'Disable',
      }))) return;
      try {
        await WMS_API.orgmeta.deactivateTitle(Number(disableBtn.dataset.id));
        toast('ok', 'Title disabled');
        renderTitles();
      } catch (err) { toast('err', err.message); }
    } else if (purgeBtn) {
      const name = purgeBtn.dataset.name;
      if (!(await confirmHardDelete(name))) return;
      try {
        await WMS_API.orgmeta.purgeTitle(Number(purgeBtn.dataset.id));
        toast('ok', `Title "${name}" deleted`);
        renderTitles();
      } catch (err) { toast('err', purgeErrorMessage(err, name)); }
    }
  });

  // ── DEPARTMENTS ───────────────────────────────────────────────────────

  async function renderDepts() {
    try {
      const depts = await WMS_API.orgmeta.departments(callerIsMCS ? siteState.target : undefined);
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
          <span class="om-actions">
            ${d.is_active ? `<button class="btn btn--xs" data-act="dept-disable" data-id="${d.id}">Disable</button>` : ''}
            <button class="btn btn--xs btn--danger" data-act="dept-purge" data-id="${d.id}" data-name="${d.name}" title="Hard delete (refuses if in use)">Delete</button>
          </span>
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
    const payload = { name };
    const sid = siteIdForCreate();
    if (sid !== undefined) payload.site_id = sid;
    try {
      await WMS_API.orgmeta.createDepartment(payload);
      toast('ok', `Department "${name}" added`);
      $('#dept-name').value = '';
      renderDepts();
    } catch (err) { toast('err', err.message); }
  });

  $('#depts-list').addEventListener('click', async (e) => {
    const disableBtn = e.target.closest('[data-act="dept-disable"]');
    const purgeBtn = e.target.closest('[data-act="dept-purge"]');
    if (disableBtn) {
      if (!(await confirmModal.simple({
        title: 'Disable this department?',
        body: 'Existing users keep the department, but it disappears from the dropdown. Reactivate any time.',
        confirmLabel: 'Disable',
      }))) return;
      try {
        await WMS_API.orgmeta.deactivateDepartment(Number(disableBtn.dataset.id));
        renderDepts();
      } catch (err) { toast('err', err.message); }
    } else if (purgeBtn) {
      const name = purgeBtn.dataset.name;
      if (!(await confirmHardDelete(name))) return;
      try {
        await WMS_API.orgmeta.purgeDepartment(Number(purgeBtn.dataset.id));
        toast('ok', `Department "${name}" deleted`);
        renderDepts();
      } catch (err) { toast('err', purgeErrorMessage(err, name)); }
    }
  });

  // ── SHIFTS ────────────────────────────────────────────────────────────

  async function renderShifts() {
    try {
      const shifts = await WMS_API.orgmeta.shifts(callerIsMCS ? siteState.target : undefined);
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
          <span class="om-actions">
            ${s.is_active ? `<button class="btn btn--xs" data-act="shift-disable" data-id="${s.id}">Disable</button>` : ''}
            <button class="btn btn--xs btn--danger" data-act="shift-purge" data-id="${s.id}" data-name="${s.name}" title="Hard delete (refuses if in use)">Delete</button>
          </span>
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
    const sid = siteIdForCreate();
    if (sid !== undefined) payload.site_id = sid;
    try {
      await WMS_API.orgmeta.createShift(payload);
      toast('ok', `Shift "${payload.name}" added`);
      $('#shift-name').value = '';
      $('#shift-start').value = '';
      $('#shift-end').value = '';
      renderShifts();
    } catch (err) { toast('err', err.message); }
  });

  $('#shifts-list').addEventListener('click', async (e) => {
    const disableBtn = e.target.closest('[data-act="shift-disable"]');
    const purgeBtn = e.target.closest('[data-act="shift-purge"]');
    if (disableBtn) {
      if (!(await confirmModal.simple({
        title: 'Disable this shift?',
        body: 'Existing users keep the shift, but it disappears from the dropdown. Reactivate any time.',
        confirmLabel: 'Disable',
      }))) return;
      try {
        await WMS_API.orgmeta.deactivateShift(Number(disableBtn.dataset.id));
        renderShifts();
      } catch (err) { toast('err', err.message); }
    } else if (purgeBtn) {
      const name = purgeBtn.dataset.name;
      if (!(await confirmHardDelete(name))) return;
      try {
        await WMS_API.orgmeta.purgeShift(Number(purgeBtn.dataset.id));
        toast('ok', `Shift "${name}" deleted`);
        renderShifts();
      } catch (err) { toast('err', purgeErrorMessage(err, name)); }
    }
  });

  // ── SCO-115: caller + sites bootstrap ─────────────────────────────────

  async function bootSiteContext() {
    try {
      const me = await WMS_API.me();
      callerSiteId = me.site_id;
      // MCS Lvl4+ unlocks cross-site authoring. Same gate the backend uses.
      callerIsMCS = (me.site_id === 'MCS' && (me.permission_level || 0) >= 4);
      siteState.target = callerSiteId;
    } catch (e) {
      toast('err', `Auth check failed: ${e.message}`);
      return;
    }

    if (!callerIsMCS) {
      // Non-MCS: keep the UI exactly as before. Lists scoped to own site by
      // backend default; forms send no site_id (server fills caller's site).
      renderAll();
      return;
    }

    // MCS path: fetch site list, wire the page filter + per-form pickers.
    try {
      allSites = await WMS_API.sites();
      if (!allSites.find((s) => s.id === callerSiteId)) {
        allSites.unshift({ id: callerSiteId, name: callerSiteId });
      }
    } catch (e) {
      toast('err', `Sites load failed: ${e.message}`);
      allSites = [{ id: callerSiteId, name: 'MCS' }];
    }

    const filterRow = $('#om-site-filter-row');
    const filterSel = $('#om-site-filter');
    filterRow.hidden = false;
    filterSel.innerHTML = allSites
      .map((s) => `<option value="${s.id}">${s.id} — ${s.name}</option>`)
      .join('');
    filterSel.value = callerSiteId;
    filterSel.addEventListener('change', () => {
      siteState.target = filterSel.value;
      syncSitePickers();
      renderAll();
    });

    // Per-form Target-site pickers: same population, all driven by siteState.
    $$('[data-om-site-target]').forEach((sel) => {
      sel.innerHTML = allSites
        .map((s) => `<option value="${s.id}">${s.id} — ${s.name}</option>`)
        .join('');
      sel.closest('.om-site-row').hidden = false;
    });
    syncSitePickers();
    renderAll();
  }

  function syncSitePickers() {
    $$('[data-om-site-target]').forEach((sel) => { sel.value = siteState.target; });
  }

  // For Roles/Titles: scope=global → null; scope=site → explicit site_id.
  // For Departments/Shifts: always explicit site_id (or undefined → server
  // defaults to caller's site for non-MCS callers).
  function siteIdForCreate(opts = {}) {
    if (opts.scope === 'global') return null;
    if (!callerIsMCS) return undefined;  // server fills caller.site_id
    return siteState.target;
  }

  function renderAll() {
    renderRoles();
    renderTitles();
    renderDepts();
    renderShifts();
  }

  // ── Boot ──────────────────────────────────────────────────────────────
  bootSiteContext();
})();
