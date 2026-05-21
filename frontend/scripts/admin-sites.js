/* ═══════════════════════════════════════════════════════════════════════════
   Admin · Sites — multi-site directory CRUD (SCO-54)
   ─────────────────────────────────────────────────────────────────────────
   Drives /api/v1/sites read-and-write. Write endpoints require the caller to
   be on the master site (server enforces); this UI also hides destructive
   controls when the caller can't use them, so non-master admins get a clean
   read-only view instead of confusing 403s.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';
  if (!window.WMS_API || !WMS_API.isAuthed()) return;

  const $ = (s) => document.querySelector(s);
  const grid = $('#sites-grid');
  const metaEl = $('#sites-meta');
  const gateEl = $('#gate-banner');
  const addSection = $('#add-section');
  const toastEl = $('#toast');

  // Track whether the caller is on the master site. Used to gate UI controls.
  // Server enforces independently; this is for UX clarity, not security.
  let callerCanWrite = false;
  let masterSiteId = null;

  function toast(kind, msg) {
    toastEl.textContent = msg;
    const ok = kind !== 'err';
    toastEl.style.borderColor = ok ? 'var(--signal-ok)' : 'var(--signal-crit)';
    toastEl.style.color = ok ? 'var(--signal-ok)' : 'var(--signal-crit)';
    toastEl.style.background = ok ? 'rgba(74,222,128,0.08)' : 'rgba(239,68,68,0.08)';
    toastEl.style.display = 'block';
    setTimeout(() => { toastEl.style.display = 'none'; }, 2800);
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function siteCard(site, counts) {
    const writable = callerCanWrite && !site.is_master;
    const offlineToggleLabel = site.is_online ? 'Take offline' : 'Bring online';
    const usersStr = counts ? `${counts.user_count} users` : '— users';
    const deptsStr = counts ? `${counts.department_count} departments` : '— departments';
    return `
      <article class="site-card" data-master="${site.is_master}" data-online="${site.is_online}">
        <div class="site-card-head">
          <h3 class="site-name">${escapeHtml(site.name)}</h3>
          <span class="site-id">${escapeHtml(site.id)}</span>
        </div>
        <div class="site-tags">
          ${site.is_master ? '<span class="site-tag site-tag--master">Master</span>' : ''}
          <span class="site-tag ${site.is_online ? 'site-tag--online' : 'site-tag--offline'}">
            ${site.is_online ? 'Online' : 'Offline'}
          </span>
          <span class="site-tag">${escapeHtml(site.build_version)}</span>
        </div>
        <div class="site-meta">
          <span class="site-meta-label">City</span><span>${escapeHtml(site.city)}</span>
          <span class="site-meta-label">TZ</span><span>${escapeHtml(counts ? counts.timezone : '')}</span>
        </div>
        <div class="site-counts">
          <span class="site-count"><strong>${counts ? counts.user_count : '—'}</strong> users</span>
          <span class="site-count"><strong>${counts ? counts.department_count : '—'}</strong> departments</span>
        </div>
        <div class="site-actions">
          ${callerCanWrite && !site.is_master ? `<button class="btn btn--ghost btn--xs" data-act="edit" data-id="${escapeHtml(site.id)}">Edit</button>` : ''}
          ${callerCanWrite && !site.is_master ? `<button class="btn btn--ghost btn--xs" data-act="toggle" data-id="${escapeHtml(site.id)}">${offlineToggleLabel}</button>` : ''}
          ${writable ? `<button class="btn btn--ghost btn--xs" data-act="delete" data-id="${escapeHtml(site.id)}" style="color: var(--signal-crit);">Archive</button>` : ''}
        </div>
      </article>
    `;
  }

  async function load() {
    grid.innerHTML = '';
    metaEl.textContent = 'Loading…';
    try {
      const sites = await WMS_API.sites();
      const master = sites.find((s) => s.is_master);
      masterSiteId = master ? master.id : null;
      const me = WMS_API.getUser ? WMS_API.getUser() : null;
      callerCanWrite = Boolean(me && masterSiteId && me.site_id === masterSiteId && (me.permission_level || 0) >= 5);

      gateEl.style.display = callerCanWrite ? 'none' : 'block';
      addSection.hidden = !callerCanWrite;

      // Fetch detail (counts + timezone) in parallel; non-fatal per-card.
      const details = await Promise.all(
        sites.map((s) => WMS_API.sitesAdmin.get(s.id).catch(() => null))
      );
      const onlineCount = sites.filter((s) => s.is_online).length;
      metaEl.textContent = `${sites.length} sites · ${onlineCount} online · master = ${masterSiteId || '—'}`;
      grid.innerHTML = sites.map((s, i) => siteCard(s, details[i])).join('');
    } catch (e) {
      metaEl.textContent = 'Failed to load';
      toast('err', `Sites: ${e.message}`);
    }
  }

  $('#site-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      id: $('#site-id').value.trim().toUpperCase(),
      name: $('#site-name').value.trim(),
      city: $('#site-city').value.trim(),
      timezone: $('#site-tz').value.trim() || 'America/Chicago',
      build_version: $('#site-build').value.trim() || 'v0.1.0',
      is_online: $('#site-online').checked,
      is_master: false,
    };
    try {
      await WMS_API.sitesAdmin.create(payload);
      toast('ok', `Site "${payload.id}" created`);
      ['site-id', 'site-name', 'site-city'].forEach((id) => { $('#' + id).value = ''; });
      load();
    } catch (err) {
      toast('err', err.message);
    }
  });

  grid.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    try {
      if (act === 'toggle') {
        await WMS_API.sitesAdmin.toggleOnline(id);
        toast('ok', `Toggled ${id}`);
      } else if (act === 'delete') {
        if (!(await confirmModal.simple({
          title: `Archive site "${id}"?`,
          body: 'Only allowed if no users or departments still reference this site. The server will refuse otherwise.',
          confirmLabel: 'Archive',
          danger: true,
        }))) return;
        await WMS_API.sitesAdmin.remove(id);
        toast('ok', `Archived ${id}`);
      } else if (act === 'edit') {
        const detail = await WMS_API.sitesAdmin.get(id);
        const name = prompt('Name', detail.name);
        if (name === null) return;
        const city = prompt('City', detail.city);
        if (city === null) return;
        await WMS_API.sitesAdmin.update(id, { name, city });
        toast('ok', `Updated ${id}`);
      }
      load();
    } catch (err) {
      toast('err', err.message);
    }
  });

  load();
})();
